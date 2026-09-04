"""模块③ 危险性评估：对照国标预警标准判级。

【STUB】骨架阶段返回假判级；
真实实现按「总水位(增水+潮位) vs 岸线/堤防高程」对照国标（红/橙/黄/蓝）判级，
分场景编写（静远 / 华荣 / 浩宇 / 文芳 / 智峰）。
"""
from orchestrator.contract import ModuleContext


def run(ctx: ModuleContext) -> ModuleContext:
    # TODO: 真实实现 —— 对照国标判级，分场景编写
    ctx.results["assess"] = {
        "status": "stub",
        "level": "橙色预警",            # 占位
        "risk": "存在海水倒灌风险",      # 占位
        "basis": "占位：最大增水 87.5cm 超过橙色阈值",
    }
    return ctx
