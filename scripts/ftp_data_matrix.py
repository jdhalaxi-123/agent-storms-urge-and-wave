#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成《FTP 台风数据完整性表》—— 每个台风有哪些数据、缺什么。

用法：
    python scripts/ftp_data_matrix.py                 # 打印到屏幕 + 写 docs/FTP台风数据完整性.md
    python scripts/ftp_data_matrix.py -o 表格.md
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orchestrator.ftp_client import _connect  # noqa: E402

# 数据源定义： (列名, 短名, 远程目录, 文件名匹配, 说明)
SOURCES = [
    ("A.正交场\n天文潮+总水位", "A.正交场", "/group1/storm_surge/正交", "dir/{ty}", "课题一 高精度正交网格"),
    ("B.风暴潮场\n(课题三 2MB)", "B.课题三场", "/group3/storm_surge_field", "typhoon_{ty}", "课题三 全场增水 0.25°"),
    ("C.站点增水\n(8.5KB/天)", "C.站点增水", "/group3/storm_surge_point/new_wind_v2", "typhoon_{ty}", "课题三 4站单点增水"),
    ("D.裁剪场\n天文潮+总水位", "D.裁剪场", "/group5/202609/dataset_GFS_cropped", "{ty}", "课题五 裁剪版"),
    ("E.波浪场\n数值+AI", "E.波浪场", "/group5/202609/regular", "{ty}_regular.nc", "课题五 0.05° 含 hs/hs_torch"),
    ("F.波浪细网格\n数值+AI", "F.波浪细网格", "/group5/202609/regular-H", "{ty}_regular-H.nc", "课题五 1/120° 厦门附近"),
    ("G.实测观测", "G.实测观测", "/group5/202609/observation/out2", "{ty}_observation_qc.nc", "课题五 浮标实测"),
    ("H.非结构网格\n三要素", "H.非结构网格", "/group5/irregular", "{ty}_irregular.nc", "课题五 含 tide/surge/all"),
    ("I.集合AI\n风暴潮", "I.集合AI", "/group5/irregular_surge_Ensemble", "{ty}_irregular_new.nc", "课题五 集合(AI)"),
    ("J.波浪单点\n(10KB/站)", "J.波浪单点", "/group3/TC_wave_point/wave", "typhoon_{ty}", "课题三 16浮标站"),
]
SHORT = {s[0]: s[1] for s in SOURCES}



def ls(ftp, path):
    out = []
    try:
        for n, m in ftp.mlsd(path):
            if n in (".", ".."):
                continue
            out.append({"name": n, "dir": m.get("type") == "dir",
                        "size": int(m.get("size", 0) or 0)})
    except Exception:
        return None
    return out


def probe(ftp, base, pat, ty):
    """返回 (是否存在, 总字节数, 文件数)。支持 dir/{ty} 形式（按台风子目录）。"""
    if pat.startswith("dir/"):
        sub = pat[4:].format(ty=ty)
        entries = ls(ftp, f"{base.rstrip('/')}/{sub}")
        if not entries:
            return False, 0, 0
        tot = sum(e["size"] for e in entries if not e["dir"])
        return True, tot, len([e for e in entries if not e["dir"]])
    if "/" in pat or pat.endswith(".nc"):
        name = pat.format(ty=ty)
        entries = ls(ftp, base)
        if entries is None:
            return False, 0, 0
        for e in entries:
            if e["name"] == name and not e["dir"]:
                return True, e["size"], 1
        return False, 0, 0
    # 目录形式（按台风号命名）
    sub = pat.format(ty=ty)
    entries = ls(ftp, f"{base.rstrip('/')}/{sub}")
    if not entries:
        return False, 0, 0
    tot = sum(e["size"] for e in entries if not e["dir"])
    n = len([e for e in entries if not e["dir"]])
    return (n > 0), tot, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(ROOT / "docs" / "FTP台风数据完整性.md"))
    args = ap.parse_args()

    t0 = time.time()
    ftp = _connect()
    print("扫描 FTP 中…")

    # 台风清单
    tys = set()
    for base, pat in [("/group1/storm_surge/正交", "dir/{ty}"),
                      ("/group3/storm_surge_point/new_wind_v2", "typhoon_{ty}"),
                      ("/group5/202609/dataset_GFS_cropped", "{ty}")]:
        for e in (ls(ftp, base) or []):
            if e["dir"]:
                n = e["name"].replace("typhoon_", "")[:4]
                if n.isdigit():
                    tys.add(n)
    tys = sorted(tys)
    print(f"  共 {len(tys)} 个台风，逐个核对 {len(SOURCES)} 类数据源…")

    matrix = {}
    for i, ty in enumerate(tys, 1):
        row = {}
        for col, _short, base, pat, _note in SOURCES:
            ok, tot, n = probe(ftp, base, pat, ty)
            row[col] = {"ok": ok, "mb": round(tot / 1e6, 2), "n": n}
        matrix[ty] = row
        print(f"  [{i:2d}/{len(tys)}] {ty} 完成")
    ftp.quit()

    # ---------------- 生成 Markdown ----------------
    L = []
    L.append("# FTP 台风期间数据完整性表")
    L.append("")
    L.append(f"扫描时间：{time.strftime('%Y-%m-%d %H:%M')}　|　"
             f"数据源：课题数据库（FTP）　|　台风个例：**{len(tys)} 个**")
    L.append("")

    L.append("## 一、数据源说明")
    L.append("")
    L.append("| 代号 | 数据源 | 路径 | 体积 | 内容 |")
    L.append("| --- | --- | --- | --- | --- |")
    SZ = {
        "A.正交场\n天文潮+总水位": "710 + 921 MB",
        "B.风暴潮场\n(课题三 2MB)": "**2 MB**",
        "C.站点增水\n(8.5KB/天)": "**8.5 KB/文件**",
        "D.裁剪场\n天文潮+总水位": "37~117 MB ×2",
        "E.波浪场\n数值+AI": "2716 MB",
        "F.波浪细网格\n数值+AI": "2716 MB",
        "G.实测观测": "1.4 MB",
        "H.非结构网格\n三要素": "0.2~1.2 GB",
        "I.集合AI\n风暴潮": "0.1~0.6 GB",
        "J.波浪单点\n(10KB/站)": "**10 KB × 16**",
    }
    for col, _short, base, pat, note in SOURCES:
        L.append(f"| {col.split('.')[0]} | {col.split('.')[1].replace(chr(10),' ')} | "
                 f"`{base}/{pat}` | {SZ.get(col,'')} | {note} |")
    L.append("")

    L.append("## 二、完整性矩阵")
    L.append("")
    L.append("> ✅ = 有　— = 没有　（括号内为该数据源总体积 MB）")
    L.append("")
    heads = [c.split(".")[0] for c in [s[0] for s in SOURCES]]
    L.append("| 台风 | " + " | ".join(heads) + " | 齐全度 |")
    L.append("| --- | " + " | ".join(":-:" for _ in heads) + " | :-: |")
    for ty in tys:
        cells, cnt = [], 0
        for col, *_ in SOURCES:
            v = matrix[ty][col]
            if v["ok"]:
                cnt += 1
                cells.append(f"✅ {v['mb']:.1f}" if v["mb"] >= 1 else "✅")
            else:
                cells.append("—")
        L.append(f"| **{ty}** | " + " | ".join(cells) + f" | {cnt}/{len(SOURCES)} |")
    L.append("")

    L.append("## 三、汇总统计")
    L.append("")
    L.append("| 数据源 | 覆盖台风数 | 占比 |")
    L.append("| --- | :-: | :-: |")
    for col, *_ in SOURCES:
        n = sum(1 for ty in tys if matrix[ty][col]["ok"])
        L.append(f"| {col.replace(chr(10),' ')} | {n} / {len(tys)} | {n/len(tys)*100:.0f}% |")
    L.append("")

    L.append("## 四、缺口清单（每个台风缺什么）")
    L.append("")
    L.append("| 台风 | 齐全度 | 缺少的数据源 |")
    L.append("| --- | :-: | --- |")
    for ty in tys:
        miss = [SHORT[col] for col, *_ in SOURCES if not matrix[ty][col]["ok"]]
        cnt = len(SOURCES) - len(miss)
        L.append(f"| **{ty}** | {cnt}/{len(SOURCES)} | {'、'.join(miss) if miss else '**齐全**'} |")
    L.append("")

    L.append("## 五、判级所需三要素的覆盖情况")
    L.append("")
    L.append("| 三要素 | 可从哪些数据源得到 | 覆盖台风数 |")
    L.append("| --- | --- | :-: |")
    tide = sum(1 for ty in tys if matrix[ty]["A.正交场\n天文潮+总水位"]["ok"]
               or matrix[ty]["D.裁剪场\n天文潮+总水位"]["ok"]
               or matrix[ty]["H.非结构网格\n三要素"]["ok"])
    surge = sum(1 for ty in tys if matrix[ty]["B.风暴潮场\n(课题三 2MB)"]["ok"]
                or matrix[ty]["C.站点增水\n(8.5KB/天)"]["ok"]
                or matrix[ty]["H.非结构网格\n三要素"]["ok"])
    total = sum(1 for ty in tys if matrix[ty]["A.正交场\n天文潮+总水位"]["ok"]
                or matrix[ty]["D.裁剪场\n天文潮+总水位"]["ok"]
                or matrix[ty]["H.非结构网格\n三要素"]["ok"])
    L.append(f"| **天文潮** | A 正交场 output_0 / D 裁剪场 output_0 / H 非结构网格 elev_tide | {tide} / {len(tys)} |")
    L.append(f"| **风暴增水** | B 课题三场 surge / C 单点 surge / H 非结构网格 elev_surge | {surge} / {len(tys)} |")
    L.append(f"| **总水位** | A、D 的 output_4 / H 非结构网格 elev_all | {total} / {len(tys)} |")
    L.append("")

    md = "\n".join(L)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"\n已生成：{out}　（{len(md)} 字符，耗时 {time.time()-t0:.0f}s）")

    # 屏幕简表
    print("\n" + "=" * 100)
    print("简表（✅有 —无）")
    print("=" * 100)
    print("台风  " + "".join(f"{h:>6s}" for h in heads) + "   齐全度")
    for ty in tys:
        line = f"{ty:6s}"
        for col, *_ in SOURCES:
            line += f"{'✅' if matrix[ty][col]['ok'] else '—':>6s}"
        cnt = sum(1 for col, *_ in SOURCES if matrix[ty][col]["ok"])
        print(line + f"   {cnt}/{len(SOURCES)}")


if __name__ == "__main__":
    main()
