"""模块② 地理信息提取 · NC 插值 · 统计分析。

真实实现：
    1. 从 ctx.files 取风暴潮场 NC（数值/融合均可）；
    2. 自动识别变量：优先 elevs(精细网格,厦门附近)，回退 elev(粗网格)；
    3. 对目标海域站点(厦门港/同安湾/东山等) 最近网格点采样时间序列；
    4. 统计：最大增水(cm)、峰值时刻、过程曲线(降采样)、是否超阈。

输出 ctx.results["geo_stats"]：
    {
        "status": "ok" | "no_data",
        "source_file": str,
        "sites": [{"name","lon","lat","max_surge_cm","peak_idx","peak_time","series"}],
        "max_surge_cm": float,          # 全区最大的站点值
        "peak_time": str,               # 对应时刻
        "series": [...],                # 主站(厦门港)过程曲线
        "region": str,
    }
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import numpy as np

from orchestrator.contract import ModuleContext

# 站点表（名称 -> 经纬度）。厦门中心关注的重点站位，后续可用站点文件覆盖。
SITES: Dict[str, tuple] = {
    "厦门港": (118.07, 24.45),
    "同安湾": (118.15, 24.55),
    "东山东港": (117.42, 23.70),
    "石狮": (118.72, 24.82),
    "漳浦": (117.62, 23.99),
}

# 预警级别阈值（增水 cm）：按国标风暴潮增水经验阈值，可参数化
THRESHOLDS = {"黄色": 50.0, "橙色": 80.0, "红色": 120.0}


def _find_variable(ds, candidates: List[str]) -> Optional[str]:
    """按候选名找存在的变量。"""
    for c in candidates:
        if c in ds.variables:
            return c
    return None


def _sample_at(ds, var: str, lon_pt: float, lat_pt: float) -> np.ndarray:
    """在 2D 网格(lats/lons)上取最近点的时间序列。"""
    lons = ds["lons"].values if "lons" in ds.coords or "lons" in ds.variables else None
    lats = ds["lats"].values if "lats" in ds.coords or "lats" in ds.variables else None
    if lons is None or lats is None:
        # 粗网格：用 lon/lat 1D 坐标
        lon_1d = ds["lon"].values
        lat_1d = ds["lat"].values
        i = int(np.abs(lon_1d - lon_pt).argmin())
        j = int(np.abs(lat_1d - lat_pt).argmin())
        return ds[var].isel(lat=j, lon=i).values
    d2 = (lons - lon_pt) ** 2 + (lats - lat_pt) ** 2
    j, i = np.unravel_index(int(np.argmin(d2)), d2.shape)
    return ds[var].isel(lats=j, lons=i).values if "lats" in ds[var].dims else ds[var].isel(lat=j, lon=i).values


def _fmt_time(t_val: Any, base: str = "2025-11-08") -> str:
    """把时间值格式化为字符串。

    支持两种形态：
      - numpy datetime64 / datetime.datetime（CF 解码后）
      - float 相对秒（真实数据 time=300/3900/... 秒，自起始时刻）
    """
    import datetime

    try:
        if hasattr(t_val, "astype") and "datetime64" in str(getattr(t_val, "dtype", "")):
            t_val = t_val.astype("datetime64[s]")
            t_val = t_val.astype(datetime.datetime)
        elif hasattr(t_val, "item"):
            t_val = t_val.item()
        if isinstance(t_val, np.datetime64):
            t_val = t_val.astype("datetime64[s]").item()
        if isinstance(t_val, datetime.datetime):
            return t_val.strftime("%m-%d %H:%M")
        if isinstance(t_val, (int, float)):
            if abs(t_val) < 10**7:  # 相对秒（7天内≈60万）
                base_dt = datetime.datetime.strptime(base, "%Y-%m-%d")
                return (base_dt + datetime.timedelta(seconds=float(t_val))).strftime("%m-%d %H:%M")
            if 10**17 < abs(t_val) < 10**19:  # 纳秒时间戳（datetime64[ns]）
                return datetime.datetime.fromtimestamp(float(t_val) / 1e9).strftime("%m-%d %H:%M")
    except Exception:
        pass
    return str(t_val)


def run(ctx: ModuleContext) -> ModuleContext:
    import xarray as xr

    path = ctx.files.get("nc_forecast_num") or (
        ctx.files.get("surge_files") or [None]
    )[0]
    if not path:
        ctx.results["geo_stats"] = {"status": "no_data", "sites": [], "series": []}
        return ctx

    try:
        ds = xr.open_dataset(path)
    except Exception as exc:
        ctx.results["geo_stats"] = {"status": "no_data", "error": str(exc), "sites": [], "series": []}
        return ctx

    try:
        # 变量自动识别：精细网格优先
        var = _find_variable(ds, ["elevs", "elev"])
        if var is None:
            ctx.results["geo_stats"] = {"status": "no_data", "error": "找不到 elev/elevs 变量", "sites": []}
            return ctx

        time = ds["time"].values
        sites: List[Dict[str, Any]] = []
        for name, (lon_p, lat_p) in SITES.items():
            ts = _sample_at(ds, var, lon_p, lat_p)
            valid = ts[~np.isnan(ts)] if np.issubdtype(np.asarray(ts).dtype, np.number) else ts
            if len(valid) == 0:
                continue
            # 最大增水(cm)。注意 elev 单位:米 -> 厘米
            max_val_m = float(np.nanmax(valid))
            peak_idx = int(np.nanargmax(valid))
            max_cm = round(max_val_m * 100.0, 1)
            series = [round(float(v * 100.0), 1) for v in np.asarray(valid)[:: max(1, len(valid) // 30)]]
            sites.append({
                "name": name,
                "lon": lon_p,
                "lat": lat_p,
                "max_surge_cm": max_cm,
                "peak_idx": peak_idx,
                "peak_time": _fmt_time(float(time[peak_idx])),
                "series": series,
            })

        if not sites:
            ctx.results["geo_stats"] = {"status": "no_data", "sites": [], "series": []}
            return ctx

        # 全区最大
        top = max(sites, key=lambda s: s["max_surge_cm"])
        ctx.results["geo_stats"] = {
            "status": "ok",
            "source_file": str(path),
            "variable": var,
            "region": ctx.request.get("region"),
            "sites": sites,
            "max_surge_cm": top["max_surge_cm"],
            "peak_time": top["peak_time"],
            "peak_site": top["name"],
            "series": sites[0]["series"],
            "site_count": len(sites),
        }
        return ctx
    finally:
        ds.close()
