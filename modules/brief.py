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
        # ⭐ 时间统一写成"世界时 UTC（北京时 …）"：nc 时间轴是 UTC，
        #    只写 12:00 会被当成北京时，差 8 小时（也避免图文时间写法不一致）
        _pt = pk.get("time_label") or str(pk.get("time", "")).replace("T", " ")
        L.append(f"- **过程最大风速 {pk.get('speed_ms')} m/s（{pk.get('beaufort')}，"
                 f"约 {pk.get('speed_kmh')} km/h）**，出现在 "
                 f"{pk.get('lon')}°E, {pk.get('lat')}°N，{_pt}")
    if st.get("mean_peak_ms") is not None:
        _mt = (st.get("mean_peak_time") or "")
        _mt_b = st.get("mean_peak_time_bjt") or ""
        _mt_txt = f"{_mt} UTC（北京时 {_mt_b[11:]}）" if _mt and _mt_b else _mt
        L.append(f"- 区域平均风速峰值 {st.get('mean_peak_ms')} m/s（{_mt_txt}）")
    if counts:
        L.append(f"- 峰值时刻达到 6 级（≥10.8 m/s）的格点 {counts.get('g6')} 个，"
                 f"8 级（≥17.2 m/s）{counts.get('g8')} 个，"
                 f"10 级（≥24.5 m/s）{counts.get('g10')} 个（共 {counts.get('n')} 个格点）")
    stations = st.get("stations") or {}
    if stations:
        L += ["", "**代表站点最大风**", "",
              "| 站点 | 最大风速 | 出现时间（世界时 / 北京时） | 风力 |",
              "| --- | --- | --- | --- |"]
        for cn, v in stations.items():
            t = str(v.get("time", "")).replace("T", " ")
            tb = str(v.get("time_bjt", "") or "")
            t_txt = f"{t[5:]} UTC / {tb[5:]} BJT" if (t and tb) else t
            ms = v.get("speed_ms")
            bf = ""
            try:
                from modules import ai_daily as _ad
                bf = _ad.beaufort(float(ms))
            except Exception:
                bf = ""
            L.append(f"| {cn} | {ms} m/s | {t_txt} | {bf} |")
    if st.get("start"):
        _s0, _s1 = str(st.get("start")).replace("T", " "), str(st.get("end")).replace("T", " ")
        _b0, _b1 = str(st.get("start_bjt") or ""), str(st.get("end_bjt") or "")
        _rng = f"{_s0} ~ {_s1}（UTC）"
        if _b0 and _b1:
            _rng += f"，即北京时 {_b0} ~ {_b1}"
        L += ["", f"- 时效：{_rng}（逐时，共 {st.get('n_time')} 个时次）"]
    if st.get("lon_range"):
        L.append(f"- 范围：{st['lon_range'][0]}~{st['lon_range'][1]}°E，"
                 f"{st['lat_range'][0]}~{st['lat_range'][1]}°N")
    L += ["", f"- 数据来源：课题三每日风场（{wind.get('file')}，"
              f"{wind.get('size_mb')} MB），为 AI 风暴潮/海浪预报的驱动风场。"]
    if st.get("tz_note"):
        L.append(f"- {st.get('tz_note')}")
    _scope = (f"**{st.get('only_date')} 当日**" if st.get("only_date") else "**本次请求范围内**")
    L += ["", f"（附图：风速填色 + 风向箭头，取{_scope}过程风速最强时刻；"
              "**图题上的最大风速与时刻就是上面这条**）"]
    return "\n".join(L)


def _fusion_markdown(ctx: ModuleContext, fus: Dict[str, Any]) -> str:
    """第五组融合产品小节：总水位 / 有效波高（含量值、时刻、判级、口径）。"""
    L: List[str] = []
    for kind in ("tide", "wave"):
        v = fus.get(kind) or {}
        fld = v.get("field") or {}
        d = v.get("point") or {}
        if not fld or not d:
            continue
        name = v.get("name") or ctx.request.get("region") or "目标点"
        if kind == "tide":
            L += [f"## {name} 风暴潮总水位（第五组融合产品）", ""]
            L.append(f"- **过程最高总水位 {d.get('max_m')} m（{(d.get('max_m') or 0)*100:.0f} cm）**"
                     f"，最低 {d.get('min_m')} m，变幅 {d.get('range_m')} m")
            L.append(f"- 最高出现在 {_ft(d.get('peak_time'))} UTC"
                     f"（北京时 {(d.get('peak_time_bjt') or '')[11:]}）")
            try:
                from . import assess
                w = assess._find_warn(name)
                if w:
                    lv = assess.judge_by_warn_level(float(d.get("max_m") or 0) * 100.0, w)
                    L.append(f"- **判级（总水位对照该站四色警戒潮位）："
                             f"{'未达到预警阈值' if lv == '无' else lv + '警戒'}**；"
                             f"该站警戒潮位 蓝{w.get('blue')}/黄{w.get('yellow')}/"
                             f"橙{w.get('orange')}/红{w.get('red')} cm")
                else:
                    L.append("- 该点没有本站四色警戒潮位，未做分级")
            except Exception:
                pass
        else:
            L += [f"## {name} 有效波高（第五组融合产品）", ""]
            L.append(f"- **过程最大有效波高 {d.get('max_m')} m**，最低 {d.get('min_m')} m")
            L.append(f"- 最大出现在 {_ft(d.get('peak_time'))} UTC"
                     f"（北京时 {(d.get('peak_time_bjt') or '')[11:]}）")
            try:
                from . import assess
                lv = assess.judge_wave_level(float(d.get("max_m") or 0))
                L.append(f"- **判级（海浪分级）：{'未达到预警级别' if lv == '无' else lv + '预警'}**"
                         "（蓝 2.5 / 黄 4.0 / 橙 6.0 / 红 9.0 m）")
            except Exception:
                pass
        L.append(f"- 取值格点 {d.get('cell_lon')}°E, {d.get('cell_lat')}°N"
                 f"（距站点约 {d.get('dist_km')} km，"
                 f"{'随时间变化' if d.get('varied') else '该格点变化很小'}）")
        L.append(f"- 口径：第五组融合产品（AI + 数值模式融合），"
                 f"{'福建中南部精细 0.0083°' if fld.get('fine') else '全场 0.05°'}；"
                 f"起报 {fld.get('issue')}；覆盖 {_ft((fld.get('times') or [''])[0])} ~ "
                 f"{_ft((fld.get('times') or [''])[-1])} UTC；"
                 f"基准：平均海平面；时间：UTC（括号内为北京时）；文件 {fld.get('file')}")
        L.append("")
    if L:
        L.append("> 说明：融合产品中约 30~45% 的格点为“常数源”（整段几乎不变），"
                 "取点时已优先挑选随时间变化的格点；上面已注明所用格点与到站距离。")
    return "\n".join(L)


def _ft(s: Any) -> str:
    return str(s or "")[:16].replace("T", " ")


def _with_fusion(ctx: ModuleContext, markdown: str) -> str:
    """在简报正文后追加"第五组融合产品"小节（挂了才加）。"""
    fus = ctx.results.get("fusion") or {}
    if not fus:
        return markdown
    try:
        add = _fusion_markdown(ctx, fus)
    except Exception as e:  # noqa: BLE001
        print(f"[brief] 融合小节生成失败：{e}")
        return markdown
    return (markdown or "") + ("\n\n" + add if add else "")


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
        # ⭐ 用户明确说"不要简报 / 不要 Word" → 不生成 Word（也就不会有下载链接）
        _no_brief = bool(request.get("no_brief"))
        if not _no_brief:
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
        else:
            markdown += "\n\n> （按您的要求：**本次不生成 Word 简报**。）"
        if not _no_brief:
            try:      # 标记最近简报，供 UI 追加可点链接
                (OUT_DIR / ".last_brief").write_text(str(docx_path or ""), encoding="utf-8")
            except Exception:
                pass
        ctx.results["brief"] = {
            "markdown": _with_fusion(ctx, markdown),
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
        "markdown": _with_fusion(ctx, markdown),
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
