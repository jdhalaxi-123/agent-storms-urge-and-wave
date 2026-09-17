# -*- coding: utf-8 -*-
"""链路专检：体检全绿、但提问出不来图时用这个定位。

按顺序检查：
    ① gradio 版本（>=6 会导致界面显示异常：图生成了但看不到）
    ② .env 配置（DeepSeek / FTP）
    ③ FTP 能否取到数据（直接下一份最小文件）
    ④ 跑一次真实查询（厦门风暴潮），打印取到什么、出了几张图
    ⑤ 若没出图：打印各模块的中间结果与报错，指出卡在哪一环

用法（项目目录下）：
    .venv\\Scripts\\python.exe scripts\\check_pipeline.py
    .venv\\Scripts\\python.exe scripts\\check_pipeline.py "闽南的海浪场"     # 自定义问题
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "✅", "❌", "⚠️"


def show_gradio() -> None:
    print("\n① 界面库版本")
    try:
        import gradio as gr
        v = getattr(gr, "__version__", "?")
        print(f"  gradio {v}")
        if v.startswith("6") or v.startswith("7"):
            print(f"  {BAD} gradio 版本过新！本项目按 5.x 编写，6.x 会让聊天里的图片显示不出来。")
            print("     修复：.venv\\Scripts\\python.exe -m pip install \"gradio>=5.0,<6.0\"")
        else:
            print(f"  {OK} 版本符合要求（>=5,<6）")
        try:
            import gradio.components as gc
            print(f"  {OK} 组件模块可导入")
        except Exception as e:  # noqa: BLE001
            print(f"  {WARN} 组件模块导入异常：{e}")
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 无法导入 gradio：{e}")


def show_env() -> None:
    print("\n② 配置")
    env = ROOT / ".env"
    if not env.exists():
        print(f"  {BAD} 没有 .env")
        return
    cfg = {}
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            cfg[k.strip()] = v.strip()
    ds = cfg.get("DEEPSEEK_API_KEY", "")
    print(f"  DeepSeek: {OK + ' 已配置' if ds.startswith('sk-') else BAD + ' 未配置'}")
    ftp_ok = all(cfg.get(k) for k in ("FTP_HOST", "FTP_USER", "FTP_PASS"))
    print(f"  FTP     : {OK + ' ' + cfg.get('FTP_HOST','') + ':' + cfg.get('FTP_PORT','') if ftp_ok else BAD + ' 未配置'}")


def show_ftp() -> bool:
    print("\n③ FTP 取数（下最小的一份：厦门站单点增水，约 10 KB）")
    try:
        from modules import ai_daily
        p = ai_daily.load_point_surge("XMN")
        if p:
            print(f"  {OK} 取到数据：{Path(p.get('file') or '').name}  "
                  f"共 {p.get('n_times')} 小时")
            return True
        print(f"  {BAD} 取不到数据（FTP 配置或网络问题）→ 先跑 scripts/check_ftp.py 看细节")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 取数异常：{type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def run_query(question: str) -> None:
    print(f"\n④ 跑真实查询：{question!r}")
    try:
        from orchestrator import engine, llm
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 导入编排层失败：{e}")
        return

    # 拦截引擎调用，看 LLM 有没有真的去取数
    slots_seen = []
    orig = engine.run_with_slots

    def spy(slots, raw=""):
        slots_seen.append(dict(slots))
        return orig(slots, raw=raw)

    engine.run_with_slots = spy
    try:
        text, images = llm.chat(question, [])
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} llm.chat 抛异常：{type(e).__name__}: {e}")
        traceback.print_exc()
        return
    finally:
        engine.run_with_slots = orig

    print(f"  取数调用：{len(slots_seen)} 次" + (f"  槽位={slots_seen}" if slots_seen else ""))
    print(f"  文字长度：{len(text or '')} 字")
    print(f"  图片数量：{len(images or [])}")
    for im in (images or []):
        p = Path(im)
        exists = p.exists()
        size = f"{p.stat().st_size/1024:.0f} KB" if exists else "文件不存在！"
        print(f"    · {p.name}  {size}  {OK if exists else BAD}")

    print("\n⑤ 结论")
    if not slots_seen:
        print(f"  {WARN} 模型这次**没有去取数**，而是在反问（需求澄清协议）。")
        print("     这是设计行为：问题里没说清「时间/要素」时，它先问 2~3 个选项。")
        print(f"     文字是这样的：{(text or '')[:80]}…")
        print("     → 按它问的回答一次，它就会取数出图；")
        print("     → 想一次到位，把话说全，例如：")
        print("        「厦门站未来5天的风暴增水过程曲线」")
        print("        「闽南的过程最大增水空间分布图」")
        return
    if images and all(Path(i).exists() for i in images):
        print(f"  {OK} 后端出图正常（{len(images)} 张，文件都在磁盘上）。")
        print("     若浏览器里看不到图 → 是**界面显示**问题，重点看 ① 的 gradio 版本；")
        print("     也可以直接打开上面列出的文件确认图是好的。")
    elif images:
        print(f"  {WARN} 有图片路径但文件不存在，出图过程被中断。")
    else:
        print(f"  {BAD} 取了数但一张图都没出来 → 看上面的报错（多半是画图环节异常）。")


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else "厦门站未来5天的风暴增水过程曲线"
    print("=" * 70)
    print("链路专检：为什么出不了图")
    print("=" * 70)
    print(f"（测试问题：{question}）")
    show_gradio()
    show_env()
    show_ftp()
    run_query(question)
    print("\n" + "=" * 70)
    print("把本页输出整段发出来即可定位（含上面所有 ✅/❌ 行）")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
