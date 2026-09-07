"""一键生成样例 NC 数据（模拟 2526 台风风暴潮场，体积小，用于跑通链路）。

生成到 <项目根>/data/sample/ 下：
    output_0.nc   — 模拟「数值模拟」方案（变量与真实 output_0.nc 一致）
    output_4.nc   — 模拟「AI/融合」方案（含 wind/msl 驱动场）
    ERA5/…        — 模拟再分析风场（3 个日文件）

变量/维度与真实数据保持一致（可直接用 orchestrator/nc_inspect.py 体检）：
    time(秒, 每小时)  lat/lon(粗网格)  lats/lons(厦门附近细网格)
    elev / elevs(水位)  current_u/v(流速)  depth/depths(水深)
    output_4 另有 wind_x/wind_y/msl

用法：
    python scripts/make_sample_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sample"


def make_surge_file(path: Path, with_forcing: bool, seed: int) -> None:
    """生成一个模拟风暴潮场文件。"""
    rng = np.random.default_rng(seed)

    # 时间：169 时次 × 1 小时（秒），与真实数据一致
    n_time = 169
    time = 300.0 + np.arange(n_time) * 3600.0

    # 粗网格：113~128E / 18~30N，30 分度（缩小体积，真实为 1/6 度）
    lon = np.linspace(113.0, 128.0, 61)
    lat = np.linspace(18.0, 30.0, 49)
    LON, LAT = np.meshgrid(lon, lat)

    # 细网格（厦门附近）：117.9~118.5E / 24.35~24.65N，约 0.005°
    lons = np.linspace(117.90, 118.50, 121)
    lats = np.linspace(24.35, 24.65, 61)
    LONS, LATS = np.meshgrid(lons, lats)

    # 模拟增水：低频波动 + 台风过境信号（42h 附近抬升）
    def surge_series(t, amp):
        # 主体：昼夜潮周期(12.42h) + 台风增水包络(3天)
        tide = 0.15 * np.sin(2 * np.pi * t / (12.42 * 3600) + 0.3)
        storm = amp * np.exp(-((t - 42 * 3600) ** 2) / (2 * (30 * 3600) ** 2))
        return tide + storm

    t_axis = (time - time[0])
    base = surge_series(t_axis, 0.55)

    # elev（粗网格）：时间 × 纬度 × 经度，加空间扰动
    elev = (base[:, None, None]
            + 0.15 * rng.standard_normal((n_time, 1, 1))
            + 0.05 * np.sin(LON[None]) * np.cos(LAT[None]))
    elev = elev.astype("float32")

    # elevs（细网格，厦门附近更精细）
    elevs = (base[:, None, None]
             + 0.2 * rng.standard_normal((n_time, 1, 1))
             + 0.06 * np.sin(LONS[None]) * np.cos(LATS[None]))
    elevs = elevs.astype("float32")

    ds = xr.Dataset(
        {
            "elev": (("time", "lat", "lon"), elev, {"units": "m", "long_name": "storm surge elevation"}),
            "current_u": (("time", "lat", "lon"), rng.standard_normal((n_time, *LON.shape)).astype("float32") * 0.3, {"units": "m/s"}),
            "current_v": (("time", "lat", "lon"), rng.standard_normal((n_time, *LON.shape)).astype("float32") * 0.3, {"units": "m/s"}),
            "elevs": (("time", "lats", "lons"), elevs, {"units": "m", "long_name": "fine surge elevation"}),
            "depth": (("lat", "lon"), (20 + 15 * np.ma.masked_invalid(np.abs(LON - 120))).astype("float32"), {"units": "m"}),
            "depths": (("lats", "lons"), (15 + 5 * np.abs(np.sin(LONS))).astype("float32"), {"units": "m"}),
        },
        coords={
            "time": ("time", time, {"units": "seconds since 2025-11-08 00:00:00"}),
            "lon": ("lon", lon),
            "lat": ("lat", lat),
        },
    )
    if with_forcing:
        ds["wind_x"] = (("time", "lat", "lon"), (8 * np.sin(2 * np.pi * np.arange(n_time)[:, None, None] / 24) + rng.standard_normal((n_time, *LON.shape)) * 2).astype("float32"), {"units": "m/s"})
        ds["wind_y"] = (("time", "lat", "lon"), (6 * np.cos(2 * np.pi * np.arange(n_time)[:, None, None] / 24) + rng.standard_normal((n_time, *LON.shape)) * 2).astype("float32"), {"units": "m/s"})
        storm_pa = (101300 - 400 * np.exp(-((t_axis - 42 * 3600) ** 2) / (2 * (36 * 3600) ** 2)))
        ds["msl"] = (("time", "lat", "lon"), (storm_pa[:, None, None] + 0 * LON[None]).astype("float32"), {"units": "Pa"})

    # 二维坐标（与真实结构一致：lons/lats 是 2D）
    ds = ds.assign_coords(lons=(("lats", "lons"), LONS))
    ds = ds.assign_coords(lats=(("lats", "lons"), LATS))
    # 注意 lons/lats 是 2D 坐标，不能同时作为维度坐标，需以 dims 共享
    ds.to_netcdf(path)
    ds.close()


def make_era5(path: Path, day: str, seed: int) -> None:
    """生成一个模拟 ERA5 日文件（u10/v10/msl, 24h, 0.25°）。"""
    rng = np.random.default_rng(seed)
    lon = np.linspace(112.0, 129.0, 69)
    lat = np.linspace(31.0, 17.0, 57)
    time = np.datetime64(f"{day}T00") + np.arange(24) * np.timedelta64(1, "h")
    LON, LAT = np.meshgrid(lon, lat)
    u = (6 + 3 * np.sin(2 * np.pi * np.arange(24)[:, None, None] / 24) + rng.standard_normal((24, *LON.shape)) * 0.5).astype("float32")
    v = (2 + 2 * np.cos(2 * np.pi * np.arange(24)[:, None, None] / 24) + rng.standard_normal((24, *LON.shape)) * 0.5).astype("float32")
    msl = (101300 + rng.standard_normal((24, *LON.shape)) * 80).astype("float32")
    ds = xr.Dataset(
        {
            "u10": (("valid_time", "latitude", "longitude"), u, {"units": "m s**-1", "long_name": "10 metre U wind component"}),
            "v10": (("valid_time", "latitude", "longitude"), v, {"units": "m s**-1", "long_name": "10 metre V wind component"}),
            "msl": (("valid_time", "latitude", "longitude"), msl, {"units": "Pa", "long_name": "Mean sea level pressure"}),
        },
        coords={"valid_time": time, "latitude": lat, "longitude": lon},
    )
    ds.to_netcdf(path)
    ds.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    era5_dir = OUT_DIR / "ERA5"
    era5_dir.mkdir(parents=True, exist_ok=True)

    print("生成样例风暴潮场 output_0.nc（数值模拟）...")
    make_surge_file(OUT_DIR / "output_0.nc", with_forcing=False, seed=1)
    print("生成样例风暴潮场 output_4.nc（AI/融合，含驱动场）...")
    make_surge_file(OUT_DIR / "output_4.nc", with_forcing=True, seed=2)
    print("生成样例 ERA5 风场（3 个日文件）...")
    for i, day in enumerate(["2025-11-08", "2025-11-09", "2025-11-10"]):
        make_era5(era5_dir / f"{day.replace('-', '')}00.nc", day, seed=10 + i)

    total = sum(p.stat().st_size for p in OUT_DIR.rglob("*.nc"))
    print(f"完成：样例数据共 {total / 1024 / 1024:.1f} MB -> {OUT_DIR}")


if __name__ == "__main__":
    main()
