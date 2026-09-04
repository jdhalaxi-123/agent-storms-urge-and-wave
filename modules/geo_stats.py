"""模块② 地理信息提取 · NC 插值 · 统计分析。

【STUB】骨架阶段返回假统计量；
真实实现负责切出目标海域、插值到网格/站点、统计最大增水/超阈时刻/过程曲线。
"""
from orchestrator.contract import ModuleContext


def run(ctx: ModuleContext) -> ModuleContext:
    ctx.results["geo_stats"] = {
        "status": "stub",
        "region": ctx.request.get("region"),
        "max_surge_cm": 87.5,            # 占位：最大增水(cm)
        "peak_time": "未来第3天02时",      # 占位：超阈时刻
        "series": [10, 30, 55, 87, 62],  # 占位：增水过程曲线
    }
    return ctx
