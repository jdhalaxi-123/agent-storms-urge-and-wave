"""意图解析：把用户自然语言拆成结构化槽位。

骨架阶段：先用规则解析兜底（零依赖、可跑通）；
后续接入真实 LLM（DeepSeek）时，替换 parse_with_llm，规则解析保留为降级方案。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# 海域地名字典（先内置示例；正式版由团队维护为完整字典）
REGION_DICT = {
    "厦门": "厦门海域",
    "泉州": "泉州海域",
    "福州": "福州海域",
    "漳州": "漳州海域",
    "浙江": "浙江沿海",
    "福建": "福建沿海",
    "广东": "广东沿海",
    "海南": "海南沿海",
}

# 灾种关键词
DISASTER_RULES: List[Tuple[List[str], str]] = [
    (["风暴潮", "增水", "倒灌"], "storm_surge"),
    (["海浪", "浪高", "波高"], "wave"),
]

# 风险类型关键词
RISK_RULES: List[Tuple[List[str], str]] = [
    (["海水倒灌", "倒灌"], "seawater_intrusion"),
    (["漫滩", "漫顶"], "overtopping"),
    (["增水"], "surge"),
    (["浪高", "波高"], "wave_height"),
]


def parse(text: str) -> Dict[str, Any]:
    """入口：优先 LLM，失败回退规则解析。"""
    # TODO: 接入真实 LLM 时，改为先 try parse_with_llm(text) 再回退规则
    return parse_by_rules(text)


def parse_by_rules(text: str) -> Dict[str, Any]:
    """规则解析兜底（零依赖）。"""
    return {
        "disaster": _match_any(text, DISASTER_RULES, "unknown"),
        "risk_type": _match_any(text, RISK_RULES, "general"),
        "region": _match_region(text),
        "time_window": _match_time_window(text),
        "raw": text,
    }


def parse_with_llm(text: str) -> Dict[str, Any]:
    """占位：后续接 DeepSeek 等 LLM，用结构化输出解析槽位。"""
    raise NotImplementedError("待接入 LLM")


def _match_any(text: str, rules: List[Tuple[List[str], str]], default: str) -> str:
    for keywords, value in rules:
        if any(k in text for k in keywords):
            return value
    return default


def _match_region(text: str) -> str:
    for name, full in REGION_DICT.items():
        if name in text:
            return full
    return "未知海域"


def _match_time_window(text: str) -> Optional[str]:
    m = re.search(r"未来\s*(\d+)\s*(天|小时|h|d)", text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return "未指定"
