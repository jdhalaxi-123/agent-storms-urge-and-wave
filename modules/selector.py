"""★ 选优模块：数值模式 vs 智能预报，进评估前选出更可信结果。

【STUB】骨架阶段按固定规则选优；
真实实现按团队定的指标（RMSE / 与实测对比等）选优。
"""
from orchestrator.contract import ModuleContext


def run(ctx: ModuleContext) -> ModuleContext:
    # TODO: 真实实现 —— 用评估指标（RMSE / 与实测对比）选优
    chosen = "智能预报"  # 占位：固定规则

    ctx.meta["selected_source"] = chosen
    ctx.results["selector"] = {
        "status": "stub",
        "chosen": chosen,
        "reason": "占位：默认选智能预报（待定指标）",
    }
    return ctx
