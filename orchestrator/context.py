"""数据上下文辅助：Context 的序列化 / 落盘 / 读回，便于调试与模块间交接。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .contract import ModuleContext


def new_context(request: Dict[str, Any]) -> ModuleContext:
    """按意图槽位新建一个上下文。"""
    return ModuleContext(request=request)


def dump(ctx: ModuleContext, path: Path) -> None:
    """把上下文落盘为 JSON（调试/审计用）。"""
    path.write_text(json.dumps(ctx.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: Path) -> ModuleContext:
    """从 JSON 读回上下文。"""
    return ModuleContext.from_dict(json.loads(path.read_text(encoding="utf-8")))


def to_json(ctx: ModuleContext) -> str:
    """把上下文序列化为 JSON 字符串（给 LLM 读 / 跨进程传递）。"""
    return json.dumps(ctx.to_dict(), ensure_ascii=False)
