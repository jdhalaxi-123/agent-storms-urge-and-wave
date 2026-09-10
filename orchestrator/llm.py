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
    "【画图】当用户要求“画/看/展示”某类图时，调用 forecast_risk 工具，"
    "并通过 plot 参数**只指定用户要的那一类图**（wind=风场、surge_station=站点过程曲线、"
    "surge_field=全场增水分布、wave=海浪波高）；"
    "用户要多种时才用 all。切忌用户只要一种却把各类图都画出来。"
    "用户没提图时不要传 plot（默认按灾种给一张核心图）。"
    "当用户询问数据库/数据位置（如“XX数据在哪”“FTP上有什么”“有没有XX台风的YY数据”）时，"
    "调用 ftp_query 工具查询课题数据库，并把查到的路径/目录内容清楚告诉用户；"
    "只报告工具实际返回的路径，不要推测不存在的路径。"
    "当用户明确要求下载/同步某数据时，调用 ftp_sync 工具同步到本地，并告知同步了多少文件/多大。"
    "注意区分：问“数据在哪/有什么”→ ftp_query；问“预报结论/画图/看风场”→ forecast_risk。"
    "【重要】生成的图片会自动附加到对话中显示，回复里不要再用 markdown 图片语法"
    "（如 ![](...)）或写出本地文件路径，只需简要说明图的内容即可。"
)

FORECAST_TOOL = {
    "type": "function",
    "function": {
        "name": "forecast_risk",
        "description": (
            "查询指定海域的风暴潮或海浪预报风险，并生成预报图"
            "（站点增水/水位过程曲线、全场增水分布、风场图、海浪波高曲线）。"
            "返回预警等级、风险结论与简报。"
            "用户要求“画图/看风场/看预报图”时也调用本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "海域或地名，如：厦门、浙江沿海；缺省为厦门"},
                "disaster": {
                    "type": "string",
                    "enum": ["storm_surge", "wave"],
                    "description": "灾种：风暴潮=storm_surge，海浪=wave",
                },
                "time_window": {"type": "string", "description": "时间窗，如：未来5天"},
                "risk_type": {"type": "string", "description": "风险类型，如：海水倒灌、增水、浪高"},
                "typhoon": {"type": "string", "description": "台风编号（可省略），如：2526、2403、1521、1614；用户未指定台风时省略"},
                "date": {"type": "string", "description": "查看日期（可省略），如：7月22日、2024-07-22；用户指定具体日期时填写，否则省略"},
                "plot": {
                    "type": "string",
                    "enum": ["wind", "surge_station", "surge_field", "wave", "all"],
                    "description": (
                        "需要出图时填写图类型（问什么画什么，不要多给）："
                        "wind=风场图；surge_station=站点增水/水位过程曲线；"
                        "surge_field=全场增水空间分布；wave=海浪波高曲线；"
                        "all=全部图。用户没明确要图时省略（默认按灾种给一张核心图）。"
                    ),
                },
            },
            "required": ["disaster"],
        },
    },
}


FTP_TOOL = {
    "type": "function",
    "function": {
        "name": "ftp_query",
        "description": (
            "查询课题数据库(FTP)上的数据目录/文件位置。用户问“数据在哪”“FTP上有什么”“有没有XX数据”时调用。"
            "FTP 根目录下有 group1~group5（对应课题一~五）；"
            "group1/storm_surge 是风暴潮场, group1/storm_surge/era5 是ERA5风场, "
            "group3/wind 是风场, group3/storm_surge_point 是风暴潮单点。"
            "【重要】只能报告本工具实际返回的路径/文件名，"
            "绝不能凭推测补充未在返回结果中出现的路径；"
            "若某目录不存在会在返回中体现，请如实告知用户“该路径不存在”。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要查看的FTP目录，如 /group3/wind；缺省 /"},
                "keyword": {"type": "string", "description": "可选：按关键字过滤或搜索，如 2526、wave、storm_surge"},
                "search_root": {"type": "string", "description": "可选：递归搜索的起始目录（与keyword配合），如 /group1"},
            },
            "required": [],
        },
    },
}


FTP_SYNC_TOOL = {
    "type": "function",
    "function": {
        "name": "ftp_sync",
        "description": (
            "从课题数据库(FTP)同步数据到本地，供后续预报/绘图使用。"
            "当用户明确要求“下载/同步/拉取某数据”时调用。"
            "注意：单个文件可达数百MB，应先用 ftp_query 确认目录内容，"
            "并在同步前告知用户预计数据量；默认最多同步20个文件。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "remote_dir": {"type": "string", "description": "要同步的FTP目录，如 /group3/wind/typhoon_2526"},
                "keyword": {"type": "string", "description": "可选：只同步文件名含此关键字的文件，如 2025111"},
                "max_files": {"type": "integer", "description": "可选：最多同步文件数，默认20"},
            },
            "required": ["remote_dir"],
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


def _call_ftp(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行 FTP 查询工具：列目录 或 关键字搜索。"""
    from . import ftp_client

    keyword = (args.get("keyword") or "").strip()
    search_root = (args.get("search_root") or "").strip()
    if keyword and search_root:
        res = ftp_client.search(search_root, keyword)
    else:
        res = ftp_client.query(args.get("path") or "/", keyword)
    return res


def _call_ftp_sync(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行 FTP 同步工具：把远程目录下的文件拉到本地。"""
    from . import ftp_client

    return ftp_client.sync_dir(
        args.get("remote_dir", ""),
        keyword=(args.get("keyword") or "").strip(),
        max_files=int(args.get("max_files") or 20),
    )


def _call_forecast(args: Dict[str, Any]) -> Dict[str, Any]:
    """执行预报工具：把 LLM 填的参数转成槽位，跑编排引擎。"""
    from . import engine  # 延迟导入，避免循环依赖

    slots = {
        "disaster": args.get("disaster", "storm_surge"),
        "risk_type": args.get("risk_type", "general"),
        "region": args.get("region") or "厦门",
        "time_window": args.get("time_window", "未指定"),
        "typhoon": args.get("typhoon", ""),
        "date": args.get("date", ""),
        "plot": args.get("plot", ""),
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
    resp = client.chat.completions.create(model=MODEL, messages=messages, tools=[FORECAST_TOOL, FTP_TOOL, FTP_SYNC_TOOL], timeout=120)
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
        # 按工具名分发
        if tc.function.name == "ftp_query":
            result = _call_ftp(args)
        elif tc.function.name == "ftp_sync":
            result = _call_ftp_sync(args)
        else:
            result = _call_forecast(args)
            if result.get("images"):
                images = result["images"]
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

    resp2 = client.chat.completions.create(model=MODEL, messages=messages, timeout=120)
    return resp2.choices[0].message.content or "（未生成回复，请重试）", images
