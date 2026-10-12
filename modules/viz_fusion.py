# -*- coding: utf-8 -*-
"""融合产品的出图。

两类图、两种形态：
    tide（总水位）→ ① 站点/任意点过程曲线（叠四色警戒潮位）
                     ② 过程最高总水位空间分布（全场 0.05°，叠各站警戒潮位参考）
    wave（有效波高）→ ① 站点/任意点过程曲线（叠海浪分级线）
                      ② 过程最大有效波高空间分布（精细 0.0083° 或全场 0.05°）

图上固定写清：来源（融合产品融合）、起报、时段、基准（平均海平面）、时间（UTC + 北京时）、取值格点。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

# 与 assess 里的四色警戒潮位/海浪分级保持一致
WAVE_LEVELS = [(2.5, "蓝色"), (4.0, "黄色"), (6.0, "橙色"), (9.0, "红色")]


def _warn(station: str) -> Dict[str, Any]:
    try:
        from . import assess
        return assess._find_warn(station) or {}
    except Exception:
        return {}


def _head(fld: Dict[str, Any], kind_cn: str, extra: str = "") -> str:
    grid = "精细 0.0083°" if fld.get("fine") else "全场 0.05°"
    src = (f"台风个例 {fld.get('typhoon')}" if fld.get("typhoon")
           else f"起报 {fld.get('issue')}")
    t0 = str(fld.get("times", [""])[0])[:16].replace("T", " ")
    t1 = str(fld.get("times", [""])[-1])[:16].replace("T", " ")
    return (f"融合产品· {kind_cn} · {src} · {grid}\n"
            f"{t0} ~ {t1} UTC（北京时 +8）　基准：平均海平面　{extra}")


# --------------------------------------------------------------------------- #
# 过程曲线
# --------------------------------------------------------------------------- #
def curve(out_dir: Path, ctx: Any, tag: str, kind: str) -> Tuple[List[str], str]:
    """站点/任意点过程曲线。返回 (图片列表, 说明文本)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from . import plotstyle
    plotstyle.setup()
    _setup_cn()

    fus = (ctx.results.get("fusion") or {}).get(kind) or {}
    fld = fus.get("field") or {}
    d = fus.get("point") or {}
    if not fld or not d or not d.get("series_cm") and not d.get("series_m"):
        return [], ""

    is_tide = (kind == "tide")
    ser = d["series_cm"] if is_tide else [None if v is None else v for v in d["series_m"]]
    y = np.asarray([np.nan if v is None else float(v) for v in ser], dtype=float)
    if not np.isfinite(y).any():
        return [], ""
    x = np.arange(y.size)
    name = fus.get("name") or ctx.request.get("region") or "目标点"
    unit = "cm" if is_tide else "m"

    fig, ax = plt.subplots(figsize=(9.6, 4.4), dpi=110)
    ax.plot(x, y, lw=1.8, color="#c0392b" if is_tide else "#1f77b4",
            label=f"融合{'总水位' if is_tide else '有效波高'}")
    k = int(np.nanargmax(y))
    ax.plot([k], [y[k]], "o", ms=5, color="#c0392b" if is_tide else "#1f77b4")
    ax.annotate(f"峰值 {y[k]:.1f} {unit}\n{_tlab(fld, k)}", (k, y[k]),
                textcoords="offset points", xytext=(8, -18), fontsize=9)

    if is_tide:
        w = _warn(name)
        if w:
            for key, lab, col in (("blue", "蓝色警戒", "#2f80ed"), ("yellow", "黄色警戒", "#f2c200"),
                                  ("orange", "橙色警戒", "#f2994a"), ("red", "红色警戒", "#eb5757")):
                if w.get(key):
                    ax.axhline(float(w[key]), ls="--", lw=0.9, color=col, alpha=0.85)
                    ax.text(0.004, float(w[key]), f"{lab} {w[key]}cm", va="bottom", ha="left",
                            fontsize=7.5, color=col, transform=ax.get_yaxis_transform())
            _lvl = _judge_tide(float(np.nanmax(y)), w)
            extra = f"峰值对照该站警戒潮位：**{_lvl}**"
        else:
            extra = "（该点无本站警戒潮位，未判级）"
    else:
        for th, lab in WAVE_LEVELS:
            ax.axhline(th, ls="--", lw=0.9, alpha=0.7)
            ax.text(0.004, th, f"{lab} {th}m", va="bottom", ha="left", fontsize=7.5,
                    alpha=0.8, transform=ax.get_yaxis_transform())
        _lvl = _judge_wave(float(np.nanmax(y)))
        extra = f"峰值对照海浪分级：**{_lvl}**"

    ax.set_title(_head(fld, "风暴潮总水位" if is_tide else "有效波高", extra), fontsize=10)
    ax.set_xlabel(f"时次（{_tlab(fld, 0)} 起，逐时）", fontsize=9)
    ax.set_ylabel(("总水位 (cm，基准：平均海平面)" if is_tide else "有效波高 (m)"), fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.3)
    _note_xticks(ax, fld, y.size)
    fig.tight_layout(pad=1.2)
    fp = out_dir / f"fusion_{kind}_curve_{tag}.png"
    fig.savefig(fp, bbox_inches="tight")
    plt.close(fig)

    note = (f"融合产品 · {name} {'总水位' if is_tide else '有效波高'}过程曲线"
            f"（起报 {fld.get('issue')}，{'精细 0.0083°' if fld.get('fine') else '全场 0.05°'}）；"
            f"取值格点 {d.get('cell_lon')}°E/{d.get('cell_lat')}°N（距 {d.get('dist_km')} km）；"
            f"峰值 {d.get('max_m')} m @ {_tlab(fld, k)}；{extra}。"
            "基准：平均海平面（提供方口径）；时间：UTC（括号内北京时）。")
    return [str(fp)], note


# --------------------------------------------------------------------------- #
# 空间分布（过程最高/最大）
# --------------------------------------------------------------------------- #
def field(out_dir: Path, ctx: Any, tag: str, kind: str) -> Tuple[List[str], str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    from . import plotstyle
    plotstyle.setup()
    _setup_cn()

    fus = (ctx.results.get("fusion") or {}).get(kind) or {}
    fld = fus.get("field") or {}
    if not fld:
        return [], ""
    arr = np.asarray(fld["values"], dtype=float)
    la = np.asarray(fld["lat"], dtype=float)
    lo = np.asarray(fld["lon"], dtype=float)
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mx = np.nanmax(arr, axis=0)                      # 过程最高
    if kind == "tide":
        mx = mx * 100.0                                  # → cm
    LON, LAT = np.meshgrid(lo, la)

    box = (ctx.results.get("geo_stats") or {}).get("field_box") or ctx.request.get("field_box")
    extent = [float(lo.min()), float(lo.max()), float(la.min()), float(la.max())]
    if isinstance(box, (list, tuple)) and len(box) == 4:
        extent = [max(extent[0], float(box[0])), min(extent[1], float(box[1])),
                  max(extent[2], float(box[2])), min(extent[3], float(box[3]))]
    if extent[1] - extent[0] < 0.4 or extent[3] - extent[2] < 0.4:
        extent = [float(lo.min()), float(lo.max()), float(la.min()), float(la.max())]

    is_tide = (kind == "tide")
    vmax = float(np.nanmax(mx[np.isfinite(mx)])) if np.isfinite(mx).any() else 1.0
    if is_tide:
        vmin, vmax_c = 0.0, max(100.0, np.ceil(vmax / 50.0) * 50.0)
        label = "过程最高总水位 (cm，基准：平均海平面)"
        cmap, ticks = "jet", None
    else:
        vmin, vmax_c = 0.0, max(4.0, np.ceil(vmax * 2) / 2)
        label = "过程最大有效波高 (m)"
        cmap, ticks = "jet", None

    fig = plt.figure(figsize=(10.6, 7.6))
    ax = plotstyle.map_axes(fig, [0.05, 0.06, 0.79, 0.85], extent)
    pc = ax.pcolormesh(LON, LAT, mx, cmap=cmap, vmin=vmin, vmax=vmax_c,
                       shading="auto", zorder=2, transform=ccrs.PlateCarree())
    plotstyle.add_colorbar(fig, ax, pc, label, ticks, shrink=0.85, pad=0.02)
    if is_tide:
        # 叠各站四色警戒潮位参考（用站点坐标标点 + 文字）
        from orchestrator import geo_domain as _gd
        for cn, (x, y) in _gd.SESSION_STATION_COORD.items():
            w = _warn(cn)
            if not w:
                continue
            ax.plot(x, y, "k^", ms=5, transform=ccrs.PlateCarree(), zorder=5)
            ax.text(x + 0.06, y, f"{cn} 蓝{w.get('blue')}/红{w.get('red')}", fontsize=7,
                    transform=ccrs.PlateCarree(), zorder=5)
    else:
        # 海浪：叠分级参考（粗线 4.0/6.0 m）
        for th, lab in ((4.0, "黄 4.0m"), (6.0, "橙 6.0m")):
            if th < vmax_c:
                ax.contour(LON, LAT, mx, levels=[th], colors="k", linewidths=1.0,
                           transform=ccrs.PlateCarree(), zorder=4)
    ax.set_title(_head(fld, "风暴潮总水位" if is_tide else "有效波高",
                       f"过程最高 {vmax:.1f} {'cm' if is_tide else 'm'}"), fontsize=10)
    fp = out_dir / f"fusion_{kind}_field_{tag}.png"
    fig.savefig(fp, bbox_inches="tight", dpi=150)
    plt.close(fig)

    note = (f"融合产品 · {'过程最高总水位' if is_tide else '过程最大有效波高'}空间分布"
            f"（起报 {fld.get('issue')}，{'精细 0.0083°' if fld.get('fine') else '全场 0.05°'}，"
            f"共 {int(np.isfinite(mx).sum())} 个有效格点）；"
            f"全场最高 {vmax:.1f} {'cm' if is_tide else 'm'}。"
            "基准：平均海平面（提供方口径）；时间：UTC。")
    return [str(fp)], note


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _setup_cn() -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for fam in ("Microsoft YaHei", "SimHei"):
            if any(f.name == fam for f in font_manager.fontManager.ttflist):
                plt.rcParams["font.sans-serif"] = [fam]
                plt.rcParams["axes.unicode_minus"] = False
                return
    except Exception:
        pass


def _tlab(fld: Dict[str, Any], k: int) -> str:
    try:
        from . import fusion as F
        t = fld["times"][k]
        return F.time_label(t)
    except Exception:
        return ""


def _note_xticks(ax, fld: Dict[str, Any], n: int) -> None:
    """横轴标几个"MM-DD HH（北京时 HH）"，避免只有序号看不懂。"""
    try:
        from . import fusion as F
        step = max(1, n // 8)
        idx = list(range(0, n, step))
        labs = []
        for i in idx:
            t = F.fmt(fld["times"][i])
            b = F.to_bjt(fld["times"][i])
            labs.append(f"{t[5:]}\n({b[11:]})")
        ax.set_xticks(idx)
        ax.set_xticklabels(labs, fontsize=7.5)
    except Exception:
        pass


def _judge_tide(max_cm: float, warn: Dict[str, Any]) -> str:
    try:
        from . import assess
        lv = assess.judge_by_warn_level(max_cm, warn)
        return "未达到预警阈值" if lv == "无" else f"{lv}警戒"
    except Exception:
        return "—"


def _judge_wave(max_m: float) -> str:
    try:
        from . import assess
        lv = assess.judge_wave_level(max_m)
        return "未达到预警级别" if lv == "无" else f"{lv}预警"
    except Exception:
        return "—"
