"""模块③ 危险性评估：对照国标预警标准判级。

真实实现：
    输入 geo_stats 的站点统计(max_surge_cm 等)，
    按风暴潮增水阈值判级(蓝/黄/橙/红)，并生成 brief_data(简报模板字段)，
    供 brief.py 渲染为厦门中心格式 Markdown + Word。

警戒阈值(增水 cm, 经验值, 可参数化覆盖)：
    蓝色 >= 30, 黄色 >= 50, 橙色 >= 80, 红色 >= 120
    （真实业务按「总水位 vs 警戒潮位表」判级，接入潮位后升级）
"""
from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, Optional

import numpy as np

from orchestrator.contract import ModuleContext

# 增水判级阈值 (cm)
LEVELS = [("红色", 120.0), ("橙色", 80.0), ("黄色", 50.0), ("蓝色", 30.0)]

# 各站警戒潮位表（cm）：蓝/黄/橙/红
# 来源：四色警戒潮位.et（陶老师提供），85黄零基准
# 水尺零点基准 = 85黄零值 + "水尺零点与85黄零关系"差值
#   换算证明：厦门 373+327=700 / 393+327=720 / 413+327=740 / 433+327=760 ✓
#   即：水尺零点警戒(700/720/740/760) = 85黄零警戒(373/393/413/433) + 327
STATION_WARN_LEVELS = {
    "厦门": {"blue": 373, "yellow": 393, "orange": 413, "red": 433, "datum": 327,
             "color": "373/393/413/433", "wm_color": "700/720/740/760"},
    "崇武": {"blue": 361, "yellow": 381, "orange": 401, "red": 431, "datum": 449,
             "color": "361/381/401/431", "wm_color": "810/830/850/880"},
    "晋江": {"blue": 345, "yellow": 365, "orange": 395, "red": 425, "datum": 487,
             "color": "345/365/395/425", "wm_color": "832/852/882/912"},
    "东山": {"blue": 255, "yellow": 265, "orange": 285, "red": 305, "datum": 495,
             "color": "255/265/285/305", "wm_color": "750/760/780/800"},
}
# 厦门站名带"厦门港"等别名；后缀（站/港/海洋站/观测站…）统一归一化，
# 避免"厦门站""崇武海洋站"这类写法查不到警戒潮位（测试报告第 6 条）
STATION_NAME_MAP = {
    "厦门": "厦门", "厦门港": "厦门", "厦门(XMN)": "厦门", "厦门站": "厦门",
    "东山东港": "东山", "东山东港(DSN)": "东山", "东山": "东山", "东山站": "东山",
    "崇武": "崇武", "崇武(CWU)": "崇武", "崇武站": "崇武",
    "晋江": "晋江", "晋江(JNJ)": "晋江", "晋江站": "晋江",
}

# 站名里可以剥掉的后缀（按长度从长到短剥）
_STATION_SUFFIXES = ("海洋观测站", "海洋站", "观测站", "潮位站", "验潮站", "水文站",
                     "站点", "站", "港", "测站")
_CODE_SUFFIX_RE = re.compile(r"[(（][A-Za-z]{2,4}[)）]\s*$")


def normalize_station(name: str) -> str:
    """把用户/上游给的站名归一到警戒潮位表的键（厦门/崇武/晋江/东山）。

    "厦门站"→厦门，"厦门港"→厦门，"东山东港站"→东山，"崇武海洋站"→崇武，
    "崇武(CWU)"→崇武；认不出来就原样返回（后续查表会自然落空，不会编数）。
    """
    s = str(name or "").strip()
    if not s:
        return s
    if s in STATION_NAME_MAP:
        return STATION_NAME_MAP[s]
    base = _CODE_SUFFIX_RE.sub("", s).strip()
    if base in STATION_NAME_MAP:
        return STATION_NAME_MAP[base]
    for _ in range(3):                     # 最多剥 3 层后缀
        cut = False
        for suf in _STATION_SUFFIXES:
            if base.endswith(suf) and len(base) > len(suf):
                base = base[: -len(suf)].strip()
                cut = True
                break
        if not cut:
            break
        if base in STATION_NAME_MAP:
            return STATION_NAME_MAP[base]
    # 再退一步：包含关系（"厦门西海域"→厦门）
    for k, v in STATION_NAME_MAP.items():
        if k and k in base:
            return v
    return STATION_NAME_MAP.get(base, base)


def judge(max_surge_cm: float) -> str:
    """按最大增水判级。"""
    for name, th in LEVELS:
        if max_surge_cm >= th:
            return name
    return "无"


def _warn_level_text(level: str) -> str:
    if level == "无":
        return "未达到预警阈值"
    return f"{level}预警"


def _data_range_text(ctx: ModuleContext, geo: dict) -> str:
    """数据覆盖的真实日期范围描述（如 '2025-11-10 00:00 ~ 2025-11-16 23:00'）。"""
    s = geo.get("data_start", "")
    e = geo.get("data_end", "")
    if s and e:
        return f"数据范围：{s} ~ {e}"
    if s:
        return f"数据起始：{s}"
    return ""


def _find_warn(station_name: str) -> Optional[dict]:
    """按站名(含别名/后缀)找警戒潮位表。"""
    key = normalize_station(station_name)
    return STATION_WARN_LEVELS.get(key) or STATION_WARN_LEVELS.get(station_name)


def judge_by_warn_level(total_level_cm: float, warn: dict) -> str:
    """总潮位判级：水尺/85黄零总水位对照警戒潮位表。

    total_level_cm 与 warn 同基准即可（统一转换后调用）。
    """
    if not warn:
        return judge(total_level_cm)
    if total_level_cm >= warn["red"]:
        return "红色"
    if total_level_cm >= warn["orange"]:
        return "橙色"
    if total_level_cm >= warn["yellow"]:
        return "黄色"
    if total_level_cm >= warn["blue"]:
        return "蓝色"
    return "无"


def _is_wind_only(ctx) -> bool:
    """用户这次就是来看风场的。"""
    req = getattr(ctx, "request", None) or {}
    plot = str(req.get("plot", "") or "").strip().lower()
    dis = str(req.get("disaster", "") or "").strip().lower()
    return plot == "wind" or dis in ("wind", "风场", "风")


def _freshness_text(ctx, geo: Dict[str, Any]) -> str:
    """数据时效说明。

    风场有独立更新节奏（前一日 22:00 后上传当天），
    不能拿“每日风暴潮预报尚未更新”去说风场。
    """
    if _is_wind_only(ctx):
        wind = (getattr(ctx, "results", None) or {}).get("daily_wind") or {}
        d = str(wind.get("date") or "")
        if len(d) == 8:
            return (f"风场数据：人工智能方法每日风场，起报 {d[:4]}-{d[4:6]}-{d[6:]}，"
                    f"每日更新（通常前一日 22:00 后上传当天）。")
        return ""
    fresh = (geo or {}).get("freshness") or {}
    return fresh.get("note_target") or fresh.get("note_today") or ""


def _extra_note(geo: Dict[str, Any], ctx=None) -> str:
    """附加上数据来源与实测对比信息（FTP 台风期间数据）。"""
    parts = []
    # ⭐ 数据时效说明（每日预报有固定更新时点）
    ftxt = (_freshness_text(ctx, geo) if ctx is not None
            else ((geo.get("freshness") or {}).get("note_target")
                  or (geo.get("freshness") or {}).get("note_today") or ""))
    if ftxt:
        parts.append(ftxt)
    if geo.get("ai_daily"):
        parts.append(f"数据来源：{geo.get('data_source','人工智能方法')}"
                     f"（起报 {geo.get('forecast_date','')}，"
                     f"{geo.get('forecast_span','')}）。")
    obs = geo.get("observation") or {}
    if obs:
        bits = []
        if obs.get("wave_H_max") is not None:
            bits.append(f"最大有效波高 {obs['wave_H_max']} m")
        if obs.get("tide_tide_max") is not None:
            bits.append(f"最高潮位 {obs['tide_tide_max']} m")
        if bits:
            parts.append(f"实测对照：本台风浮标实测{'、'.join(bits)}"
                         f"（{obs.get('n_buoy')} 个浮标站 / {obs.get('n_tide')} 个潮位站，"
                         f"可用于计算预报误差）。")
    wp = geo.get("wave_points") or []
    if wp:
        top = wp[0]
        if top.get("max_hs_m") is not None:
            parts.append(f"浮标预报波高最大 {top['max_hs_m']} m（站号 {top.get('station')}），"
                         f"对应海浪{judge_wave_level(top['max_hs_m'])}预警。")
    if geo.get("data_source"):
        parts.append(f"数据来源：{geo['data_source']}，按需取数、未落地全量数据。")
    return ("\n" + "\n".join(parts)) if parts else ""


def judge_wave_level(hs_m: float) -> str:
    for name, th in (("红色", 9.0), ("橙色", 6.0), ("黄色", 4.0), ("蓝色", 2.5)):
        if hs_m >= th:
            return name
    return "无"


def _field_brief(ctx: ModuleContext, geo: dict, region: str) -> Optional[Dict[str, Any]]:
    """场查询（区域性问题）的简报：**用空间分布的方式描述**，而不是只报一个点。

    产出：区域峰值、出现位置与时刻、分级格点数、站点对照。
    """
    st = geo.get("field_stats") or {}
    if not st:
        return None
    is_wave = geo.get("field_kind") == "wave"
    unit = "m" if is_wave else "cm"
    vmax = st.get("max_m") if is_wave else st.get("max_cm")
    vmean = st.get("mean_m") if is_wave else st.get("mean_cm")
    pk_dt = st.get("peak_dt")
    L = st.get("levels") or {}
    n = st.get("n_cells") or 0
    grid = geo.get("field_grid") or {}

    if is_wave:
        segs = [("红色(≥9m)", L.get("红色(≥9m)", 0)), ("橙色(6~9m)", L.get("橙色(6~9m)", 0)),
                ("黄色(4~6m)", L.get("黄色(4~6m)", 0)), ("蓝色(2.5~4m)", L.get("蓝色(2.5~4m)", 0))]
        lvl = ("红色" if vmax >= 9 else "橙色" if vmax >= 6 else "黄色" if vmax >= 4
               else "蓝色" if vmax >= 2.5 else "无")
        seg_txt = "；".join(f"{k} **{v}** 个格点" for k, v in segs if v) or "区域内各点均未达海浪预警阈值"
    else:
        segs = [("红色(≥120cm)", L.get("红色(≥120cm)", 0)), ("橙色(80~120cm)", L.get("橙色(80~120cm)", 0)),
                ("黄色(50~80cm)", L.get("黄色(50~80cm)", 0)), ("蓝色(30~50cm)", L.get("蓝色(30~50cm)", 0))]
        lvl = ("红色" if vmax >= 120 else "橙色" if vmax >= 80 else "黄色" if vmax >= 50
               else "蓝色" if vmax >= 30 else "无")
        seg_txt = "；".join(f"{k} **{v}** 个格点" for k, v in segs if v) \
            or "区域内各点均未达风暴潮增水预警阈值（30cm）"

    hours = st.get("n_hours") or (len((geo.get("sites") or [{}])[0].get("series_full") or []))
    peak_place = f"{st.get('peak_lon')}°E, {st.get('peak_lat')}°N"
    rb = geo.get("field_box")
    box_txt = f"（{rb[0]}~{rb[1]}°E，{rb[2]}~{rb[3]}°N）" if rb else ""
    title = f"{region}{'海浪' if is_wave else '风暴潮'}{'警报' if lvl != '无' else '预报'}"
    summary = (
        f"基于人工智能方法，{region}海域{box_txt}"
        + (f"未来 {hours} 小时内，" if hours else "")
        + f"**过程最大{'有效波高' if is_wave else '风暴增水'}为 {vmax} {unit}**，"
        f"出现在 **{peak_place}**"
        + (f"（{pk_dt:%m-%d %H:%M}）" if pk_dt else "") + f"；区域平均 {vmean} {unit}。\n\n"
        f"**空间分布**：{seg_txt}（区域内共 {n} 个有效网格点，分辨率 {grid.get('res')}°）。"
    )
    note = (
        f"注：本简报为**区域（面）预报**，不是单点预报 —— 数据取自人工智能方法场"
        f"（{'海浪 hs_torch' if is_wave else '风暴潮增水 surge'}），起报日 {geo.get('field_date')}，"
        f"覆盖 {grid.get('lon_min')}~{grid.get('lon_max')}°E / {grid.get('lat_min')}~{grid.get('lat_max')}°N，"
        f"分辨率 {grid.get('res')}°。判级标准："
        f"{'有效波高分级（蓝2.5/黄4.0/橙6.0/红9.0 m）' if is_wave else '风暴增水分级（蓝30/黄50/橙80/红120 cm）'}。"
        f"区域内站点位置已在图上标出；如需具体站点的过程曲线，请指定站点名（厦门/崇武/晋江/东山东港）。"
    )
    # ⭐ 数据时效说明（今天的出来没有 / 请求日期是否超范围；风场请求用风场自己的日期）
    fresh_txt = _freshness_text(ctx, geo)
    if fresh_txt:
        note = fresh_txt + "\n" + note
    return {
        "template_type": "wave_alert" if is_wave else "storm_surge_alert",
        "agency": "自然资源部厦门海洋预报台",
        "title": title,
        "time": "（生成时刻）",
        "number": "",
        "signer": "",
        "basis": "《自然资源部厦门海洋中心海洋灾害应急执行预案（风暴潮、海浪、海啸）》",
        "summary": summary,
        "data_range": _data_range_text(ctx, geo),
        "stations": [] if is_wave else [{
            "station": f"{region}区域峰值",
            "date": pk_dt.strftime("%Y-%m-%d") if pk_dt else "",
            "time": pk_dt.strftime("%m-%d %H:%M") if pk_dt else "",
            "high_tide_cm": vmax,
            "warn": "30/50/80/120(增水分级)",
            "level": lvl,
        }],
        "segments": [{"region": f"{region}（区域峰值）",
                      "description": f"{'有效波高' if is_wave else '最大增水'}约 {vmax} {unit}",
                      "level": "未达到预警级别" if lvl == "无" else f"{lvl}预警"}] if is_wave else [],
        "notice": "请沿海各有关单位密切关注我台后续风暴潮预警报。",
        "tip": "预警提示：请沿海相关部门关闭危险区域的海滨浴场和休闲娱乐场所，加固薄弱危险区域的海堤等设施，做好防潮准备和应急措施。",
        "note": note,
        "targets": "市委办、市政府办、市防汛办",
        "contact": "陶小琴",
        "phone": "0592－2065005，18705925573",
        "fax": "0592—5905381",
        "website": "http://www.fjocean.com",
    }


def run(ctx: ModuleContext) -> ModuleContext:
    geo = ctx.results.get("geo_stats", {}) or {}
    sites = geo.get("sites", []) or []
    src = geo.get("source", "")

    # ⭐ 场查询（区域性问题）：走空间分布描述，不走单点判级
    if geo.get("field_query") and geo.get("field_stats"):
        region = ctx.request.get("region", "未指定海域")
        bd = _field_brief(ctx, geo, region)
        if bd:
            st = geo["field_stats"]
            is_wave = geo.get("field_kind") == "wave"
            vmax = st.get("max_m") if is_wave else st.get("max_cm")
            lvl = ("红色" if (is_wave and vmax >= 9) or (not is_wave and vmax >= 120) else
                   "橙色" if (is_wave and vmax >= 6) or (not is_wave and vmax >= 80) else
                   "黄色" if (is_wave and vmax >= 4) or (not is_wave and vmax >= 50) else
                   "蓝色" if (is_wave and vmax >= 2.5) or (not is_wave and vmax >= 30) else "无")
            ctx.results["assess"] = {
                "status": "ok", "field_query": True,
                "level": "未达到预警阈值" if lvl == "无" else f"{lvl}预警",
                "risk": "区域内存在风险点" if lvl != "无" else "区域风险较低",
                "basis": (f"区域过程最大{'浪高' if is_wave else '增水'} {vmax}"
                          f"{'m' if is_wave else 'cm'}（{st.get('peak_lon')}°E,{st.get('peak_lat')}°N）"),
                "max_surge_cm": st.get("max_cm"), "max_hs_m": st.get("max_m"),
                "field_stats": st, "brief_data": bd,
            }
            return ctx

    if geo.get("status") != "ok" or not sites:
        # 无数据降级：骨架占位，保证链路不中断
        ctx.results["assess"] = {
            "status": "stub",
            "level": "橙色预警",
            "risk": "存在海水倒灌风险",
            "basis": "占位：无真实数据，使用骨架默认",
        }
        return ctx

    max_cm = geo.get("max_surge_cm", 0.0)
    is_point = bool(geo.get("custom_point"))
    # Ensemble 数据自带天文潮, max 为总水位；但任意采样点没有本站警戒潮位，
    # 只能按"风暴增水"分级判级，故此时不按总水位判。
    is_total_level = (src == "ensemble") and not is_point
    peak_site = geo.get("peak_site", "厦门港")
    peak_time = geo.get("peak_time", "")

    # ---- FTP 台风期间数据：优先用"总水位对照警戒潮位"（业务口径）----
    tt = geo.get("tide_total") or {}
    # ⭐ 融合产品的"总水位"也按同一口径参与判级（否则会出现
    #    "正文按增水分级说未达阈值、融合小节按总水位说蓝色警戒"两个级别并存）
    _fust = ((ctx.results.get("fusion") or {}).get("tide") or {})
    _fp = _fust.get("point") or {}
    if _fp.get("series_cm"):
        _pts = list(tt.get("points") or [])
        _surge_series = None
        for s in (geo.get("sites") or []):
            if s.get("series_cm"):
                _surge_series = list(s["series_cm"])
                break
        _pts.append({
            "name": _fust.get("name") or region,
            "lon": _fp.get("cell_lon"), "lat": _fp.get("cell_lat"),
            "series_total_cm": list(_fp["series_cm"]),
            "series_surge_cm": _surge_series,       # 人工智能方法 AI 增水（有就一起给）
            "series_tide_cm": None,
        })
        _st = None
        try:
            _st = datetime.datetime.strptime(
                str((_fust.get("field") or {}).get("times", [""])[0])[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            _st = None
        tt = {"start_dt": _st, "step_hours": 1.0, "points": _pts,
              "source_kind": "融合产品 · 总水位（天文潮+增水，基准：平均海平面）"}
        ctx.results["assess_total_from_fusion"] = True
    tt_map: Dict[str, Any] = {}
    for p in (tt.get("points") or []):
        tot = [v for v in (p.get("series_total_cm") or []) if v is not None]
        sur = [v for v in (p.get("series_surge_cm") or []) if v is not None]
        tid = [v for v in (p.get("series_tide_cm") or []) if v is not None]
        if not tot:
            continue
        k = int(np.argmax(tot))
        step = tt.get("step_hours", 1) or 1
        pk_dt = None
        if tt.get("start_dt"):
            try:
                pk_dt = tt["start_dt"] + datetime.timedelta(hours=k * step)
            except Exception:
                pk_dt = None
        tt_map[str(p.get("name", ""))] = {
            "total_max": round(max(tot), 1),
            "surge_max": round(max(sur), 1) if sur else None,
            "tide_max": round(max(tid), 1) if tid else None,
            "tide_min": round(min(tid), 1) if tid else None,
            "peak_dt": pk_dt,
            "warn": _find_warn(str(p.get("name", ""))),
        }

    # 有总水位 + 有该站警戒潮位 → 业务口径判级
    ftp_warn_sites = {k: v for k, v in tt_map.items() if v.get("warn")}
    if ftp_warn_sites:
        top = max(ftp_warn_sites.items(), key=lambda kv: kv[1]["total_max"])
        top_name, top_v = top
        level = judge_by_warn_level(top_v["total_max"], top_v["warn"])
        peak_site = top_name
        if top_v.get("peak_dt"):
            peak_time = top_v["peak_dt"].strftime("%m-%d %H:%M")
        max_cm = top_v["total_max"]
        if level == "无":
            basis = (f"过程最高总水位 {top_v['total_max']:.1f}cm（{top_name}），"
                     f"未达该站蓝色警戒潮位 {top_v['warn']['blue']}cm；"
                     f"最大风暴增水 {top_v.get('surge_max')}cm")
        else:
            basis = (f"过程最高总水位 {top_v['total_max']:.1f}cm（{top_name}），"
                     f"达到该站{level}警戒潮位（{top_v['warn']['color']}cm，85黄零基准）；"
                     f"最大风暴增水 {top_v.get('surge_max')}cm")
        is_total_level = True
    # 判级：Ensemble(总水位) 对照警戒潮位表；否则增水阈值
    elif is_total_level:
        # 总水位判级: 取全区最大站点的警戒潮位对照
        top_warn = _find_warn(peak_site)
        level = judge_by_warn_level(max_cm, top_warn) if top_warn else judge(max_cm)
        if level == "无":
            basis = f"过程最高水位 {max_cm:.1f}cm，未达{peak_site}蓝色警戒潮位"
        else:
            basis = f"过程最高水位 {max_cm:.1f}cm(位于{peak_site})，达到{peak_site}{level}警戒潮位"
    else:
        level = judge(max_cm)
        if level == "无":
            basis = f"过程最大增水 {max_cm:.1f}cm，未达蓝色阈值(30cm)"
        else:
            basis = f"过程最大增水 {max_cm:.1f}cm(位于{peak_site})，达到{level}预警阈值"
        if tt_map:
            t2 = max(tt_map.items(), key=lambda kv: kv[1]["total_max"])
            basis += f"；{t2[0]}最高总水位 {t2[1]['total_max']:.1f}cm（参照）"
        if is_point and geo.get("max_all_cm"):
            basis += f"；该点过程最高水位 {geo['max_all_cm']:.1f}cm（参照）"

    # 站点表（简报的潮位×警戒潮位对照表，用各站真实警戒潮位）
    stations = []
    for s in sites:
        cm = s.get("max_surge_cm", 0.0)          # 该站的**最大增水**(cm)
        sname = s.get("name", "")
        warn = _find_warn(sname)
        if is_point and not warn:
            warn = None
        tt_s = tt_map.get(sname) or {}
        total_cm = tt_s.get("total_max")         # 该站的**最高总水位**(cm)
        # 有总水位就用总水位对照警戒潮位判（业务口径）；否则按增水分级
        if total_cm is not None and warn:
            lv = judge_by_warn_level(total_cm, warn)
            judge_on = total_cm
        else:
            lv = judge_by_warn_level(cm, warn) if (is_total_level and warn) else judge(cm)
            judge_on = cm
        # 判级用的量到底是"增水"还是"高潮位/总水位"——必须标出来，
        # 否则会出现"22.8cm 标成高潮位、再和 373cm 警戒潮位比"的荒唐表（用户反馈第 1 条）
        _metric = "高潮位" if (total_cm is not None and warn) else "增水"
        pt = s.get("peak_time", "")
        pd = s.get("peak_date", "")
        if tt_s.get("peak_dt"):
            pt = tt_s["peak_dt"].strftime("%m-%d %H:%M")
            pd = tt_s["peak_dt"].strftime("%Y-%m-%d")
        # ⭐ 阈值列必须是**判级真正用的那套标准**：
        #   按增水分级判 → 写 30/50/80/120；按总水位对照警戒潮位判 → 才写警戒潮位四色值。
        if _metric == "增水":
            warn_text = "30/50/80/120(增水分级)"
        elif warn:
            warn_text = warn["color"] + "(蓝/黄/橙/红)"
        elif is_point:
            warn_text = "30/50/80/120(增水分级)"
        else:
            warn_text = "700(蓝)/720(黄)/740(橙)/760(红)"
        stations.append({
            "station": sname,
            "date": pd,
            "time": pt,
            "metric": _metric,
            "high_tide_cm": round(judge_on, 1),          # 用于判级的那个量
            "max_total_cm": round(total_cm, 1) if total_cm is not None else None,
            "max_surge_cm": round(cm, 1),
            "tide_range_cm": (round(tt_s["tide_max"] - tt_s["tide_min"], 1)
                              if tt_s.get("tide_max") is not None
                              and tt_s.get("tide_min") is not None else None),
            "warn": warn_text,
            "level": lv,
            "warn_blue": warn["blue"] if warn else None,
        })

    region = ctx.request.get("region", "未指定海域")
    tw = ctx.request.get("time_window", "")
    tw_text = ""  # 不再写"未来N天窗口"(避免误导); 实际范围由 data_range 标注

    # 任意采样点：补充点位/网格点/距离说明
    point_note = ""
    point_desc = ""
    if is_point:
        pname = geo.get("point_name") or region
        plo, pla = geo.get("point_lon"), geo.get("point_lat")
        slo, sla = geo.get("sample_lon"), geo.get("sample_lat")
        dist = geo.get("sample_dist_km")
        kind = geo.get("sample_kind", "")
        where = {"mesh": "风暴潮数值模式场（非结构网格）",
                 "grid": "风暴潮数值模式场（网格）",
                 "nearest_station": "本站站点数据"}.get(kind, "模式场")
        point_desc = f"{pname}（{plo}°E, {pla}°N）"
        if kind == "nearest_station":
            point_note = (
                f"注：该台风暂无覆盖该点的场数据，此处采用最近本站站点"
                f"「{geo.get('sample_station','')}」（距目标点约 {dist} km）的预报结果。"
            )
        else:
            point_note = (
                f"注：采样点为{pname}（{plo}°E, {pla}°N），"
                f"取自{where}最近有效格点（{slo}°E, {sla}°N，距目标点约 {dist} km）。"
            )

    # 摘要措辞：严格区分"最高总水位"与"最大风暴增水"，避免两个量混在一起
    max_surge_cm = geo.get("max_surge_cm", 0.0)
    if is_total_level:
        max_total_cm = max((s.get("max_total_cm") or 0) for s in stations) if stations else max_cm
        summary_txt = (
            f"受台风过程影响，{region}沿岸将出现最高约 {max_total_cm:.0f} 厘米的风暴潮总水位过程"
            f"（天文潮叠加风暴增水，最大风暴增水 {max_surge_cm:.0f} 厘米），"
            f"最高总水位出现在{peak_site}（{peak_time}），"
            f"预警级别为{_warn_level_text(level)}。"
        )
    else:
        summary_txt = (
            f"受台风过程影响，{region}将出现{max_cm:.0f}厘米左右的"
            f"风暴增水过程{tw_text}，"
            f"过程最大增水出现在{peak_site}（{peak_time}），"
            f"预警级别为{_warn_level_text(level)}。"
        )

    # ---- 数据完整性门槛（测试报告 P2 第 5 条）----
    #   站点总水位/天文潮/官方预警缺项时，**不允许**输出"不具备成灾条件""全区无风险"
    #   这种确定性结论——只能讲"当前模型（增水）未达预警阈值"，并说清缺口。
    have_total = bool(ftp_warn_sites)
    # ⭐ 融合产品给了"总水位"（天文潮+增水，基准平均海平面）→ 也算有总水位，
    #    否则会一边展示融合总水位、一边说"未取到总水位"（自相矛盾）
    _fus_tide = (ctx.results.get("fusion") or {}).get("tide") or {}
    if _fus_tide.get("point"):
        have_total = True
    try:
        from . import ai_daily as _ad
        _tide_date = str(_ad.latest_tide_date() or "")
    except Exception:
        _tide_date = ""
    _gaps = []
    if not have_total:
        _gaps.append("站点总水位（天文潮+增水）本期未取到 → 倒灌风险无法按业务口径判级")
    elif _fus_tide.get("point"):
        _gaps.append("总水位来自融合产品（基准：平均海平面），与本站警戒潮位（85黄零）"
                     "的口径一致性未做换算")
    if not _tide_date:
        _gaps.append("天文潮（潮位）产品未取到")
    _gaps.append("官方预警信号（红/橙/黄/蓝）不在本系统数据内，须以官方发布为准")
    data_completeness = {
        "total_water": bool(have_total),
        "tide_product_date": _tide_date,
        "official_warning": False,
        "gaps": _gaps,
        # 只有"总水位 + 该站警戒潮位"都在，才允许下"无风险"级结论
        "allow_none_risk_conclusion": bool(have_total),
        "required_wording": (
            "当前模型增水未达预警阈值；该结论只代表本系统模型结果，**不代表官方无风险**——"
            "站点总水位/天文潮/官方预警尚未补齐，是否停课、撤离等须以政府部门"
            "正式发布的预警和决定为准。"
            if not have_total else
            "站点总水位已按业务口径对照警戒潮位判级，结论依据较充分；"
            "但是否停课、撤离等仍属政府部门正式决定。"),
    }

    brief_data = {
        "template_type": "storm_surge_alert",
        "agency": "自然资源部厦门海洋预报台",
        "title": f"{region}风暴潮{_warn_level_text(level)}",
        "time": "（生成时刻）",
        "number": "",
        "signer": "",
        "basis": "《自然资源部厦门海洋中心海洋灾害应急执行预案（风暴潮、海浪、海啸）》",
        "summary": summary_txt,
        "data_range": _data_range_text(ctx, geo),
        "stations": stations,
        "notice": "请沿海各有关单位密切关注我台后续风暴潮预警报。",
        "tip": "预警提示：请沿海相关部门关闭危险区域的海滨浴场和休闲娱乐场所，加固薄弱危险区域的海堤等设施，做好防潮准备和应急措施。",
        "note": (
            "注：本简报预警级别判定标准——"
            + ("「风暴潮总水位对照该站警戒潮位表（蓝/黄/橙/红）」；" if is_total_level
               else "「风暴增水分级」（蓝色30cm/黄色50cm/橙色80cm/红色120cm）；")
            + ("该点为任意采样点，无本站四色警戒潮位，故按风暴增水分级判定。"
               if is_point else
               # 表里写的到底是"警戒潮位"还是"增水分级"，备注必须跟着一致
               ("表中增水阈值即风暴增水分级（30/50/80/120cm）。"
                if (stations and stations[0].get("metric") == "增水")
                else "表中警戒潮位为该站85黄零基准的四色警戒值。"))
            + ("总水位取自数值场（潮驱动与风+潮驱动相减得增水、相加即总水位），"
               "其基准面与警戒潮位的85黄零基准是否一致尚待核实，故判级结论具参照性。"
               if is_total_level and (geo.get("tide_total") or {}).get("points") else "")
            + ("**总水位取自融合产品**，基准为平均海平面；"
               "表中的风暴增水为人工智能方法的单点产品，两个量标准不同、不要混用。"
               if ctx.results.get("assess_total_from_fusion") else "")
            + "最终判级以厦门中心业务化运行结果为准。"
            + ("" if have_total else
               "本次未取到站点总水位（天文潮+增水）产品，结论只按风暴增水阈值分级，"
               "**不能据此判断“无风险”**；是否停课、撤离须以政府部门正式预警与决定为准。")
            + (f"\n{point_note}" if point_note else "")
            + _extra_note(geo, ctx)
        ),
        "targets": "市委办、市政府办、市防汛办",
        "contact": "陶小琴",
        "phone": "0592－2065005，18705925573",
        "fax": "0592—5905381",
        "website": "http://www.fjocean.com",
    }

    ctx.results["assess"] = {
        "status": "ok",
        "level": _warn_level_text(level),
        "risk": "存在海水倒灌风险" if level != "无" else "风险较低",
        "basis": basis,
        "max_surge_cm": max_cm,
        "peak_time": peak_time,
        "peak_site": peak_site,
        "custom_point": is_point,
        "point_desc": point_desc,
        "point_note": point_note,
        "brief_data": brief_data,
        # ⭐ 数据完整性（模型据此决定能不能说"无风险/不具备成灾条件"）
        "data_completeness": data_completeness,
    }

    # 海浪评估（若已统计）
    wave = ctx.results.get("wave_stats", {}) or {}
    want_wave = str(ctx.request.get("disaster", "") or "") == "wave"
    # ⭐ 若本轮挂了融合产品融合浪高 → **以融合为主口径**（与简报里的融合小节一致），
    #    否则会出现"正文按人工智能方法 AI 浪场说 3.6 m→蓝色预警、融合小节说 1.53 m→未达到"
    #    这种同一条回复里两套数打架（补充测试报告点出的判级不一致）。
    _fusw = (ctx.results.get("fusion") or {}).get("wave") or {}
    _fwp = _fusw.get("point") or {}
    if _fwp.get("max_m") is not None:
        wave = dict(wave)
        wave["status"] = "ok"
        wave["max_hs_m"] = _fwp.get("max_m")
        wave["peak_time"] = (f"{( _fwp.get('peak_time') or '')[5:16]} UTC"
                            if _fwp.get("peak_time") else wave.get("peak_time"))
        wave["source"] = ("融合产品· 有效波高 · "
                          f"起报 {(_fusw.get('field') or {}).get('issue')} · "
                          f"{'精细 0.0083°' if (_fusw.get('field') or {}).get('fine') else '全场 0.05°'} · "
                          f"格点 {_fwp.get('cell_lon')}°E/{_fwp.get('cell_lat')}°N"
                          f"（距 {_fwp.get('dist_km')} km）")
        wave["fusion"] = True
        ctx.results["wave_stats"] = wave
    if wave.get("status") == "ok":
        hs = wave.get("max_hs_m", 0) or 0
        # ⭐ 判级**一律按要写出来的那个数值重算**：有些取数路径（点名地点/沿海点采样）
        #    构造的 wave_stats 里没有 level 字段，旧写法默认成"无"，
        #    于是出现"4.7 米却判未达预警"这种自相矛盾（用户反馈第 3 条）。
        wl = judge_wave_level(hs) if hs else (wave.get("level") or "无")
        wtext = "未达到预警阈值" if wl == "无" else f"{wl}预警"
        w_region = geo.get("point_name") or region
        ctx.results["assess"]["wave"] = {
            "max_hs_m": wave.get("max_hs_m"),
            "level": wl,
            "peak_time": wave.get("peak_time"),
        }
        if want_wave:
            # 用户问的是海浪 —— 直接把简报切换为**海浪警报/消息**模板，
            # 不再拿风暴潮的标题和表格来搪塞
            lvl_word = "未达到预警级别" if wl == "无" else f"{wl}预警"
            wst = wave.get("station")            # FTP 浮标站号（若有）
            # 浮标站缺经纬度对照，不能把台湾浮标的浪高说成"崇武近岸"
            w_label = f"浮标站 {wst}" if wst else w_region
            brief_data["template_type"] = "wave_alert" if wl != "无" else "wave_message"
            brief_data["title"] = f"{w_region}海浪{'警报' if wl != '无' else '消息'}"
            brief_data["summary"] = (
                f"受台风过程影响，{w_label} 出现 {hs:.1f} 米左右的有效波高过程，"
                f"峰值时刻 {wave.get('peak_time') or '（未标注）'}，海浪预警级别为{lvl_word}。"
            )
            brief_data["segments"] = [{
                "region": w_label,
                "description": f"有效波高最大约 {hs:.1f} 米",
                "level": lvl_word,
            }]
            # 海浪简报不展示潮位×警戒潮位表
            brief_data["stations"] = []
            wsrc = str(wave.get("source") or wave.get("file") or "海浪场")
            note_lines = [
                f"注：本简报为海浪预报，判级标准为「有效波高分级」"
                f"（蓝色2.5m / 黄色4.0m / 橙色6.0m / 红色9.0m）；"
                f"浪高数据取自 {wsrc}。"
            ]
            if wst:
                note_lines.append(
                    f"浮标波浪数据共 {wave.get('n_stations', '?')} 个站，此处给出本台风期间"
                    f"浪高最大的站（{wst}）。**该批浮标站在文件中只有站号、没有经纬度**，"
                    f"无法与「{region}」直接对应，故请按站号理解该结论。"
                )
            note_lines.append("最终判级以厦门中心业务化运行结果为准。")
            brief_data["note"] = "".join(note_lines)
        else:
            brief_data["summary"] += (
                f"\n\n同时，受台风影响，{w_region}近岸海域将出现{hs:.1f}米的大浪过程，"
                f"海浪预警级别为{wtext}。"
            )
    elif want_wave:
        # 只要海浪、却没取到海浪数据 —— 如实说明，不要拿风暴潮充数
        brief_data["summary"] = (
            f"暂未取到 {region} 的海浪（有效波高）数据，无法给出海浪预报结论。"
            f"可尝试：换一个台风编号（数据完整的 10 个：1513、1521、1601、1614、1617、"
            f"1709、1808、2305、2311、2403），或换个海域，或改用风暴潮查询。"
        )
        brief_data["title"] = f"{region}海浪预报（无数据）"
        brief_data["stations"] = []
    return ctx
