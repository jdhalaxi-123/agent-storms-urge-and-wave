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

from typing import Any, Dict

from orchestrator.contract import ModuleContext

# 增水判级阈值 (cm)
LEVELS = [("红色", 120.0), ("橙色", 80.0), ("黄色", 50.0), ("蓝色", 30.0)]


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


def run(ctx: ModuleContext) -> ModuleContext:
    geo = ctx.results.get("geo_stats", {}) or {}
    sites = geo.get("sites", []) or []

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
    level = judge(max_cm)
    peak_site = geo.get("peak_site", "厦门港")
    peak_time = geo.get("peak_time", "")

    # 判级依据
    if level == "无":
        basis = f"过程最大增水 {max_cm:.1f}cm，未达蓝色阈值(30cm)"
    else:
        basis = f"过程最大增水 {max_cm:.1f}cm(位于{peak_site})，达到{level}预警阈值"

    # 站点表（简报的潮位×警戒潮位对照表）
    stations = []
    for s in sites:
        cm = s.get("max_surge_cm", 0.0)
        lv = judge(cm)
        pt = s.get("peak_time", "")
        pd = s.get("peak_date", "")
        stations.append({
            "station": s.get("name", ""),
            "date": pd,
            "time": pt,
            "high_tide_cm": round(cm, 1),
            "warn": "700(蓝)/720(黄)/740(橙)/760(红)",
            "level": lv,
        })

    region = ctx.request.get("region", "未指定海域")
    brief_data = {
        "template_type": "storm_surge_alert",
        "agency": "自然资源部厦门海洋预报台",
        "title": f"{region}风暴潮{_warn_level_text(level)}",
        "time": "（生成时刻）",
        "number": "",
        "signer": "",
        "basis": "《自然资源部厦门海洋中心海洋灾害应急执行预案（风暴潮、海浪、海啸）》",
        "summary": (
            f"受台风过程影响，{region}将出现{max_cm:.0f}厘米左右的风暴增水过程，"
            f"过程最大增水出现在{peak_site}（{peak_time}），预警级别为{_warn_level_text(level)}。"
        ),
        "stations": stations,
        "notice": "请沿海各有关单位密切关注我台后续风暴潮预警报。",
        "tip": "预警提示：请沿海相关部门关闭危险区域的海滨浴场和休闲娱乐场所，加固薄弱危险区域的海堤等设施，做好防潮准备和应急措施。",
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
        "brief_data": brief_data,
    }

    # 海浪评估（若已统计）
    wave = ctx.results.get("wave_stats", {}) or {}
    if wave.get("status") == "ok":
        wl = wave.get("level", "无")
        wtext = "未达到预警阈值" if wl == "无" else f"{wl}预警"
        brief_data["summary"] += (
            f"\n\n同时，受台风影响，厦门近岸海域将出现{wave.get('max_hs_m', 0):.1f}米的大浪过程，"
            f"海浪预警级别为{wtext}。"
        )
        ctx.results["assess"]["wave"] = {
            "max_hs_m": wave.get("max_hs_m"),
            "level": wl,
            "peak_time": wave.get("peak_time"),
        }
    return ctx
