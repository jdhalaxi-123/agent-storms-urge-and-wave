"""需求澄清（grill-me 风格）端到端测试。

场景一：含糊需求「帮我看看风暴潮」→ 应该先追问（3~5 个带选项的问题），且**不查任何数据**。
场景二：用户回答后 → 应该合并前后轮信息，真的出结果（可以有图）。
场景三：用户说「别问了 直接给」→ 不该再追问。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import llm  # noqa: E402

CALLS = []

_ORIG_FORECAST = llm._call_forecast


def _spy(args):
    CALLS.append(args)
    return _ORIG_FORECAST(args)


llm._call_forecast = _spy


def ask(message, history):
    CALLS.clear()
    text, images = llm.chat(message, history)
    return text, images, list(CALLS)


def show(title, text, images, calls):
    print("=" * 70)
    print(f"【{title}】")
    print(text)
    print(f"--- 图片 {len(images)} 张 | 是否调了 forecast_risk: {bool(calls)}")
    if calls:
        print(f"--- forecast_risk 参数: {calls}")
    print()


def main():
    from datetime import datetime
    print(f"（脚本运行时间：{datetime.now():%Y-%m-%d %H:%M}）")
    print(f"（系统提示里的当前时间：{llm._system_prompt()[-120:]}）\n")

    # ---- 场景一：含糊需求，应先追问且不取数 ----
    t1, i1, c1 = ask("帮我看看风暴潮", [])
    show("场景一 含糊需求", t1, i1, c1)
    asked = t1.count("？") + t1.count("?")
    ok1 = (not c1) and asked >= 2
    print(f">>> 场景一判定：{'通过' if ok1 else '不通过'}"
          f"（提问数={asked}，取数={bool(c1)}）\n")

    # ---- 场景二：回答后应合并信息并出结果 ----
    # 历史用真实 Gradio 结构：助手消息是 (文本, 图片列表) 元组
    hist = [["帮我看看风暴潮", (t1, [])]]
    t2, i2, c2 = ask("厦门，明天，主要看增水会不会超警戒，要过程曲线", hist)
    show("场景二 补充需求后", t2, i2, c2)
    ok2 = bool(c2) or ("厦门" in t2)
    print(f">>> 场景二判定：{'通过' if ok2 else '不通过'}\n")

    # ---- 场景三：明确说别问了 ----
    t3, i3, c3 = ask("别问了，直接给结果", [])
    show("场景三 别问了直接给", t3, i3, c3)
    ok3 = bool(c3)
    print(f">>> 场景三判定：{'通过' if ok3 else '不通过'}\n")

    # ---- 场景四：说“今天”→ 应换算成真实日期，并如实说明数据时效 ----
    t4, i4, c4 = ask("今天厦门的风暴潮什么情况", [])
    show("场景四 今天（时效换算）", t4, i4, c4)
    ok4 = bool(c4)
    print(f">>> 场景四判定：{'通过' if ok4 else '不通过'}\n")

    print("=" * 70)
    print(f"总结：场景一={'OK' if ok1 else 'FAIL'} 场景二={'OK' if ok2 else 'FAIL'} "
          f"场景三={'OK' if ok3 else 'FAIL'} 场景四={'OK' if ok4 else 'FAIL'}")


if __name__ == "__main__":
    main()
