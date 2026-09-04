"""模块接口契约 —— 345 流程模板中「接口」部分的落地。

所有业务模块（modules/ 下的每个实现）都必须遵守本契约：
    输入 ModuleContext，输出 ModuleContext；
    不直接跨模块通信，只通过 ctx.files / ctx.results 传递数据。

数据交换约定（已定）：
    - 进程内：模块间直接传递 ModuleContext 对象（Python dataclass）。
    - 跨进程 / 跨语言 / 交给 LLM 读取：统一用 JSON 序列化（ctx.to_dict() → json.dumps）。
      示例：{"水位等级": "0.3", "nc文件路径": "D:/test.nc"}
    - JSON 是 LLM 最友好的数据格式：工具返回、模块交接、会话记忆都走 JSON。

版本：v1.0
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

# 模块标准执行顺序（两阶段 + 中间选优）
STAGE_ANALYSIS: List[str] = ["meta", "geo_stats", "selector", "assess"]
STAGE_PRESENT: List[str] = ["brief", "visualize"]


@dataclass
class ModuleContext:
    """模块间唯一的数据容器。

    request: 意图槽位（灾种 / 海域 / 时间窗 / 风险类型 / 输出要求）
    files:   数据文件路径映射，如 {"nc_forecast_num": "E:/data/xxx.nc"}
    results: 各模块产出，如 {"geo_stats": {...}, "assess": {...}}
    routes:  场景路由命中结果（该用哪套模块实现）
    meta:    过程元信息（选优结论、版本等）
    """

    request: Dict[str, Any] = field(default_factory=dict)
    files: Dict[str, str] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    routes: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModuleContext":
        return cls(**{k: d.get(k) for k in ("request", "files", "results", "routes", "meta")})


def run_module(ctx: ModuleContext) -> ModuleContext:
    """模块统一入口契约：吃 Context，吐 Context。所有模块照此签名实现。"""
    raise NotImplementedError("每个模块必须实现 run_module(ctx) -> ctx")
