"""编排引擎：两阶段调度 + 中间选优。

阶段一（分析）：meta → geo_stats → selector(选优) → assess
阶段二（呈现）：brief → visualize

这是编排层的核心：只负责「调用谁的、什么顺序、传什么数据」，
不实现任何业务算法（算法都在 modules/ 里）。
"""
from __future__ import annotations

from typing import Any, Dict

import modules  # 顶层业务模块包

from .contract import ModuleContext
from . import intent, router, memory, geo_domain


def run(request: str) -> Dict[str, Any]:
    """字符串入口：规则解析槽位后走完整链路。"""
    slots = intent.parse(request)
    return run_with_slots(slots, raw=request)


def run_with_slots(slots: Dict[str, Any], raw: str = "") -> Dict[str, Any]:
    """槽位入口：LLM 工具调用直接给结构化参数。"""
    # ⭐「EC 预报 / 欧洲中心 / ECMWF」不是地名：指的是 EC 起报的那版预报。
    #    统一按"全场"处理并标记取 EC 那张动图；否则会被当成不认识的地点，
    #    退化成任意点采样(point_grid)→被判成"局地"→官方动图整条被跳过。
    _raw_ec = str(raw or slots.get("raw", "") or "").lower()
    if ("ecmwf" in _raw_ec or "欧洲中心" in _raw_ec or "ec预报" in _raw_ec
            or "ec 预报" in _raw_ec or "ec的" in _raw_ec or "ec 的" in _raw_ec):
        slots["wave_source"] = "ec"
        _reg = str(slots.get("region") or "")
        if not geo_domain.locate(_reg)[0] and not geo_domain.region_box(_reg):
            slots["region"] = "全场"
            slots["field_query"] = True
            slots["field_box"] = [114.5, 127.5, 17.0, 29.5]
            slots["broad_region"] = "全场"
            slots.pop("point", None)
            slots.pop("point_name", None)

    # 覆盖范围校验：超出范围不展示任何数据，只返回文字说明
    region = slots.get("region", "")
    # ⭐ 海浪单点的**浮标站号**（C6W10 / 46694A …）不是地名，别当坐标解析后误判出界
    chk = ({"ok": True, "matched": region, "buoy_code": True}
           if geo_domain.is_buoy_code(region)
           else geo_domain.check_region(region, slots.get("lon"), slots.get("lat")))
    if chk.get("buoy_code"):
        slots["buoy_code"] = str(region).strip().upper()

    # ⭐⭐ 场所请求（"厦门沿海的海浪场""闽北沿海的增水分布"）：
    #     场**不是预先定好的**——只要用户点了一个能识别的地点并要"场/分布"，
    #     就以该地点为中心、东南西北各 0.8°（约 90 km）动态取一个框。
    _plot = str(slots.get("plot", "") or "").strip().lower()
    _field_plot = _plot in ("surge_field", "wave_field", "field", "distribution")

    # ⭐ 用户原话里明确要"动图"时打硬标记：
    #    LLM 有时把 plot 给成静态图（如 surge_station），"动图"两个字就丢了。
    _raw_text = str(raw or slots.get("raw", "") or "")
    if any(k in _raw_text.lower() for k in ("动图", "动画", "动效", "gif")):
        slots["want_anim"] = True
    if _field_plot and not slots.get("field_query"):
        box = geo_domain.region_box(region) or geo_domain.dynamic_box(region)
        if box:
            slots["field_query"] = True
            slots["field_box"] = [float(x) for x in box]
            slots["dynamic_box"] = geo_domain.region_box(region) is None
            _n, _c = geo_domain.locate(region)
            if _n and not geo_domain.region_box(region):
                slots["region"] = str(_n)

    if not chk.get("ok"):
        reason = chk.get("reason", "out_of_domain")
        # ⭐ 大范围区域：若有「场数据」能力，**不再追问**，改为直接出该区域的场分布
        if reason == "need_clarify":
            box = (geo_domain.region_box(region)
                   or (geo_domain.dynamic_box(region) if _field_plot else None))
            if box:
                slots["field_query"] = True
                slots["field_box"] = [float(x) for x in box]
                slots["dynamic_box"] = geo_domain.region_box(region) is None
                slots["broad_region"] = chk.get("matched") or region
                slots["region"] = str(chk.get("matched") or region)
                memory.append({"request": raw or slots.get("raw", ""), "slots": slots,
                               "field_query": chk.get("matched")})
                routes = router.resolve(slots)
                ctx = ModuleContext(request=slots, routes=routes)
                ctx = modules.meta.run(ctx)
                ctx = modules.geo_stats.run(ctx)
                if (ctx.results.get("geo_stats") or {}).get("field_stats"):
                    ctx = modules.assess.run(ctx)
                    ctx = modules.brief.run(ctx)
                    ctx = modules.visualize.run(ctx)
                    _w = ctx.results.get("daily_wind") or {}
                    return {
                        "reply": ctx.results.get("brief", {}).get("markdown", ""),
                        "images": ctx.results.get("visualize", {}).get("images", []),
                        "image_notes": ctx.results.get("image_notes") or {},
                        "docx_path": ctx.results.get("brief", {}).get("docx_path"),
                        "brief_template": ctx.results.get("brief", {}).get("template"),
                        "field_query": True,
                        "wind": ({"file": _w.get("file"), "date": _w.get("date"),
                                  "size_mb": _w.get("size_mb")} if _w else {}),
                        "meta": ctx.meta,
                    }
            # 场数据不可用 → 退回追问
        msg = chk.get("message", "")
        memory.append({
            "request": raw or slots.get("raw", ""),
            "slots": slots,
            reason: chk.get("matched"),
        })
        return {
            "reply": msg,
            "images": [],
            "docx_path": None,
            "brief_template": reason,
            "need_clarify": reason == "need_clarify",
            "out_of_domain": chk.get("matched") if reason == "out_of_domain" else None,
            "meta": {"status": reason, "matched": chk.get("matched")},
        }

    # ⭐ 任意点采样：命中具体地点/经纬度且不属于本站站点时，
    #    把坐标写入槽位，由 geo_stats 在模式场/网格上按点取序列
    coord = chk.get("coord")
    if coord and not chk.get("station"):
        try:
            lo, la = float(coord[0]), float(coord[1])
        except (TypeError, ValueError):
            lo = la = None  # type: ignore
        if lo is not None and la is not None:
            slots["point"] = [lo, la]
            matched = str(chk.get("matched") or "")
            if matched and not matched.startswith("("):
                slots["point_name"] = matched
            else:
                # 只给了坐标：标题用坐标表示
                slots["region"] = f"{lo:.2f}°E, {la:.2f}°N"
            slots["nearest_station"] = chk.get("nearest_station", "")

    # 场景路由：槽位 → 命中的模块实现标识
    routes = router.resolve(slots)

    # 组装上下文
    ctx = ModuleContext(request=slots, routes=routes)

    # 阶段一：分析
    ctx = modules.meta.run(ctx)        # ① 定位 NC
    ctx = modules.geo_stats.run(ctx)   # ② 提取 + 插值 + 统计

    # ⭐ 兜底：站点/场/序列一个都没取到 → 如实说明并请用户给明确位置，
    #    绝不能继续硬编一份"简报"（曾出现"未知海域风暴潮风险简报…橙色预警"这类假结论）
    _g = ctx.results.get("geo_stats") or {}
    if not (_g.get("sites") or _g.get("field_stats") or _g.get("series")):
        _r = str(slots.get("region") or "").strip()
        memory.append({"request": raw or slots.get("raw", ""), "slots": slots,
                       "status": "no_data"})
        return {
            "reply": (f"抱歉，没有取到「{_r or '该海域'}」的预报数据，暂时无法给出结论，"
                      "也就不出图和简报了。\n\n"
                      "请换一个更明确的位置再问一次，例如：\n"
                      "- 站点：厦门、崇武、晋江、东山东港\n"
                      "- 区域：闽南、闽东、台湾海峡，或直接说「全场」看整个覆盖范围\n"
                      "- 也可以直接给经纬度，如 118.5°E, 24.5°N\n\n"
                      f"**当前可查询的站点**：{geo_domain.SUPPORTED_STATIONS}\n"
                      f"**覆盖范围**：{geo_domain.DOMAIN_DESC}"),
            "images": [],
            "docx_path": None,
            "brief_template": "no_data",
            "meta": {"status": "no_data", "region": _r},
        }

    ctx = modules.selector.run(ctx)    # ★ 数值 vs 智能 选优
    ctx = modules.assess.run(ctx)      # ③ 国标判级

    # 阶段二：呈现
    ctx = modules.brief.run(ctx)       # ④ Markdown 简报
    ctx = modules.visualize.run(ctx)   # ⑤ 图片

    # 会话记忆落盘（防降智，硬性要求）
    memory.append({
        "request": raw or slots.get("raw", ""),
        "slots": slots,
        "assess": ctx.results.get("assess", {}),
        "brief": ctx.results.get("brief", {}),
    })

    # 汇总返回
    wind = ctx.results.get("daily_wind") or {}
    return {
        "reply": ctx.results.get("brief", {}).get("markdown", ""),
        "images": ctx.results.get("visualize", {}).get("images", []),
        # ⭐ 每张图的准确说明（模型必须照这个说，不能把场图/场动图说成"某站的图"）
        "image_notes": ctx.results.get("image_notes") or {},
        "docx_path": ctx.results.get("brief", {}).get("docx_path"),
        "brief_template": ctx.results.get("brief", {}).get("template"),
        # 每日风场（任务三）有独立的更新节奏，单独告知，别和风暴潮预报的时效混在一起说
        "wind": ({"file": wind.get("file"), "date": wind.get("date"),
                  "size_mb": wind.get("size_mb")} if wind else {}),
        "meta": ctx.meta,
        # ⭐ 出图失败的原因（供对话里如实告知用户；没有失败则为 None）
        "plot_error": ctx.results.get("visualize_error") or None,
    }
