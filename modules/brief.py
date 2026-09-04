"""模块④ 简报生成：输出 Markdown + 可导出 Word。

实现方式：调用 brief_tpl 模板引擎，把上游产出的结构化 dict 渲染成
    - ctx.results["brief"]["markdown"]   对话简报文本
    - ctx.results["brief"]["docx_path"]  导出 Word 路径（有模板数据才生成）
    - ctx.results["brief"]["template"]   命中的模板类型

数据来源（按优先级）：
    1. ctx.results["assess"] 若带完整模板字段(stations/segments/...)，直接用；
    2. 无完整字段时，降级为骨架摘要简报（保留原 stub 行为，保证链路不中断）。
"""
from pathlib import Path
from typing import Any, Dict

from orchestrator.contract import ModuleContext

from . import brief_tpl

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def run(ctx: ModuleContext) -> ModuleContext:
    request = ctx.request or {}
    assess = ctx.results.get("assess", {}) or {}
    selector = ctx.results.get("selector", {}) or {}

    # ① 若上游已产出符合模板结构的完整数据，走真实模板引擎
    data = _build_template_data(ctx, request, assess, selector)
    if data:
        markdown = brief_tpl.render_markdown(data)
        docx_path = None
        try:
            docx_path = str(brief_tpl.render_docx(data, OUT_DIR))
        except Exception:
            docx_path = None  # Word 生成失败不影响对话
        ctx.results["brief"] = {
            "markdown": markdown,
            "docx_path": docx_path,
            "template": data.get("template_type", "storm_surge_alert"),
            "status": "template",
        }
        return ctx

    # ② 降级：骨架摘要简报（仅文字）
    region = request.get("region", "未知海域")
    tw = request.get("time_window", "未指定")
    markdown = (
        f"## {region}风暴潮风险简报\n\n"
        f"- 时间窗：{tw}\n"
        f"- 采用结果：{selector.get('chosen', '未选优')}\n"
        f"- 预警等级：{assess.get('level', '未判级')}\n"
        f"- 结论：{assess.get('risk', '未评估')}\n"
    )
    ctx.results["brief"] = {
        "markdown": markdown,
        "docx_path": None,
        "template": "fallback",
        "status": "fallback",
    }
    return ctx


def _build_template_data(
    ctx: ModuleContext,
    request: Dict[str, Any],
    assess: Dict[str, Any],
    selector: Dict[str, Any],
) -> Dict[str, Any]:
    """把上下文各模块产出合成为模板引擎需要的统一 data dict。

    任何模块直接在 results 里塞了「标准简报字段」即可触发。
    """
    # 若 assess 已经生成标准模板 data（真实模块将来会这样产出），直接透传
    if assess.get("brief_data"):
        return dict(assess["brief_data"])

    # 骨架阶段没有真实数据，返回 None 走降级
    return None
