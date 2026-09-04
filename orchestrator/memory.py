"""会话记忆：防降智（每轮落盘 + 新对话读回）。

这是编排层的【硬性要求】组件，对应项目的 AgentRecord 机制：
    - 每轮对话结束后 append() 落盘关键信息；
    - 新对话开始时 recent() 读回，用于恢复上下文；
    - 保证多轮对话中 agent 不丢关键上下文（降智）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

RECORD_FILE = Path(__file__).resolve().parent.parent / "AgentRecord.session.jsonl"


def append(entry: Dict[str, Any]) -> None:
    """追加一条会话记录（每轮对话结束时调用）。"""
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def recent(n: int = 10) -> List[Dict[str, Any]]:
    """读回最近 n 条记录，用于新对话恢复上下文。"""
    if not RECORD_FILE.exists():
        return []
    lines = RECORD_FILE.read_text(encoding="utf-8").strip().splitlines()
    out: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
