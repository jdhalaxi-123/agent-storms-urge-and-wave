"""编排引擎：两阶段调度 + 中间选优。

阶段一（分析）：meta → geo_stats → selector(选优) → assess
阶段二（呈现）：brief → visualize

这是编排层的核心：只负责「调用谁的、什么顺序、传什么数据」，
不实现任何业务算法（算法都在 modules/ 里）。
"""
from __future__ import annotations

from typing import Any, Dict

import modules  # 顶层业务模块包

from .contract import ModuleContext
from . import intent, router, memory, geo_domain


def run(request: str) -> Dict[str, Any]:
    """字符串入口：规则解析槽位后走完整链路。"""
    slots = intent.parse(request)
    return run_with_slots(slots, raw=request)


def run_with_slots(slots: Dict[str, Any], raw: str = "") -> Dict[str, Any]:
    """槽位入口：LLM 工具调用直接给结构化参数。"""
    # 覆盖范围校验：超出范围不展示任何数据，只返回文字说明
    region = slots.get("region", "")
    chk = geo_domain.check_region(region, slots.get("lon"), slots.get("lat"))
    if not chk.get("ok"):
        msg = chk.get("message", "")
        reason = chk.get("reason", "out_of_domain")
        memory.append({
            "request": raw or slots.get("raw", ""),
            "slots": slots,
            reason: chk.get("matched"),
        })
        return {
            "reply": msg,
            "images": [],
            "docx_path": None,
            "brief_template": reason,
            "need_clarify": reason == "need_clarify",
            "out_of_domain": chk.get("matched") if reason == "out_of_domain" else None,
            "meta": {"status": reason, "matched": chk.get("matched")},
        }

    # 场景路由：槽位 → 命中的模块实现标识
    routes = router.resolve(slots)

    # 组装上下文
    ctx = ModuleContext(request=slots, routes=routes)

    # 阶段一：分析
    ctx = modules.meta.run(ctx)        # ① 定位 NC
    ctx = modules.geo_stats.run(ctx)   # ② 提取 + 插值 + 统计
    ctx = modules.selector.run(ctx)    # ★ 数值 vs 智能 选优
    ctx = modules.assess.run(ctx)      # ③ 国标判级

    # 阶段二：呈现
    ctx = modules.brief.run(ctx)       # ④ Markdown 简报
    ctx = modules.visualize.run(ctx)   # ⑤ 图片

    # 会话记忆落盘（防降智，硬性要求）
    memory.append({
        "request": raw or slots.get("raw", ""),
        "slots": slots,
        "assess": ctx.results.get("assess", {}),
        "brief": ctx.results.get("brief", {}),
    })

    # 汇总返回
    return {
        "reply": ctx.results.get("brief", {}).get("markdown", ""),
        "images": ctx.results.get("visualize", {}).get("images", []),
        "docx_path": ctx.results.get("brief", {}).get("docx_path"),
        "brief_template": ctx.results.get("brief", {}).get("template"),
        "meta": ctx.meta,
    }
