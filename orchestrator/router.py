"""场景路由：槽位 → 命中的模块实现标识。

路由表从 scenarios/routes.yaml 读取，不写死在代码里。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

ROUTES_FILE = Path(__file__).resolve().parent.parent / "scenarios" / "routes.yaml"


def resolve(slots: Dict[str, Any]) -> Dict[str, Any]:
    """根据槽位返回命中的场景实现标识。"""
    table = _load()
    disaster = slots.get("disaster", "unknown")
    # 数据源：骨架阶段默认「数值模式」，后续由选优/用户指定
    source = slots.get("source", "数值模式")
    level = slots.get("level", "未定级")

    scene = table.get(disaster, {}).get(source, {})
    return {
        "disaster": disaster,
        "source": source,
        "level": level,
        "impls": scene.get("impls", {}),
    }


def _load() -> Dict[str, Any]:
    if not ROUTES_FILE.exists():
        return {}
    try:
        import yaml
        with open(ROUTES_FILE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return {}
