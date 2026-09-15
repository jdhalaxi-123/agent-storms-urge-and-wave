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
# 厦门站名带"厦门港"等别名
STATION_NAME_MAP = {
    "厦门": "厦门", "厦门港": "厦门", "厦门(XMN)": "厦门",
    "东山东港": "东山", "东山东港(DSN)": "东山",
    "崇武": "崇武", "崇武(CWU)": "崇武",
    "晋江": "晋江", "晋江(JNJ)": "晋江",
}


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
    """按站名(含别名)找警戒潮位表。"""
    key = STATION_NAME_MAP.get(station_name, station_name)
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


def _extra_note(geo: Dict[str, Any]) -> str:
    """附加上数据来源与实测对比信息（FTP 台风期间数据）。"""
    parts = []
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


def run(ctx: ModuleContext) -> ModuleContext:
    geo = ctx.results.get("geo_stats", {}) or {}
    sites = geo.get("sites", []) or []
    src = geo.get("source", "")

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
        key = STATION_NAME_MAP.get(sname, sname)
        warn = STATION_WARN_LEVELS.get(key) or STATION_WARN_LEVELS.get(sname)
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
        pt = s.get("peak_time", "")
        pd = s.get("peak_date", "")
        if tt_s.get("peak_dt"):
            pt = tt_s["peak_dt"].strftime("%m-%d %H:%M")
            pd = tt_s["peak_dt"].strftime("%Y-%m-%d")
        if warn:
            warn_text = warn["color"] + "(蓝/黄/橙/红)"
        elif is_point:
            warn_text = "30/50/80/120(增水分级)"
        else:
            warn_text = "700(蓝)/720(黄)/740(橙)/760(红)"
        stations.append({
            "station": sname,
            "date": pd,
            "time": pt,
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
               "表中警戒潮位为该站85黄零基准的四色警戒值。")
            + ("总水位取自数值场（潮驱动与风+潮驱动相减得增水、相加即总水位），"
               "其基准面与警戒潮位的85黄零基准是否一致尚待核实，故判级结论具参照性。"
               if is_total_level and (geo.get("tide_total") or {}).get("points") else "")
            + "最终判级以厦门中心业务化运行结果为准。"
            + (f"\n{point_note}" if point_note else "")
            + _extra_note(geo)
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
    }

    # 海浪评估（若已统计）
    wave = ctx.results.get("wave_stats", {}) or {}
    if wave.get("status") == "ok":
        wl = wave.get("level", "无")
        wtext = "未达到预警阈值" if wl == "无" else f"{wl}预警"
        w_region = geo.get("point_name") or region
        brief_data["summary"] += (
            f"\n\n同时，受台风影响，{w_region}近岸海域将出现{wave.get('max_hs_m', 0):.1f}米的大浪过程，"
            f"海浪预警级别为{wtext}。"
        )
        ctx.results["assess"]["wave"] = {
            "max_hs_m": wave.get("max_hs_m"),
            "level": wl,
            "peak_time": wave.get("peak_time"),
        }
    return ctx
