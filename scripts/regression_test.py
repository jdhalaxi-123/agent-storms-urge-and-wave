#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全台风回归测试 —— 检查每个台风的风暴潮/海浪查询是否正常。

检查项：
  ① 有数据、有图（需要出图时）
  ② 简报标题与灾种一致（问海浪不能返回风暴潮）
  ③ 峰值时间落在简报标注的"数据范围"内
  ④ 数值在合理范围（增水/水位/浪高）
  ⑤ 没有张冠李戴（浪高不能把浮标站说成大陆近岸站）

用法：
    python scripts/regression_test.py                # 全部台风
    python scripts/regression_test.py 2403 1513      # 指定台风
    python scripts/regression_test.py --wave-only    # 只测海浪
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator import engine  # noqa: E402

# FTP 上的台风（数据完整 10 个 + 部分数据 11 个 + 早期个例）
COMPLETE = ["1513", "1521", "1601", "1614", "1617", "1709", "1808", "2305", "2311", "2403"]
PARTIAL = ["1909", "2004", "2106", "2418", "2420", "2421", "2504", "2506", "2511", "2518", "2524"]
EARLY = ["1006", "1011", "1013", "1111", "1209", "1307", "1312", "1410", "1710", "2006", "2109"]


def parse_range(reply: str):
    m = re.search(r"数据范围：(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ~ (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", reply)
    return (m.group(1), m.group(2)) if m else (None, None)


def check(desc: str, slots: dict, expect: str) -> dict:
    """expect: 'surge' | 'wave'"""
    t0 = time.time()
    slots = {**slots, "time_window": "未指定", "risk_type": "general",
             "typhoon": slots.get("typhoon", ""), "date": "", "plot": slots.get("plot", "")}
    res = {"desc": desc, "ok": True, "issues": [], "sec": 0.0, "imgs": 0}
    try:
        r = engine.run_with_slots(dict(slots), raw="reg")
    except Exception as e:  # noqa: BLE001
        res["ok"] = False
        res["issues"].append(f"异常 {type(e).__name__}: {str(e)[:80]}")
        return res
    res["sec"] = round(time.time() - t0, 1)
    reply = r.get("reply") or ""
    flat = reply.replace("\n", " ")
    res["imgs"] = len(r.get("images") or [])

    # ① 有内容
    if len(flat.strip()) < 30:
        res["issues"].append("简报内容为空")
    # ② 灾种一致
    if expect == "wave":
        if "海浪" not in flat:
            res["issues"].append("问海浪但简报里没有『海浪』")
        if "风暴潮蓝色预警" in flat or "风暴潮红色预警" in flat or "风暴潮黄色预警" in flat \
                or "风暴潮橙色预警" in flat:
            res["issues"].append("问海浪却返回风暴潮预警标题")
        if res["imgs"] == 0 and "暂未取到" not in flat:
            res["issues"].append("海浪无图且未说明原因")
    else:
        if "风暴潮" not in flat:
            res["issues"].append("问风暴潮但简报里没有『风暴潮』")
    # ③ 峰值时间在数据范围内
    s, e = parse_range(reply)
    if s and e:
        for tm in re.findall(r"（(\d{2}-\d{2} \d{2}:\d{2})）", flat) + \
                  re.findall(r"峰值时刻 (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", flat):
            full = tm if len(tm) == 16 else f"{s[:4]}-{tm}"
            if not (s <= full <= e):
                res["issues"].append(f"峰值时间 {full} 超出数据范围 {s}~{e}")
    # ④ 数值合理
    for hs in re.findall(r"(\d+\.?\d*) 米左右的有效波高", flat):
        v = float(hs)
        if not (0.1 <= v <= 25):
            res["issues"].append(f"波高异常 {v} m")
    for cm in re.findall(r"最大风暴增水[^0-9]{0,6}(\d+\.?\d*)", flat):
        v = float(cm)
        if not (-100 <= v <= 500):
            res["issues"].append(f"增水异常 {v} cm")
    # ⑤ 张冠李戴：浮标站浪高不能写成大陆站"近岸"
    if expect == "wave" and re.search(r"(厦门|崇武|晋江|东山)近岸海域将出现", flat) and "浮标" in flat:
        res["issues"].append("把浮标站浪高说成大陆站近岸")

    res["ok"] = not res["issues"]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("typhoons", nargs="*")
    ap.add_argument("--wave-only", action="store_true")
    ap.add_argument("--surge-only", action="store_true")
    args = ap.parse_args()

    tys = args.typhoons or (COMPLETE + PARTIAL + EARLY)
    rows = []
    print(f"回归测试：{len(tys)} 个台风\n")
    for i, ty in enumerate(tys, 1):
        if not args.wave_only:
            r = check(f"{ty} 风暴潮-厦门", {"disaster": "storm_surge", "region": "厦门",
                                            "typhoon": ty}, "surge")
            rows.append(r)
            print(f"  [{i:2d}/{len(tys)}] {r['desc']:22s} {'OK ' if r['ok'] else 'FAIL'} "
                  f"{r['sec']:5.1f}s 图{r['imgs']}  {'; '.join(r['issues'])}")
        if not args.surge_only:
            r = check(f"{ty} 海浪", {"disaster": "wave", "region": "厦门",
                                     "typhoon": ty, "plot": "wave"}, "wave")
            rows.append(r)
            print(f"  [{i:2d}/{len(tys)}] {r['desc']:22s} {'OK ' if r['ok'] else 'FAIL'} "
                  f"{r['sec']:5.1f}s 图{r['imgs']}  {'; '.join(r['issues'])}")

    bad = [r for r in rows if not r["ok"]]
    print(f"\n{'='*88}")
    print(f"合计 {len(rows)} 项，通过 {len(rows)-len(bad)}，失败 {len(bad)}")
    if bad:
        print("\n失败明细：")
        for r in bad:
            print(f"  ✗ {r['desc']}: {'; '.join(r['issues'])}")
    # 写报告
    out = ROOT / "docs" / "回归测试报告.md"
    L = ["# 全台风回归测试报告", "",
         f"测试时间：{time.strftime('%Y-%m-%d %H:%M')}　共 {len(rows)} 项",
         "", "| 用例 | 结果 | 耗时 | 图片 | 问题 |", "| --- | :-: | :-: | :-: | --- |"]
    for r in rows:
        L.append(f"| {r['desc']} | {'✅' if r['ok'] else '❌'} | {r['sec']}s | {r['imgs']} | "
                 f"{'; '.join(r['issues']) or '—'} |")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"\n报告已写入：{out}")


if __name__ == "__main__":
    main()
