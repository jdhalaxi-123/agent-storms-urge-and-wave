# -*- coding: utf-8 -*-
"""扩展图型：对齐课题三投产图的三种出图。

1. `draw_wind_wave_pair`  风+浪双联图（左风速+风矢+风级线，右有效波高+海况线）
2. `draw_wind_wave_gif`   风+浪动图（逐帧渲染 → PIL 存 GIF，不依赖 imagemagick）
3. `draw_validation_density` 预报 vs 实测 密度散点（viridis + LogNorm + RMSE/Bias/R）

所有函数都"拿不到数据就返回空字符串/None"，不影响文字回答。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import plotstyle


# --------------------------------------------------------------------------- #
# 工具：从 ctx 里取当天的风场与浪场
# --------------------------------------------------------------------------- #
def _newest_cached(subdir: str, pattern: str) -> Optional[Path]:
    """在数据仓里找最新的本地缓存文件（按日期目录名排序）。"""
    try:
        from orchestrator import paths
        root = paths.CACHE_DIR / "daily"
        if not root.exists():
            return None
        best = None
        for p in root.glob(f"*/{subdir}/{pattern}"):
            if best is None or p.parent.parent.name > best.parent.parent.name:
                best = p
        return best
    except Exception:
        return None


def _daily_wind(ctx) -> Optional[Dict[str, Any]]:
    """优先用本次请求已取到的风场；否则用本地最新缓存；再退回 FTP。"""
    w = (ctx.results or {}).get("daily_wind") or {}
    if w.get("path"):
        return w
    p = _newest_cached("wind", "atm_forecast_*.nc")
    if p is not None:
        return {"path": str(p), "file": p.name, "date": p.parent.parent.name,
                "size_mb": round(p.stat().st_size / 1e6, 1)}
    try:
        from . import ai_daily
        return ai_daily.load_wind("")
    except Exception:
        return None


def _daily_wave(ctx, date: str = "") -> Optional[Dict[str, Any]]:
    """海浪场：请求里的 ai_field → 本地最新缓存 → FTP。"""
    fld = ((ctx.results or {}).get("ai_field") or {})
    if fld.get("kind") == "wave" and fld.get("field"):
        return fld["field"]
    p = _newest_cached("wave_field", "*_wave_forecast_1h.nc")
    if p is not None:
        try:
            import datetime as _dt
            import xarray as xr
            ds = xr.open_dataset(p, decode_times=False)
            try:
                lat = np.asarray(ds["latitude"].values, dtype=float)
                lon = np.asarray(ds["longitude"].values, dtype=float)
                hs = np.asarray(ds["hs_torch"].values, dtype=float)
                mk = np.asarray(ds["mask"].values) if "mask" in ds.variables else None
            finally:
                ds.close()
            if mk is not None and mk.shape == hs.shape[-2:]:
                hs = np.where(mk[None, :, :] > 0, hs, np.nan) if hs.ndim == 3 else \
                    np.where(mk > 0, hs, np.nan)
            d = p.name[:8]
            return {"lat": lat, "lon": lon, "hs_m": hs, "mask": mk,
                    "n_times": int(hs.shape[0]),
                    "date": d, "start_dt": _dt.datetime.strptime(d, "%Y%m%d"),
                    "file": p.name, "path": str(p)}
        except Exception:
            pass
    try:
        from . import ai_daily
        return ai_daily.load_wave_field(date or "")
    except Exception:
        return None


def _load_wind_arrays(path: str, box: Tuple[float, float, float, float]):
    """读每日风场（兼容 ROMS 辅助坐标），返回 lon/lat/u/v/time。"""
    import xarray as xr

    ds = xr.open_dataset(path, decode_times=True)
    try:
        latn = "latitude" if "latitude" in ds else ("lat" if "lat" in ds else None)
        lonn = "longitude" if "longitude" in ds else ("lon" if "lon" in ds else None)
        un = next((v for v in ("u10", "u10m", "uwnd") if v in ds.variables), None)
        vn = next((v for v in ("v10", "v10m", "vwnd") if v in ds.variables), None)
        if not (latn and lonn and un and vn):
            return None
        la = np.asarray(ds[latn].values).ravel()
        lo = np.asarray(ds[lonn].values).ravel()
        j = np.where((la >= box[2]) & (la <= box[3]))[0]
        i = np.where((lo >= box[0]) & (lo <= box[1]))[0]
        if j.size < 2 or i.size < 2:
            return None
        if latn in ds.dims and lonn in ds.dims:
            sub = ds.sel({lonn: slice(box[0], box[1]), latn: slice(box[2], box[3])})
        else:
            sub = ds.isel({ds[latn].dims[0]: slice(int(j[0]), int(j[-1]) + 1),
                           ds[lonn].dims[0]: slice(int(i[0]), int(i[-1]) + 1)})
        lon = np.asarray(sub[lonn].values).ravel()
        lat = np.asarray(sub[latn].values).ravel()
        u = np.asarray(sub[un].values, dtype=float)
        v = np.asarray(sub[vn].values, dtype=float)
        tv = None
        for tname in ("time", "valid_time"):
            if tname in sub.variables:
                tv = np.asarray(sub[tname].values).ravel()
                break
        return {"lon": lon, "lat": lat, "u": u, "v": v, "time": tv}
    finally:
        try:
            ds.close()
        except Exception:
            pass


def _peak_index(spd: np.ndarray) -> int:
    """逐时刻最大值序列的峰值索引（spd 形状 (t, lat, lon)）。"""
    if spd.ndim == 3:
        series = np.nanmax(spd, axis=(1, 2))
        return int(np.nanargmax(series))
    return 0


# --------------------------------------------------------------------------- #
# ① 风 + 浪 双联图
# --------------------------------------------------------------------------- #
def draw_wind_wave_pair(OUT_DIR: Path, ctx, tag: str) -> List[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    plotstyle.setup()

    box = ctx.request.get("field_box")
    box = tuple(float(x) for x in box) if (box and len(box) == 4) else (114.0, 128.0, 17.0, 30.0)

    wind = _daily_wind(ctx)
    wave = _daily_wave(ctx)
    wa = _load_wind_arrays(wind["path"], box) if wind else None
    if not wa:
        return []

    hs = np.asarray(wave["hs_m"], dtype=float) if wave else None
    wlon = np.asarray(wave["lon"]) if wave else None
    wlat = np.asarray(wave["lat"]) if wave else None
    wtime = wave.get("times") if wave else None
    wmask = (wave or {}).get("mask")
    # 陆地掩膜：浪场在陆地上也有值，出图前套上（否则浪会爬到陆地上）
    if hs is not None and wmask is not None:
        try:
            m = np.asarray(wmask)
            if m.shape == hs.shape[-2:]:
                hs = np.where(m[None, :, :] > 0, hs, np.nan) if hs.ndim == 3 else \
                    np.where(m > 0, hs, np.nan)
        except Exception:
            pass

    # 风：取区域峰值时刻；浪：取区域峰值时刻
    spd = np.sqrt(wa["u"] ** 2 + wa["v"] ** 2)
    kw = _peak_index(spd)
    uw, vw, sw = wa["u"][kw], wa["v"][kw], spd[kw]
    t_wind = str(wa["time"][kw])[:16].replace("T", " ") if wa["time"] is not None else ""

    kh = None
    t_wave = ""
    if hs is not None and hs.ndim == 3:
        gx, gy = np.meshgrid(wlon, wlat)
        m = ((gx >= box[0]) & (gx <= box[1]) & (gy >= box[2]) & (gy <= box[3]))
        sub = np.where(m[None, :, :], hs, np.nan)
        kh = _peak_index(sub)
        hs_k = sub[kh]
    else:
        hs_k = None
    if kh is not None:
        wtime = wave.get("times")
        if wtime is not None and len(wtime) > kh:
            t_wave = str(wtime[kh])[:16].replace("T", " ")
        elif wave.get("start_dt") is not None:
            import datetime as _dt
            t_wave = (wave["start_dt"] + _dt.timedelta(hours=int(kh))).strftime("%Y-%m-%d %H:%M")

    fig = plt.figure(figsize=(20, 8))
    extent = [box[0], box[1], box[2], box[3]]

    ax1 = plotstyle.map_axes(fig, [0.04, 0.07, 0.42, 0.80], extent)
    LON, LAT = np.meshgrid(wa["lon"], wa["lat"])
    pc1 = ax1.pcolormesh(LON, LAT, sw, cmap="jet", vmin=0, vmax=25, shading="auto",
                         zorder=2, transform=ccrs.PlateCarree())
    plotstyle.add_colorbar(fig, ax1, pc1, "风速 (m/s)", [0, 5, 10, 15, 20, 25],
                           shrink=0.85, pad=0.02)
    iv = np.where((wa["lon"] >= extent[0]) & (wa["lon"] <= extent[1]))[0]
    jv = np.where((wa["lat"] >= extent[2]) & (wa["lat"] <= extent[3]))[0]
    step = max(1, int(round(max(len(iv), len(jv), 1) / 18.0)))
    ax1.quiver(LON[::step, ::step], LAT[::step, ::step], uw[::step, ::step],
               vw[::step, ::step], color="k", width=0.0022, scale=380, alpha=0.9,
               zorder=4, transform=ccrs.PlateCarree())
    plotstyle.add_wind_levels(ax1, LON, LAT, sw, transform=ccrs.PlateCarree())
    ax1.set_title(f"风场  {t_wind} UTC　最大风速 {np.nanmax(sw):.1f} m/s",
                  fontsize=15, pad=8)

    if hs_k is not None:
        ax2 = plotstyle.map_axes(fig, [0.53, 0.07, 0.42, 0.80], extent)
        LON2, LAT2 = np.meshgrid(wlon, wlat)
        pc2 = ax2.pcolormesh(LON2, LAT2, hs_k, cmap="jet", vmin=0, vmax=8,
                             shading="auto", zorder=2, transform=ccrs.PlateCarree())
        plotstyle.add_colorbar(fig, ax2, pc2, "有效波高 (m)", [0, 2, 4, 6, 8],
                               shrink=0.85, pad=0.02)
        plotstyle.add_sea_state(ax2, LON2, LAT2, hs_k, transform=ccrs.PlateCarree())
        ax2.set_title(f"海浪  {t_wave} UTC　最大浪高 {np.nanmax(hs_k):.1f} m",
                      fontsize=15, pad=8)

    out = OUT_DIR / f"wind_wave_pair_{tag}.png"
    return [plotstyle.save(fig, out, dpi=120)]


# --------------------------------------------------------------------------- #
# ② 风 + 浪 动图
# --------------------------------------------------------------------------- #
def draw_wind_wave_gif(OUT_DIR: Path, ctx, tag: str, *, max_frames: int = 40,
                       every_hours: int = 3) -> List[str]:
    """逐帧渲染风+浪（每隔 every_hours 小时取一帧）→ PIL 存 GIF。"""
    import io

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    from PIL import Image

    plotstyle.setup()

    box = ctx.request.get("field_box")
    box = tuple(float(x) for x in box) if (box and len(box) == 4) else (114.0, 128.0, 17.0, 30.0)
    wind = _daily_wind(ctx)
    wa = _load_wind_arrays(wind["path"], box) if wind else None
    if not wa:
        return []

    spd = np.sqrt(wa["u"] ** 2 + wa["v"] ** 2)
    nt = spd.shape[0]
    idxs = list(range(0, nt, max(1, every_hours)))[:max_frames]
    LON, LAT = np.meshgrid(wa["lon"], wa["lat"])

    frames: List[Any] = []
    for k in idxs:
        fig = plt.figure(figsize=(11, 7.2))
        ax = plotstyle.map_axes(fig, [0.05, 0.06, 0.80, 0.86],
                                [box[0], box[1], box[2], box[3]])
        pc = ax.pcolormesh(LON, LAT, spd[k], cmap="jet", vmin=0, vmax=25,
                           shading="auto", zorder=2, transform=ccrs.PlateCarree())
        iv = np.where((wa["lon"] >= box[0]) & (wa["lon"] <= box[1]))[0]
        jv = np.where((wa["lat"] >= box[2]) & (wa["lat"] <= box[3]))[0]
        step = max(1, int(round(max(len(iv), len(jv), 1) / 16.0)))
        ax.quiver(LON[::step, ::step], LAT[::step, ::step], wa["u"][k][::step, ::step],
                  wa["v"][k][::step, ::step], color="k", width=0.0022, scale=380,
                  alpha=0.9, zorder=4, transform=ccrs.PlateCarree())
        plotstyle.add_wind_levels(ax, LON, LAT, spd[k], transform=ccrs.PlateCarree())
        t = str(wa["time"][k])[:16].replace("T", " ") if wa["time"] is not None else f"t={k}"
        ax.set_title(f"风场  {t} UTC　最大风速 {np.nanmax(spd[k]):.1f} m/s",
                     fontsize=13, pad=6)
        plotstyle.add_colorbar(fig, ax, pc, "风速 (m/s)",
                               [0, 5, 10, 15, 20, 25], shrink=0.85, pad=0.02)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert("RGB"))

    out = OUT_DIR / f"wind_wave_anim_{tag}.gif"
    p = plotstyle.make_gif(frames, out, duration=0.4)
    return [p] if p else []


# --------------------------------------------------------------------------- #
# ②' 直接取用课题三自己出的**成品图**（官方版本）
# --------------------------------------------------------------------------- #
def attach_official_products(ctx, code: str = "XMN", *, want_anim: bool = False,
                             mode: str = "auto") -> List[str]:
    """取课题三自己出的成品图，供对话直接展示（不必自己重画）。

    - 默认：0.01° 的最大增水场图 + 该站的 0.01° 站点时序图（平滑、权威）
    - want_anim=True：附带风+增水双面板动图或增水动图（约 18~20 MB，较慢）
    - 0.01° 那套缺的时候回退到 0.25° 的全场场图 / 站点曲线图
    """
    import re as _re

    try:
        from . import ai_daily
    except Exception:
        return []

    date = str(ctx.request.get("date", "") or "")
    m = _re.search(r"(\d{4})-?(\d{2})-?(\d{2})", date)
    d8 = f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else ""

    try:
        from orchestrator import geo_domain
        _n, _c = geo_domain.locate(str(ctx.request.get("region", "") or ""))
        rev = {"厦门": "XMN", "崇武": "CWU", "晋江": "JNJ", "东山东港": "DSN"}
        if _n in rev:
            code = rev[_n]
    except Exception:
        pass

    # ===== 判定一：局地取景（闽南、厦门沿海…）一律自己画，不用他们的成品图 =====
    #   他们的成品图分辨率/范围是全场或福建中南部，没有局地细节。
    _geo = ctx.results.get("geo_stats") or {}
    _box = _geo.get("field_box") or ctx.request.get("field_box") or []
    _span = (max(_box[1] - _box[0], _box[3] - _box[2])
             if len(_box) == 4 else 99.0)          # 99 = 不知道范围，按大范围处理
    _is_field = bool(_geo.get("field_query") or ctx.request.get("field_query"))
    _local = bool(_geo.get("point_grid")) or (_is_field and _span <= 4)
    if _local:
        ctx.results["official_products"] = []
        return []

    # ===== 判定二：要浪的成品图，还是要增水的成品图 =====
    _dis = str(ctx.request.get("disaster", "") or "")
    _plt = str(ctx.request.get("plot", "") or "").strip().lower()
    _wave = ("wave" in _dis.lower()) or ("浪" in _dis) or _plt in ("wave", "wave_field",
                                                                 "wave_station", "wind_wave")
    _buoy = str(ctx.request.get("buoy_code", "") or "").strip().upper()
    _station = (bool(_geo.get("sites")) or bool(ctx.request.get("station"))
                or _plt == "surge_station")
    if mode in ("station", "field"):
        _station = (mode == "station")

    def _first(kinds, c):
        for k in kinds:
            p = ai_daily.fetch_product(k, code=c, date=d8)
            if p:
                return p
        return None

    # 大范围（跨度 >4°，如"全场"）优先按"场"给图；
    # 注意：场查询的 geo_stats 里通常也带站点，不能因此被误判成"纯站点问法"
    #   注意 _span 在"没有框"时是 99（那是给"是否算局地"用的），
    #   所以这里必须要求**确实有框**，否则纯站点提问会被误判成大范围。
    _broad = (_is_field or len(_box) == 4) and _span > 4

    got: List[Dict[str, Any]] = []
    if _wave:
        # 海浪：他们出的是「浮标单点图」和「风+浪双面板动图」（动图 10~16 MB，只在场查询时取）
        if _buoy:
            p = _first(("buoy_viz",), _buoy)
            if p:
                got.append(p)
        if not got and (_broad or not _station):
            p = _first(("wave_double",), code)
            if p:
                got.append(p)
    elif _station and not _broad:
        # 站点：他们的 0.01° 站点时序图（缺则回退 0.25° 全场曲线图）
        p = _first(("timeseries", "curve_1"), code)
        if p:
            got.append(p)
    else:
        # 全场 / 大范围：他们的最大增水场图 + 该站时序图
        p = _first(("field_max", "field_max_1"), code)
        if p:
            got.append(p)
        p = _first(("timeseries", "curve_1"), code)
        if p:
            got.append(p)

    if want_anim:
        p = (ai_daily.fetch_product("wind_surge", code=code, date=d8)
             or ai_daily.fetch_product("anim", code=code, date=d8))
        if p and p.get("path") not in [g.get("path") for g in got]:
            got.append(p)

    ctx.results["official_products"] = got
    return [g["path"] for g in got if g.get("path")]


# --------------------------------------------------------------------------- #
# ③ 预报 vs 实测 密度散点
# --------------------------------------------------------------------------- #
def _pairs_from_ctx(ctx) -> Tuple[np.ndarray, np.ndarray, str, str]:
    """为台风个例配出 (预报, 实测) 对：浮标有效波高。

    预报：`geo_stats["wave_points"]`（课题三浮标点波高，逐站序列）
    实测：课题五观测文件 `wave_H`（二维：时间×站，站号在 `sta_id`）
    两者按时间轴对齐（起点差 ≤1.5h、步长一致）后逐点配对。
    """
    geo = (ctx.results or {}).get("geo_stats") or {}
    typh = str(ctx.request.get("typhoon", "") or "").strip()
    if not typh:
        return np.asarray([]), np.asarray([]), "", ""

    # 注意：geo_stats 为给 LLM 减负，把 wave_points 里的 series_m 剥掉了，
    # 这里重新取一次完整序列（目录与文件都已缓存，很快）。
    try:
        from . import ftp_typhoon as fty
        wps = fty.load_wave_point(typh)
        obs = fty.load_observation(typh)
    except Exception:
        return np.asarray([]), np.asarray([]), "", ""
    if not wps or not obs or "wave_H" not in obs:
        return np.asarray([]), np.asarray([]), "", ""

    arr = np.asarray(obs["wave_H"], dtype=float)
    ids = [str(x) for x in (obs.get("sta_id") or [])]
    if arr.ndim == 2 and ids and arr.shape[0] == len(ids):
        arr = arr.T                      # → (time, sta)
    if arr.ndim != 2 or not ids:
        return np.asarray([]), np.asarray([]), "", ""

    obs_base = obs.get("start_dt")
    obs_step = float(obs.get("step_hours") or 1.0)

    pred: List[float] = []
    true: List[float] = []
    for row in wps:
        code = str(row.get("station") or "")
        if code not in ids:
            continue
        j = ids.index(code)
        oser = arr[:, j]
        fser = [np.nan if v is None else float(v) for v in (row.get("series_m") or [])]
        if not fser:
            continue
        fbase = row.get("start_dt")
        fstep = float(row.get("step_hours") or 1.0)
        # 时间对齐：按"距预报起点的偏移小时数"找实测最近时刻
        try:
            off0 = (fbase - obs_base).total_seconds() / 3600.0 if (fbase and obs_base) else 0.0
        except Exception:
            off0 = 0.0
        for i, fv in enumerate(fser):
            if not np.isfinite(fv):
                continue
            t_h = off0 + i * fstep
            k = int(round(t_h / obs_step))
            if k < 0 or k >= oser.size:
                continue
            ov = oser[k]
            if np.isfinite(ov):
                pred.append(float(fv))
                true.append(float(ov))
    return (np.asarray(true), np.asarray(pred), "有效波高", "m") if pred else (
        np.asarray([]), np.asarray([]), "", "")


def draw_validation_density(OUT_DIR: Path, ctx, tag: str) -> List[str]:
    """预报 vs 实测 密度散点（课题三 metrics_plotter 风格：viridis + LogNorm + 指标框）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    plotstyle.setup()

    true, pred, what, unit = _pairs_from_ctx(ctx)
    if true.size < 30:
        return []

    rmse = float(np.sqrt(np.mean((true - pred) ** 2)))
    bias = float(np.mean(true - pred))
    r = float(np.corrcoef(true, pred)[0, 1])
    vmax = float(max(np.nanmax(true), np.nanmax(pred), 0.1))

    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=150)
    h = ax.hist2d(true, pred, bins=120, cmap=plt.cm.viridis,
                  norm=mcolors.LogNorm(vmax=1e3),
                  range=[[0, vmax], [0, vmax]])
    ax.plot([0, vmax], [0, vmax], color="k", lw=1.0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(f"实测 {what} ({unit})", fontsize=15)
    ax.set_ylabel(f"预报 {what} ({unit})", fontsize=15)
    ax.tick_params(labelsize=13)
    ax.grid(alpha=0.35)
    ax.text(0.05, 0.80,
            f"RMSE = {rmse:.3f} {unit}\nBias = {bias:.3f} {unit}\nR = {r:.3f}\nN = {true.size}",
            transform=ax.transAxes, fontsize=14,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", alpha=0.85))
    cb = fig.colorbar(h[3], ax=ax)
    cb.set_label("数据点密度", fontsize=13)
    cb.ax.tick_params(labelsize=12)
    ax.set_title(f"{what} 预报 vs 实测", fontsize=16, pad=10)

    out = OUT_DIR / f"validation_density_{tag}.png"
    return [plotstyle.save(fig, out, dpi=150)]
