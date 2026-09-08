"""LLM 对话大脑：DeepSeek 驱动，支持常识问答 + 预报工具调用（Function Calling）。

职责：
    - 常识/知识类问题（"风暴潮是什么"、"厦门在哪"）→ LLM 直接回答
    - 预报需求 → LLM 调用 forecast_risk 工具 → 编排引擎 → 结果回 LLM 组织语言
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import OpenAI

MODEL = "deepseek-v4-pro"
BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = (
    "你是「风暴潮与海浪智能预报助手」。"
    "对风暴潮、海浪、海洋预报相关的常识或知识问题，直接清晰回答；"
    "当用户需要查询某个海域的具体预报风险（海水倒灌、增水、浪高、预警等级等）时，"
    "调用 forecast_risk 工具获取结果，再把结果整理成简洁易懂的回复。"
)

FORECAST_TOOL = {
    "type": "function",
    "function": {
        "name": "forecast_risk",
        "description": "查询指定海域的风暴潮或海浪预报风险，返回预警等级、风险结论与简报",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "海域或地名，如：厦门、浙江沿海"},
                "disaster": {
                    "type": "string",
                    "enum": ["storm_surge", "wave"],
                    "description": "灾种：风暴潮=storm_surge，海浪=wave",
                },
                "time_window": {"type": "string", "description": "时间窗，如：未来5天"},
                "risk_type": {"type": "string", "description": "风险类型，如：海水倒灌、增水、浪高"},
            },
            "required": ["region", "disaster"],
        },
    },
}


def _load_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在项目根目录 .env 文件里配置")


_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=_load_api_key(), base_url=BASE_URL)
    return _client


def _call_forecast(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行预报工具：把 LLM 填的参数转成槽位，跑编排引擎。"""
    from . import engine  # 延迟导入，避免循环依赖

    slots = {
        "disaster": args.get("disaster", "unknown"),
        "risk_type": args.get("risk_type", "general"),
        "region": args.get("region", "未知海域"),
        "time_window": args.get("time_window", "未指定"),
        "raw": "llm",
    }
    result = engine.run_with_slots(slots, raw=json.dumps(args, ensure_ascii=False))
    # 把 Word 导出路径一并交给 LLM，方便在回复里提示下载
    if result.get("docx_path"):
        result["reply"] = (
            f"{result.get('reply', '')}\n\n📄 正式简报 Word 已生成：{result['docx_path']}"
        )
    return result


def chat(message: str, history: List[List[str]]) -> Tuple[str, List[str]]:
    """一轮对话。history 为 Gradio 传入的 [[user, assistant], ...]，返回 (文本, 图片列表)。

    每次 API 调用带 120s 超时，避免网络阻塞导致前端挂起。
    """
    client = _get_client()

    if not message or not str(message).strip():
        return "（没有识别到有效内容，请重试）", []

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user_msg, bot_msg in history:
        # 跳过空消息，避免 DeepSeek 报 "content or tool_calls must be set"
        if user_msg:
            messages.append({"role": "user", "content": str(user_msg)})
        if bot_msg:
            messages.append({"role": "assistant", "content": str(bot_msg)})
    messages.append({"role": "user", "content": str(message)})

    # 第一次调用：LLM 决定直接回答还是调工具
    resp = client.chat.completions.create(model=MODEL, messages=messages, tools=[FORECAST_TOOL], timeout=120)
    msg = resp.choices[0].message

    # 未调工具：直接返回文本
    if not msg.tool_calls:
        return msg.content or "（未生成回复，请重试）", []

    # 调了工具：手动构造 assistant 的 tool_calls 消息补回
    messages.append({
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in msg.tool_calls
        ],
    })

    images: List[str] = []
    for tc in msg.tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        result = _call_forecast(args)
        images = result.get("images", [])
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    resp2 = client.chat.completions.create(model=MODEL, messages=messages, timeout=120)
    return resp2.choices[0].message.content or "（未生成回复，请重试）", images
