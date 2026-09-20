"""模块④ 简报生成：输出 Markdown + 可导出 Word。

实现方式：调用 brief_tpl 模板引擎，把上游产出的结构化 dict 渲染成
    - ctx.results["brief"]["markdown"]   对话简报文本
    - ctx.results["brief"]["docx_path"]  导出 Word 路径（有模板数据才生成）
    - ctx.results["brief"]["template"]   命中的模板类型

数据来源（按优先级）：
    1. ctx.results["assess"] 若带完整模板字段(stations/segments/...)，直接用；
    2. 无完整字段时，降级为骨架摘要简报（保留原 stub 行为，保证链路不中断）。
"""
from pathlib import Path
from typing import Any, Dict

from orchestrator.contract import ModuleContext
from orchestrator import paths

from . import brief_tpl

# 简报输出目录：统一落在数据根目录下（默认 <项目>\stormdata\briefs）
OUT_DIR = paths.BRIEFS_DIR


def _is_wind_only(ctx: ModuleContext) -> bool:
    """本次请求就是来看风场的。"""
    req = ctx.request or {}
    plot = str(req.get("plot", "") or "").strip().lower()
    dis = str(req.get("disaster", "") or "").strip().lower()
    return plot == "wind" or dis in ("wind", "风场", "风")


def _wind_markdown(ctx: ModuleContext, wind: Dict[str, Any],
                   st: Dict[str, Any]) -> str:
    """风场简报：只讲风，不讲增水。"""
    req = ctx.request or {}
    region = str(req.get("region") or "关注海域")
    d = str(wind.get("date") or "")
    date_txt = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else "—"
    pk = st.get("peak") or {}
    counts = st.get("counts") or {}

    L = [f"## {region} 风场预报（每日风场 · 起报 {date_txt}）", ""]
    if pk:
        L.append(f"- **过程最大风速 {pk.get('speed_ms')} m/s（{pk.get('beaufort')}，"
                 f"约 {pk.get('speed_kmh')} km/h）**，出现在 "
                 f"{pk.get('lon')}°E, {pk.get('lat')}°N，{str(pk.get('time','')).replace('T',' ')}")
    if st.get("mean_peak_ms") is not None:
        L.append(f"- 区域平均风速峰值 {st.get('mean_peak_ms')} m/s"
                 f"（{str(st.get('mean_peak_time','')).replace('T',' ')}）")
    if counts:
        L.append(f"- 峰值时刻达到 6 级（≥10.8 m/s）的格点 {counts.get('g6')} 个，"
                 f"8 级（≥17.2 m/s）{counts.get('g8')} 个，"
                 f"10 级（≥24.5 m/s）{counts.get('g10')} 个（共 {counts.get('n')} 个格点）")
    stations = st.get("stations") or {}
    if stations:
        L += ["", "**代表站点最大风**", "", "| 站点 | 最大风速 | 出现时间 | 风力 |",
              "| --- | --- | --- | --- |"]
        for cn, v in stations.items():
            t = str(v.get("time", "")).replace("T", " ")
            ms = v.get("speed_ms")
            bf = ""
            try:
                from modules import ai_daily as _ad
                bf = _ad.beaufort(float(ms))
            except Exception:
                bf = ""
            L.append(f"| {cn} | {ms} m/s | {t} | {bf} |")
    if st.get("start"):
        L += ["", f"- 时效：{str(st.get('start')).replace('T',' ')} ~ "
                  f"{str(st.get('end')).replace('T',' ')}（逐时，共 {st.get('n_time')} 个时次）"]
    if st.get("lon_range"):
        L.append(f"- 范围：{st['lon_range'][0]}~{st['lon_range'][1]}°E，"
                 f"{st['lat_range'][0]}~{st['lat_range'][1]}°N")
    L += ["", f"- 数据来源：课题三每日风场（{wind.get('file')}，"
              f"{wind.get('size_mb')} MB），为 AI 风暴潮/海浪预报的驱动风场。"]
    L += ["", "（附图：风速填色 + 风向箭头，取关注海域风速最强时刻）"]
    return "\n".join(L)


def run(ctx: ModuleContext) -> ModuleContext:
    request = ctx.request or {}
    assess = ctx.results.get("assess", {}) or {}
    selector = ctx.results.get("selector", {}) or {}

    # ⓪ 风场专问：直接出风场简报（不要用风暴潮的口径讲风场）
    wind = ctx.results.get("daily_wind") or {}
    st = wind.get("stats") or {}
    if st and _is_wind_only(ctx):
        ctx.results["brief"] = {
            "markdown": _wind_markdown(ctx, wind, st),
            "docx_path": None,
            "template": "wind_field",
            "status": "template",
        }
        return ctx

    # ① 若上游已产出符合模板结构的完整数据，走真实模板引擎
    data = _build_template_data(ctx, request, assess, selector)
    if data:
        markdown = brief_tpl.render_markdown(data)
        docx_path = None
        # 优先按**官方简报版式**生成 Word（三行抬头/36pt 大标题/编号+签发/潮位表…）；
        # 失败时回退到通用模板转换器，保证一定有一份 Word。
        try:
            from . import brief_official
            docx_path = str(brief_official.render(data, OUT_DIR))
        except Exception as e:  # noqa: BLE001
            print(f"[brief] 官方版式 Word 生成失败（改用通用模板）：{e}")
            try:
                docx_path = str(brief_tpl.render_docx(data, OUT_DIR))
            except Exception:
                docx_path = None  # Word 生成失败不影响对话
        try:      # 标记最近简报，供 UI 追加可点链接
            (OUT_DIR / ".last_brief").write_text(str(docx_path or ""), encoding="utf-8")
        except Exception:
            pass
        ctx.results["brief"] = {
            "markdown": markdown,
            "docx_path": docx_path,
            "template": data.get("template_type", "storm_surge_alert"),
            "status": "template",
        }
        return ctx

    # ② 降级：骨架摘要简报（仅文字）
    region = request.get("region", "未知海域")
    tw = request.get("time_window", "未指定")
    markdown = (
        f"## {region}风暴潮风险简报\n\n"
        f"- 时间窗：{tw}\n"
        f"- 采用结果：{selector.get('chosen', '未选优')}\n"
        f"- 预警等级：{assess.get('level', '未判级')}\n"
        f"- 结论：{assess.get('risk', '未评估')}\n"
    )
    ctx.results["brief"] = {
        "markdown": markdown,
        "docx_path": None,
        "template": "fallback",
        "status": "fallback",
    }
    return ctx


def _build_template_data(
    ctx: ModuleContext,
    request: Dict[str, Any],
    assess: Dict[str, Any],
    selector: Dict[str, Any],
) -> Dict[str, Any]:
    """把上下文各模块产出合成为模板引擎需要的统一 data dict。

    任何模块直接在 results 里塞了「标准简报字段」即可触发。
    """
    # 若 assess 已经生成标准模板 data（真实模块将来会这样产出），直接透传
    if assess.get("brief_data"):
        return dict(assess["brief_data"])

    # 骨架阶段没有真实数据，返回 None 走降级
    return None
