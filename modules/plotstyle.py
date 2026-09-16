# -*- coding: utf-8 -*-
"""画图风格：对齐课题三投产图的样式（cartopy + jet 配色 + 固定色标 + 等级线）。

他们的约定（已从源码核实）
--------------------------
- 地图：cartopy `PlateCarree` + Natural Earth 陆地（灰 `0.75`）+ 海岸线 + 经纬网
- 配色：主力 `jet`；风速固定 **0~25 m/s**，浪高固定 **0~8 m**
- 风级等值线：7 级 **13.9 m/s**（红虚）、10 级 **24.5 m/s**（黑实），带 `clabel`
- 海况等级线：0.1/0.5/1.25/2.5/4.0/6.0/9.0/14.0 m → 小浪…怒涛（标签写中文）
- 保存：`dpi=150`、`bbox_inches='tight'`；点线命名带站点与起止日期
- 字体：`Microsoft YaHei` / `SimHei` + `axes.unicode_minus=False`

离线可用
--------
Natural Earth 数据预置在 `<项目>/assets/cartopy/shapefiles/`，
本模块把 cartopy 的 `data_dir` 与 `pre_existing_data_dir` 都指到那里，
部署到别的机器不需要联网。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CARTOPY_DIR = PROJECT_ROOT / "assets" / "cartopy"

# 风速阈值（课题三硬编码，与 quickWind / 投产 GIF 一致）
WIND_7 = 13.9
WIND_10 = 24.5
# 海况等级（浪高 m → 中文名）
SEA_STATE = [(0.1, "小浪"), (0.5, "轻浪"), (1.25, "中浪"), (2.5, "大浪"),
             (4.0, "巨浪"), (6.0, "狂浪"), (9.0, "狂涛"), (14.0, "怒涛")]

_cfg_done = False


def setup() -> None:
    """中文字体 + cartopy 数据目录（幂等）。"""
    global _cfg_done
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun",
                                       "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["font.size"] = 10
    plt.rcParams["axes.titlesize"] = 12
    plt.rcParams["figure.dpi"] = 100

    if _cfg_done:
        return
    try:
        import cartopy
        CARTOPY_DIR.mkdir(parents=True, exist_ok=True)
        cartopy.config["data_dir"] = str(CARTOPY_DIR)
        cartopy.config["pre_existing_data_dir"] = str(CARTOPY_DIR)
    except Exception:
        pass
    _cfg_done = True


# --------------------------------------------------------------------------- #
# 地图底图
# --------------------------------------------------------------------------- #
def map_axes(fig, rect, extent: Sequence[float], *, grid: bool = True,
             land: bool = True):
    """建一个 PlateCarree 地图轴：陆地灰、海岸线、经纬网。

    陆地/海岸线 zorder 取高值（6/7），保证压在填色、风矢、等值线之上——
    与课题三投产图一致（数据不盖陆地）。
    """
    setup()
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

    ax = fig.add_axes(rect, projection=ccrs.PlateCarree())
    ax.set_extent(list(extent), crs=ccrs.PlateCarree())
    if land:
        try:
            ax.add_feature(cfeature.NaturalEarthFeature(
                "physical", "land", "10m", edgecolor="face", facecolor="0.78"),
                zorder=6)
        except Exception:
            ax.add_feature(cfeature.LAND.with_scale("50m"), facecolor="0.78",
                           zorder=6)
    try:
        ax.coastlines("10m", linewidth=0.6, zorder=7)
    except Exception:
        try:
            ax.coastlines("50m", linewidth=0.6, zorder=7)
        except Exception:
            pass
    if grid:
        try:
            gl = ax.gridlines(draw_labels=True, linewidth=0.3, color="0.55",
                              alpha=0.7, x_inline=False, y_inline=False)
            gl.top_labels = False
            gl.right_labels = False
            gl.xformatter = LONGITUDE_FORMATTER
            gl.yformatter = LATITUDE_FORMATTER
            gl.xlabel_style = {"size": 9}
            gl.ylabel_style = {"size": 9}
        except Exception:
            pass
    return ax


# --------------------------------------------------------------------------- #
# 等级线
# --------------------------------------------------------------------------- #
def add_wind_levels(ax, lon2, lat2, spd, *, transform=None, label: bool = True):
    """7 级（13.9）红虚线、10 级（24.5）黑实线；不存在该等级时不画。"""
    setup()
    import numpy as np
    import cartopy.crs as ccrs
    tr = transform if transform is not None else ccrs.PlateCarree()
    out = []
    try:
        vmax = float(np.nanmax(spd))
    except Exception:
        return out
    for thr, color, ls, lw, txt in ((WIND_7, "red", "dashed", 1.6, "7级"),
                                    (WIND_10, "black", "solid", 2.0, "10级")):
        if vmax < thr:
            continue
        try:
            cs = ax.contour(lon2, lat2, spd, levels=[thr], colors=color,
                            linestyles=ls, linewidths=lw, transform=tr, zorder=5)
            if label:
                try:
                    ax.clabel(cs, inline=True, fontsize=9,
                              fmt={thr: f"{thr} m/s {txt}"})
                except Exception:
                    pass
            out.append(cs)
        except Exception:
            pass
    return out


def add_sea_state(ax, lon2, lat2, hs, *, transform=None, vmax_show: float = 14.0):
    """海况等级等值线（小浪…怒涛），标签直接写中文名。"""
    setup()
    import numpy as np
    import cartopy.crs as ccrs
    tr = transform if transform is not None else ccrs.PlateCarree()
    try:
        top = float(np.nanmax(hs))
    except Exception:
        return None
    levels = [lv for lv, _ in SEA_STATE if lv <= max(top, 0.11) and lv <= vmax_show + 0.01]
    if not levels:
        return None
    fmt = {lv: name for lv, name in SEA_STATE}
    try:
        cs = ax.contour(lon2, lat2, hs, levels=levels, colors="k",
                        linewidths=0.8, alpha=0.75, transform=tr, zorder=5)
        try:
            ax.clabel(cs, inline=True, fontsize=8, fmt=fmt)
        except Exception:
            pass
        return cs
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 色标 / 保存 / 动图
# --------------------------------------------------------------------------- #
def add_colorbar(fig, ax, mappable, label: str, ticks: Optional[Sequence[float]] = None,
                 *, shrink: float = 0.8, pad: float = 0.03, label_size: int = 12):
    setup()
    cb = fig.colorbar(mappable, ax=ax, orientation="vertical", shrink=shrink,
                      pad=pad, ticks=ticks)
    cb.set_label(label, fontsize=label_size)
    cb.ax.tick_params(labelsize=10)
    return cb


def save(fig, path, dpi: int = 150) -> str:
    setup()
    import matplotlib.pyplot as plt
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return str(p)


def make_gif(frames: List[Any], path, duration: float = 0.4, loop: int = 0) -> Optional[str]:
    """frames 为 PIL.Image 列表或 numpy 数组列表 → 存 GIF。"""
    setup()
    try:
        from PIL import Image
        imgs = []
        for f in frames:
            if isinstance(f, Image.Image):
                imgs.append(f.convert("P", palette=Image.ADAPTIVE))
            else:
                import numpy as np
                a = np.asarray(f)
                if a.dtype != "uint8":
                    a = np.clip(a, 0, 255).astype("uint8")
                imgs.append(Image.fromarray(a).convert("P", palette=Image.ADAPTIVE))
        if not imgs:
            return None
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        imgs[0].save(p, save_all=True, append_images=imgs[1:],
                     duration=int(duration * 1000), loop=loop, optimize=True)
        return str(p)
    except Exception:
        return None


def nice_vmax(v: float, step: float = 10.0) -> float:
    """把最大值取整到好看的刻度上（用于固定色标）。"""
    import math
    if v <= 0:
        return step
    return float(math.ceil(v / step) * step)
