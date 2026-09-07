"""★ 选优模块：数值模式 vs 智能预报，进评估前选出更可信结果。

真实实现(骨架版)：
    对 ctx.files 中的两个风暴潮场(数值 output_0 / AI融合 output_4)，
    各自采样目标海域站点，比较最大增水/过程形态，选优并给出理由。

    ⚠️ 注意：当前选优为「规则兜底」(取两方案中峰值更高、更保守者，避免漏报)，
    后续接入评估指标(RMSE vs 实测/哨兵)时替换 _pick_by_metrics。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.contract import ModuleContext

SITES = {"厦门港": (118.07, 24.45)}


def _sample_max(path: str, lon_pt: float, lat_pt: float) -> Optional[Dict[str, Any]]:
    """对一个 NC 采样站点最大增水。"""
    import numpy as np
    import xarray as xr

    ds = None
    try:
        ds = xr.open_dataset(path)
        var = "elevs" if "elevs" in ds.variables else ("elev" if "elev" in ds.variables else None)
        if var is None:
            return None
        lons = ds["lons"].values if "lons" in ds else ds["lon"].values
        lats = ds["lats"].values if "lats" in ds else ds["lat"].values
        if np.asarray(lons).ndim == 1 or np.asarray(lats).ndim == 1:
            i = int(np.abs(ds["lon"].values - lon_pt).argmin())
            j = int(np.abs(ds["lat"].values - lat_pt).argmin())
            ts = ds[var].isel(lat=j, lon=i).values
        else:
            d2 = (lons - lon_pt) ** 2 + (lats - lat_pt) ** 2
            j, i = np.unravel_index(int(np.argmin(d2)), d2.shape)
            ts = ds[var].isel(lats=j, lons=i).values
        return {
            "max_cm": round(float(np.nanmax(ts)) * 100.0, 1),
            "mean_cm": round(float(np.nanmean(ts)) * 100.0, 1),
        }
    except Exception:
        return None
    finally:
        try:
            if ds is not None:
                ds.close()
        except Exception:
            pass


def run(ctx: ModuleContext) -> ModuleContext:
    num_path = ctx.files.get("nc_forecast_num")
    ai_path = ctx.files.get("nc_forecast_num_alt")

    stats = {}
    if num_path:
        stats["数值模式"] = _sample_max(num_path, *SITES["厦门港"])
    if ai_path:
        stats["智能预报"] = _sample_max(ai_path, *SITES["厦门港"])

    if not stats or not any(stats.values()):
        ctx.meta["selected_source"] = "智能预报"
        ctx.results["selector"] = {
            "status": "stub",
            "chosen": "智能预报",
            "reason": "占位：未找到两套数据",
        }
        return ctx

    # 规则选优：取两方案中最大增水更高者（更保守/更危险侧，避免漏报）
    chosen = max(stats, key=lambda k: stats[k]["max_cm"])

    ctx.meta["selected_source"] = chosen
    ctx.results["selector"] = {
        "status": "ok",
        "chosen": chosen,
        "reason": "取两方案中最大增水更保守者，避免漏报（规则兜底，待评估指标）",
        "sources": {
            k: {"max_cm": v["max_cm"], "mean_cm": v["mean_cm"]}
            for k, v in stats.items() if v
        },
    }
    return ctx
