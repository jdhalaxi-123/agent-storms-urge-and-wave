"""简报模板引擎 —— 依据厦门海洋预报台对外发布格式提炼。

结构约定：由上游(geo_stats/assess/selector/LLM)填充一份结构化 dict `data`，
本模块负责把它渲染成两种输出：
    - render_markdown(data) -> str            （对话里返回的简报文本）
    - render_docx(data, output_dir) -> Path   （可下载的正式红头 Word 文档）

不同 template_type 对应不同预测内容：
    - storm_surge_alert   风暴潮警报（含 潮位×警戒潮位 对照表）
    - wave_alert          海浪警报（含 分海域浪高 分段表）
    - wave_message        海浪消息（无级别，等级略低）
    - marine_env_forecast 海洋环境预报（含 风/浪 时段表 + 潮汐曲线）
    - situation_analysis  形势分析预测（分析文字 + 潮位表）

`data` 统一字段（按需提供，缺省自动降级）：
    agency      发布单位（默认 自然资源部厦门海洋预报台）
    title       标题
    time        发布时间   如 "2021年09月10日16时"
    number      编号       如 "风暴潮2021-010" / "海浪2026-030"
    signer      签发人
    basis       发布依据（应急预案名称）
    summary     正文总述段
    alert_level 概述里的预警级别（蓝/黄/橙/红）
    stations    潮位表: [{station,date,time,high_tide_cm,warn_*,level}]
    typhoon     台风名/编号
    segments    分海域段: [{region, description, level}]
    notice      提示句
    tip         预警提示
    targets     发往单位
    contact     联系人
    phone       联系电话
    fax         传真
    website     网址
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

# 警戒潮位分级（cm -> 颜色）通用默认。真实值由数据/国标传入。
DEFAULT_WARN_TABLE = [("700", "蓝色"), ("720", "黄色"), ("740", "橙色"), ("760", "红色")]


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _t(data: Dict[str, Any], key: str, default: Any = "") -> Any:
    v = data.get(key)
    return default if v in (None, "") else v


def _agency(data: Dict[str, Any]) -> str:
    return _t(data, "agency", "自然资源部厦门海洋预报台")


def _header_lines(data: Dict[str, Any]) -> List[str]:
    """素材里常见的「时间 / 编号 / 签发」并排头部行。"""
    time = _t(data, "time")
    number = _t(data, "number")
    signer = _t(data, "signer")
    parts = []
    if time:
        parts.append("时间：" + time)
    if number:
        parts.append("编号：" + number)
    if signer:
        parts.append("签发：" + signer)
    return ["　　　　".join(parts)]


def _footer_lines(data: Dict[str, Any]) -> List[str]:
    """落款：发往 / 联系人 / 电话 / 传真 / 网址。"""
    lines = []
    targets = _t(data, "targets")
    contact = _t(data, "contact")
    phone = _t(data, "phone")
    fax = _t(data, "fax")
    website = _t(data, "website")
    if targets:
        lines.append("发往：" + targets)
    if contact:
        left = f"联系人：{contact}"
        right = f"联系电话：{phone}" if phone else ""
        lines.append(left + ("　　" + right if right else ""))
    if fax or website:
        seg = []
        if fax:
            seg.append("传真：" + fax)
        if website:
            seg.append("网　　址：" + website)
        lines.append("　　".join(seg))
    return lines


# --------------------------------------------------------------------------- #
# Markdown 渲染
# --------------------------------------------------------------------------- #
def render_markdown(data: Dict[str, Any]) -> str:
    tpl_type = _t(data, "template_type", "storm_surge_alert")
    lines: List[str] = []

    lines.append("# " + _agency(data))
    title = _t(data, "title")
    if title:
        lines.append("## " + title)
    header = _header_lines(data)
    if header:
        lines.append("> " + header[0])
    lines.append("")

    basis = _t(data, "basis")
    summary = _t(data, "summary")
    if basis and summary:
        lines.append(f"{_agency(data)}根据{basis}发布{title}。")
    if summary:
        lines.append(summary)
    lines.append("")

    # 各模板特有的表格
    if tpl_type in ("storm_surge_alert", "situation_analysis"):
        lines += _md_station_table(data)
    elif tpl_type in ("wave_alert", "wave_message"):
        lines += _md_segment_table(data)
    elif tpl_type == "marine_env_forecast":
        lines += _md_wave_table(data)

    notice = _t(data, "notice")
    if notice:
        lines.append(notice)
    tip = _t(data, "tip")
    if tip:
        lines.append(tip)
    lines.append("")

    lines += _footer_lines(data)
    return "\n".join(lines)


def _md_station_table(data: Dict[str, Any]) -> List[str]:
    stations = data.get("stations") or []
    if not stations:
        return []
    lines = ["| 站位 | 日期 | 时间 | 高潮位(cm) | 警戒潮位(cm) | 预警级别 |", "| --- | --- | --- | --- | --- | --- |"]
    for s in stations:
        # 把 700/720/740/760 等分级串成一个 "700(蓝)/720(黄)..." 展示
        warn = s.get("warn", "")
        lines.append(
            f"| {_t(s, 'station')} | {_t(s, 'date')} | {_t(s, 'time')} "
            f"| {_t(s, 'high_tide_cm')} | {warn} | {_t(s, 'level')} |"
        )
    return lines


def _md_segment_table(data: Dict[str, Any]) -> List[str]:
    segs = data.get("segments") or []
    if not segs:
        return []
    lines = ["| 海域 | 预报描述 | 预警级别 |", "| --- | --- | --- |"]
    for s in segs:
        lines.append(f"| {_t(s, 'region')} | {_t(s, 'description')} | {_t(s, 'level')} |")
    return lines


def _md_wave_table(data: Dict[str, Any]) -> List[str]:
    rows = data.get("wave_table") or []
    if not rows:
        return []
    lines = ["| 时段 | 海面风 | 有效波高(米) |", "| --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {_t(r, 'period')} | {_t(r, 'wind')} | {_t(r, 'wave')} |")
    return lines


# --------------------------------------------------------------------------- #
# Word 渲染（红头 + 表格）
# --------------------------------------------------------------------------- #
def render_docx(data: Dict[str, Any], output_dir: Path) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Pt, RGBColor

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    title = _t(data, "title", "海洋预警简报")
    safe = "".join(ch for ch in title if ch not in r'\/:*?"<>|')
    out = output_dir / f"{safe}.docx"

    doc = Document()

    # 红字主标题
    agency = _agency(data)
    if agency:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(agency)
        run.bold = True
        run.font.size = Pt(16)
        run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

    if title:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.bold = True
        run.font.size = Pt(16)

    # 头部：时间/编号/签发
    header = _header_lines(data)
    if header:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(header[0]).font.size = Pt(10.5)

    for para in (
        _t(data, "basis"),
        _t(data, "summary"),
    ):
        if para:
            doc.add_paragraph(para)

    tpl_type = _t(data, "template_type", "storm_surge_alert")
    if tpl_type in ("storm_surge_alert", "situation_analysis"):
        _docx_station_table(doc, data)
    elif tpl_type in ("wave_alert", "wave_message"):
        _docx_segment_table(doc, data)
    elif tpl_type == "marine_env_forecast":
        _docx_wave_table(doc, data)

    for para in (_t(data, "notice"), _t(data, "tip")):
        if para:
            doc.add_paragraph(para)

    # 落款
    for line in _footer_lines(data):
        if line:
            doc.add_paragraph(line)

    doc.save(str(out))
    return out


def _docx_station_table(doc, data: Dict[str, Any]) -> None:
    stations = data.get("stations") or []
    if not stations:
        return
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Pt

    headers = ["站位", "日期", "时间", "高潮位(cm)", "警戒潮位(cm)", "预警级别"]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
    for s in stations:
        row = table.add_row().cells
        row[0].text = _t(s, "station")
        row[1].text = _t(s, "date")
        row[2].text = _t(s, "time")
        row[3].text = str(_t(s, "high_tide_cm"))
        row[4].text = _t(s, "warn")
        row[5].text = _t(s, "level")


def _docx_segment_table(doc, data: Dict[str, Any]) -> None:
    segs = data.get("segments") or []
    if not segs:
        return
    from docx.enum.table import WD_TABLE_ALIGNMENT

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, h in enumerate(["海域", "预报描述", "预警级别"]):
        hdr[i].text = h
    for s in segs:
        row = table.add_row().cells
        row[0].text = _t(s, "region")
        row[1].text = _t(s, "description")
        row[2].text = _t(s, "level")


def _docx_wave_table(doc, data: Dict[str, Any]) -> None:
    rows = data.get("wave_table") or []
    if not rows:
        return
    from docx.enum.table import WD_TABLE_ALIGNMENT

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    for i, h in enumerate(["时段", "海面风", "有效波高(米)"]):
        hdr[i].text = h
    for r in rows:
        row = table.add_row().cells
        row[0].text = _t(r, "period")
        row[1].text = _t(r, "wind")
        row[2].text = _t(r, "wave")
