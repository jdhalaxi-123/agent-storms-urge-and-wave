"""会话记忆：防降智（每轮落盘 + 新对话读回）。

这是编排层的【硬性要求】组件，对应项目的 AgentRecord 机制：
    - 每轮对话结束后 append() 落盘关键信息；
    - 新对话开始时 recent() 读回，用于恢复上下文；
    - 保证多轮对话中 agent 不丢关键上下文（降智）。

另有【完整对话记录】：
    - append_chat()  每轮落盘：用户原话 + Agent回复 + 时间（供网页历史面板查看）
    - recent_chats() 读回最近 N 轮
    - render_history_md() 渲染成 Markdown（网页展示用）
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

RECORD_FILE = Path(__file__).resolve().parent.parent / "AgentRecord.session.jsonl"
# 完整对话记录（用户问答原文）
CHAT_FILE = Path(__file__).resolve().parent.parent / "AgentRecord.chat.jsonl"


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


# --------------------------------------------------------------------------- #
# 完整对话记录（网页"历史对话"面板用）
# --------------------------------------------------------------------------- #
def append_chat(user: str, bot: str, meta: Dict[str, Any] | None = None) -> None:
    """每轮对话落盘：用户原话 + Agent 回复 + 时间戳。"""
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user": (user or "").strip(),
        "bot": (bot or "").strip(),
    }
    if meta:
        rec["meta"] = meta
    try:
        CHAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CHAT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 记录失败不影响对话


def recent_chats(n: int = 20) -> List[Dict[str, Any]]:
    """读回最近 n 轮对话记录（按时间正序返回）。"""
    if not CHAT_FILE.exists():
        return []
    try:
        lines = CHAT_FILE.read_text(encoding="utf-8").strip().splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def render_history_md(n: int = 20) -> str:
    """把最近 n 轮对话渲染成 Markdown（网页历史面板显示用）。"""
    recs = recent_chats(n)
    if not recs:
        return "（暂无历史对话记录）"
    lines = [f"**最近 {len(recs)} 轮对话**（共 {_chat_total()} 轮已保存）", ""]
    for i, r in enumerate(recs, 1):
        ts = r.get("ts", "")
        u = (r.get("user") or "").replace("\n", " ").strip()
        b = (r.get("bot") or "").replace("\n", " ").strip()
        if len(u) > 120:
            u = u[:120] + "…"
        if len(b) > 200:
            b = b[:200] + "…"
        lines.append(f"**{i}. [{ts}]**")
        lines.append(f"- 👤 你：{u}")
        lines.append(f"- 🤖 助手：{b}")
        lines.append("")
    return "\n".join(lines)


def _chat_total() -> int:
    """已保存的对话总轮数。"""
    if not CHAT_FILE.exists():
        return 0
    try:
        return len([l for l in CHAT_FILE.read_text(encoding="utf-8").splitlines() if l.strip()])
    except Exception:
        return 0
