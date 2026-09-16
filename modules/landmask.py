# -*- coding: utf-8 -*-
"""陆地掩膜（基于 Natural Earth 10m 陆地多边形，shapely 判定，按网格缓存）。

为什么需要
----------
课题三的增水场（0.25° 与 0.01° 精细场）**没有自带陆地掩膜**，陆地上也有非零数值：
闽南那张图里"区域峰值 22.3 cm"其实落在泉州内陆，前 50 大格点有 46 个在陆地。
海浪场自带 `mask`（海=1），所以只有它之前没出问题。

用法
----
    from . import landmask
    m = landmask.land_mask(lon1d, lat1d, key="fine_surge_136x361")   # True=陆地
    vals = np.where(m[None, :, :], np.nan, vals)                     # 陆地置 NaN

首次计算约几秒（49096 点），之后从 `stormdata/cache/masks/` 直接读。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np

from orchestrator import paths

MASK_DIR = paths.CACHE_DIR / "masks"
_mem: dict = {}


def _cache_file(key: str, shape) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(key))
    return MASK_DIR / f"{safe}_{shape[0]}x{shape[1]}.npy"


def land_mask(lon1d, lat1d, key: str = "") -> Optional[np.ndarray]:
    """返回 True=陆地的二维布尔掩膜（形状 nlat×nlon）。

    lon1d/lat1d 为一维经纬度（规则网格）。结果按 (key, 形状) 缓存到磁盘。
    """
    lon = np.asarray(lon1d, dtype=float).ravel()
    lat = np.asarray(lat1d, dtype=float).ravel()
    shape = (lat.size, lon.size)
    if key and key in _mem and _mem[key].shape == shape:
        return _mem[key]

    MASK_DIR.mkdir(parents=True, exist_ok=True)
    cf = _cache_file(key or "grid", shape)
    if cf.exists():
        try:
            m = np.load(cf)
            if m.shape == shape:
                _mem[key] = m
                return m
        except Exception:
            pass

    try:
        import cartopy.io.shapereader as shpreader
        from shapely.geometry import Point, box
        from shapely.ops import unary_union
        from shapely.prepared import prep

        p = shpreader.natural_earth(resolution="10m", category="physical", name="land")
        bbox = box(lon.min() - 0.5, lat.min() - 0.5, lon.max() + 0.5, lat.max() + 0.5)
        geoms = [g for g in shpreader.Reader(p).geometries() if g.intersects(bbox)]
        if not geoms:
            return None
        union = prep(unary_union(geoms))

        LON, LAT = np.meshgrid(lon, lat)
        m = np.zeros(shape, dtype=bool)
        for j in range(shape[0]):
            pts = [Point(LON[j, i], LAT[j, i]) for i in range(shape[1])]
            for i, pt in enumerate(pts):
                if union.contains(pt):
                    m[j, i] = True
    except Exception as e:  # noqa: BLE001
        print(f"[landmask] 生成失败（按全海处理）: {e}")
        return None

    try:
        np.save(cf, m)
    except Exception:
        pass
    if key:
        _mem[key] = m
    return m


def apply_land_nan(values: np.ndarray, lon1d, lat1d, key: str = "") -> np.ndarray:
    """把陆地格点置为 NaN（values 形状 (nlat, nlon) 或 (time, nlat, nlon)）。"""
    m = land_mask(lon1d, lat1d, key)
    if m is None:
        return values
    v = np.asarray(values, dtype=float)
    if v.ndim == 2:
        return np.where(m, np.nan, v)
    if v.ndim == 3:
        return np.where(m[None, :, :], np.nan, v)
    return v
