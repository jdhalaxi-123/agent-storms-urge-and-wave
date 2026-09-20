# -*- coding: utf-8 -*-
"""课题三「每日业务化预报」取数器（**人工智能方法**）。

数据性质（已核实）
------------------
`/group3/ATM_new/dailyforecast/` 下**全部是人工智能方法的预报结果**，模型为 `CuboidWaveModel`
（文件属性 `title/institution/source` 均指向该模型，变量名带 `_torch` 后缀）。
`ATM` 与 `EC` **不是"AI 与数值"之分，而是"同一 AI 模型的两种风场输入"**：
    ATM → 课题三 `/group3/shared_wind_inputs/atm_forecast_YYYYMMDD.nc`
    EC  → ECMWF `YYYYMMDDHH00_ECMWF_wind_msl.nc`

可用数据
--------
    surge_field       AI 风暴潮场     168h, 0.25°, 114~128°E / 17~30°N, `surge`(cm)   2.04 MB
    wave_field        AI 海浪场       144h, 64×72, `hs_torch`(m)                      13 MB
    total_water_field AI 总水位场     `rotated_total_water_level_*.nc`                66 MB
    tide_prediction   AI/潮汐预报     逐时天文潮 CSV，按站按天                        8 KB
    point_surge       单点风暴潮      `storm_surge_forecast_{站}_{起}-{止}.nc`         10 KB
    point_wave        单点波浪        `ATM_point_wave_{站}_{日期}.nc`                  11 KB

日期命名一律为 `YYYYMMDD`（起报日）。
"""
from __future__ import annotations

import datetime
import io
import os
import re
import time
from typing import Any, Dict, List, Optional

import numpy as np

from orchestrator import ftp_catalog as fc

# 各数据源路径
# ⭐ 对方有**两套镜像**目录，谁的数据新就用谁（早前旧路径 550，改成固定 ATM_new；
#    2026-09-20 实测两条都在，且只有旧路径有当天数据）→ 见 refresh_df()
DF_CANDIDATES = ("/group3/dailyforecast", "/group3/ATM_new/dailyforecast")
DF = DF_CANDIDATES[1]
_df_checked_at = 0.0
_df_ttl_sec = 300.0
SURGE_FIELD_DIR = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"      # atm_forecast_YYYYMMDD/
STATION_FIG_DIR = f"{DF}/storm_surge_point_system/figures"     # <站点>_<起>_<止>.tif（站点预报系统）
WAVE_FIELD_DIR = f"{DF}/AutoWave/res_ATM"                                   # YYYYMMDD_wave_forecast_1h.nc
WAVE_FIELD_DIR_EC = f"{DF}/AutoWave/res_EC"
TOTAL_WATER_DIR = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"      # rotated_total_water_level_*.nc
TIDE_DIR = f"{TOTAL_WATER_DIR}/tide"                                        # 站_tide_prediction_*.csv
STATION_FIELD_DIR = f"{TOTAL_WATER_DIR}/stations_nc"                        # total_water_level_field_站_*.nc
POINT_SURGE_DIR = f"{DF}/storm_surge_point_system/nc_file"
POINT_WAVE_DIR = f"{DF}/wave_for_single_point/outputs/nc_file"


def _df_latest_date(root: str) -> str:
    """该 root 下"最新一期"的日期（用 0.01° 最大增水场图的文件名日期代表）。"""
    try:
        es = _ls(f"{root}/storm_surge_for_spatiotemporal_2/results_atm")
    except Exception:  # noqa: BLE001
        return ""
    best = ""
    for e in es:
        if e["dir"]:
            continue
        m = re.search(r"surge_max_(\d{8})\.png$", e["name"])
        if m and m.group(1) > best:
            best = m.group(1)
    return best


def _ec_latest_date(root: str) -> str:
    """该 root 下 EC 强迫结果的最新期。"""
    try:
        es = _ls(f"{root}/storm_surge_for_spatiotemporal_2/results_ec")
    except Exception:  # noqa: BLE001
        return ""
    best = ""
    for e in es:
        if e["dir"]:
            continue
        m = re.search(r"surge_max_(\d{8})\.png$", e["name"])
        if m and m.group(1) > best:
            best = m.group(1)
    return best


def best_ec_root(force: bool = False) -> str:
    """EC 强迫那套要**单独挑**：两套镜像的 EC 更新进度不一样
    （2026-09-20 实测：活跃路径的 EC 只到 20260624，另一条到 20260817）。"""
    key = "ec_root"
    now = time.time()
    if not force and key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]
    best_root, best_date = DF, ""
    for root in DF_CANDIDATES:
        d = _ec_latest_date(root)
        if d > best_date:
            best_root, best_date = root, d
    print(f"[ai_daily] EC 数据取：{best_root}（最新期 {best_date or '无'}）")
    _mem[key] = {"t": now, "v": best_root}
    return best_root


def refresh_df(force: bool = False, ttl: float = None) -> str:
    """在两套镜像里挑**数据最新**的那条作为数据根目录（带 TTL，避免每条查询都探）。"""
    global DF, PROD2, PROD2_EC, PROD1, PROD1_EC, STATION_FIG_DIR, POINT_SURGE_DIR, \
        POINT_WAVE_DIR, WAVE_FIELD_DIR, WAVE_FIELD_DIR_EC, SURGE_FIELD_DIR, \
        TOTAL_WATER_DIR, TIDE_DIR, STATION_FIELD_DIR, FINE_SURGE_DIR, _df_checked_at
    now = time.time()
    if not force and (now - _df_checked_at) < (_df_ttl_sec if ttl is None else ttl):
        return DF
    best_root, best_date = DF, ""
    info = []
    for root in DF_CANDIDATES:
        d = _df_latest_date(root)
        info.append(f"{root} → {d or '不可用'}")
        if d > best_date:
            best_root, best_date = root, d
    if best_root != DF:
        print(f"[ai_daily] 切换数据根目录：{DF} → {best_root}（最新期 {best_date}）"
              f"　[{'; '.join(info)}]")
    DF = best_root
    PROD2 = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"
    PROD2_EC = f"{DF}/storm_surge_for_spatiotemporal_2/results_ec"
    PROD1 = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"
    PROD1_EC = f"{DF}/storm_surge_for_spatiotemporal_1/results_ec"
    SURGE_FIELD_DIR = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"
    STATION_FIG_DIR = f"{DF}/storm_surge_point_system/figures"
    POINT_SURGE_DIR = f"{DF}/storm_surge_point_system/nc_file"
    POINT_WAVE_DIR = f"{DF}/wave_for_single_point/outputs/nc_file"
    WAVE_FIELD_DIR = f"{DF}/AutoWave/res_ATM"
    WAVE_FIELD_DIR_EC = f"{DF}/AutoWave/res_EC"
    TOTAL_WATER_DIR = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"
    # ⭐ 这三个是导入时固定的别名，必须一起重建，否则 0.01° 精细场还指着旧镜像
    TIDE_DIR = f"{TOTAL_WATER_DIR}/tide"
    STATION_FIELD_DIR = f"{TOTAL_WATER_DIR}/stations_nc"
    FINE_SURGE_DIR = TOTAL_WATER_DIR
    _df_checked_at = now
    return DF
# 每日风场不在 dailyforecast 下，单独在 /group3/wind（约 260 MB/天，是 AI 风暴潮/海浪的驱动）
WIND_DIR = "/group3/wind"                                                    # atm_forecast_YYYYMMDD.nc

# 站点
SURGE_STATIONS = {"厦门": "XMN", "崇武": "CWU", "晋江": "JNJ", "东山东港": "DSN"}
SURGE_CODE2CN = {v: k for k, v in SURGE_STATIONS.items()}
TIDE_STATIONS = {"厦门": "XMN", "崇武": "CWU", "晋江": "JNJ", "东山东港": "DSN"}

_mem: Dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _ls(path: str) -> List[Dict[str, Any]]:
    ftp = fc.ftp_client._connect()
    try:
        return fc._ls(ftp, path)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def _dates_from(entries: List[Dict[str, Any]], pat: str = r"(\d{8})") -> List[str]:
    out = []
    for e in entries:
        m = re.search(pat, e["name"])
        if m:
            out.append(m.group(1))
    return sorted(set(out))


# --------------------------------------------------------------------------- #
# ① AI 风暴潮场（2 MB，168h，0.25°）
# --------------------------------------------------------------------------- #
def list_surge_dates(force: bool = False) -> List[str]:
    key = "surge_dates"
    if not force and key in _mem:
        return _mem[key]
    out = []
    for e in _ls(SURGE_FIELD_DIR):
        if e["dir"]:
            m = re.search(r"atm_forecast_(\d{8})", e["name"])
            if m:
                out.append(m.group(1))
    out = sorted(set(out))
    _mem[key] = out
    return out


def load_surge_field(date: str = "", use_ec: bool = False) -> Optional[Dict[str, Any]]:
    """读取 AI 风暴潮场。date 为起报日 YYYYMMDD，空则取最新。

    返回 {"lat","lon","surge_cm"(time,lat,lon),"times","date","start_dt","source"...}
    """
    import xarray as xr

    dates = list_surge_dates()
    if not dates:
        return None
    date = date if date in dates else dates[-1]
    sub = f"atm_forecast_{date}"
    cands = [e for e in _ls(f"{SURGE_FIELD_DIR}/{sub}")
             if not e["dir"] and e["name"].endswith(".nc")]
    if not cands:
        return None
    f = sorted(cands, key=lambda x: x["name"])[-1]
    lp = fc.fetch(f["path"], expected_size=f["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        lat = np.asarray(ds["lat"].values, dtype=float)
        lon = np.asarray(ds["lon"].values, dtype=float)
        arr = np.asarray(ds["surge"].values, dtype=float)
        base = None
        if "time" in ds.variables:
            m = re.search(r"since\s+(\d{4})[- ]?(\d{2})[- ]?(\d{2})",
                          str(ds["time"].attrs.get("units", "")))
            if m:
                base = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif date:
                base = datetime.datetime.strptime(date, "%Y%m%d")
        ds.close()
    except Exception as e:  # noqa: BLE001
        print(f"[ai_daily] 读 AI 风暴潮场失败: {e}")
        return None
    # 统一为 (time, lat, lon)
    if arr.ndim == 3 and arr.shape[0] != len(base and [] or []) and arr.shape[1] == lat.size:
        pass
    if arr.ndim == 3 and arr.shape[1:] != (lat.size, lon.size) and arr.shape[:2] == (lat.size, lon.size):
        arr = np.transpose(arr, (2, 0, 1))

    # 同样没有自带陆地掩膜：陆地格点置 NaN（否则"区域峰值"可能落在陆地）
    try:
        from . import landmask
        arr = landmask.apply_land_nan(arr, lon, lat, key="surge_025")
    except Exception as e:  # noqa: BLE001
        print(f"[ai_daily] 0.25°场陆地掩膜失败（按原值使用）: {e}")

    return {
        "lat": lat, "lon": lon, "surge_cm": arr,
        "n_times": int(arr.shape[0]) if arr.ndim == 3 else 1,
        "date": date, "start_dt": base,
        "file": os.path.basename(lp), "size_mb": round(f["size"] / 1e6, 2),
        "source": f"课题三 AI 每日预报（CuboidWaveModel 体系）· 起报 {date}",
        "path": f["path"],
    }


def field_stats(field: Dict[str, Any], box: Optional[tuple] = None) -> Dict[str, Any]:
    """对（可裁剪的）场做统计：最大增水、出现在哪、分级面积、超阈值格点数。"""
    if not field:
        return {}
    lat, lon = field["lat"], field["lon"]
    arr = field["surge_cm"]
    if arr.ndim == 2:
        arr = arr[None, ...]
    LON, LAT = np.meshgrid(lon, lat)
    m = np.ones(LAT.shape, dtype=bool)
    if box:
        m = (LON >= box[0]) & (LON <= box[1]) & (LAT >= box[2]) & (LAT <= box[3])
    if not m.any():
        return {}
    sub = arr[:, m]                        # (time, ncell)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # 陆地掩膜会造出全 NaN 切片
        mx = np.nanmax(sub, axis=0)        # 每格点过程最大
        if not np.isfinite(mx).any():
            return {}
        k = int(np.nanargmax(mx))
        jj, ii = np.where(m)
        peak_lon = float(LON[jj[k], ii[k]])
        peak_lat = float(LAT[jj[k], ii[k]])
        # 峰值时刻
        peak_t = int(np.nanargmax(np.nanmax(sub, axis=1)))
    peak_dt = None
    if field.get("start_dt"):
        peak_dt = field["start_dt"] + datetime.timedelta(hours=peak_t)
    # 分级格点数（增水 cm）
    total = int(np.isfinite(mx).sum())
    lv = {
        "红色(≥120cm)": int(np.sum(mx >= 120)),
        "橙色(80~120)": int(np.sum((mx >= 80) & (mx < 120))),
        "黄色(50~80)": int(np.sum((mx >= 50) & (mx < 80))),
        "蓝色(30~50)": int(np.sum((mx >= 30) & (mx < 50))),
    }
    return {
        "box": box,
        "n_cells": total,
        "max_cm": round(float(np.nanmax(mx)), 1),
        "min_cm": round(float(np.nanmin(mx)), 1),
        "mean_cm": round(float(np.nanmean(mx)), 1),
        "p95_cm": round(float(np.nanpercentile(mx[np.isfinite(mx)], 95)), 1) if total else None,
        "peak_lon": round(peak_lon, 2), "peak_lat": round(peak_lat, 2),
        "peak_dt": peak_dt, "peak_hour_index": peak_t,
        "levels": lv,
        "level_main": next((k2 for k2, v in lv.items() if v > 0), "无"),
        "grid_res": round(float(abs(lon[1] - lon[0])) if len(lon) > 1 else 0.25, 3),
    }


# --------------------------------------------------------------------------- #
# ② AI 海浪场（13 MB，144h，64×72）
# --------------------------------------------------------------------------- #
def list_wave_dates(force: bool = False) -> List[str]:
    key = "wave_dates"
    if not force and key in _mem:
        return _mem[key]
    out = _dates_from(_ls(WAVE_FIELD_DIR), r"^(\d{8})_wave_forecast")
    _mem[key] = out
    return out


def load_wave_field(date: str = "", use_ec: bool = False) -> Optional[Dict[str, Any]]:
    """读取 AI 海浪场（hs_torch, m）。"""
    import xarray as xr

    dates = list_wave_dates()
    if not dates:
        return None
    date = date if date in dates else dates[-1]
    d = WAVE_FIELD_DIR_EC if use_ec else WAVE_FIELD_DIR
    name = f"{date}_wave_forecast_1h.nc"
    entries = {e["name"]: e for e in _ls(d)}
    e = entries.get(name)
    if not e:
        return None
    lp = fc.fetch(e["path"], expected_size=e["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        lat = np.asarray(ds["latitude"].values, dtype=float)
        lon = np.asarray(ds["longitude"].values, dtype=float)
        hs = np.asarray(ds["hs_torch"].values, dtype=float)
        # 陆地掩膜（海=1）：浪场在陆地上也可能有数值，出图/统计前必须套上，
        # 否则会出现"浪爬到陆地上"和等值线穿过陆地。
        mask = None
        if "mask" in ds.variables:
            mask = np.asarray(ds["mask"].values)
        base = None
        if "time" in ds.variables:
            base = datetime.datetime.strptime(date, "%Y%m%d")
        src_attrs = {k: str(v)[:60] for k, v in ds.attrs.items()}
        ds.close()
    except Exception as e2:  # noqa: BLE001
        print(f"[ai_daily] 读 AI 海浪场失败: {e2}")
        return None
    if mask is not None and mask.shape == hs.shape[-2:]:
        hs = np.where(mask[None, :, :] > 0, hs, np.nan) if hs.ndim == 3 else \
            np.where(mask > 0, hs, np.nan)
    return {"lat": lat, "lon": lon, "hs_m": hs, "mask": mask, "n_times": int(hs.shape[0]),
            "date": date, "start_dt": base, "file": name,
            "size_mb": round(e["size"] / 1e6, 2), "attrs": src_attrs,
            "source": f"课题三 AI 海浪预报（{'EC' if use_ec else 'ATM'} 风场驱动）· 起报 {date}",
            "path": e["path"]}


def wave_field_stats(field: Dict[str, Any], box: Optional[tuple] = None) -> Dict[str, Any]:
    if not field:
        return {}
    lat, lon = field["lat"], field["lon"]
    hs = field["hs_m"]
    LON, LAT = np.meshgrid(lon, lat)
    m = np.ones(LAT.shape, dtype=bool)
    if box:
        m = (LON >= box[0]) & (LON <= box[1]) & (LAT >= box[2]) & (LAT <= box[3])
    if not m.any():
        return {}
    sub = hs[:, m]
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # 陆地掩膜会造出全 NaN 切片
        mx = np.nanmax(sub, axis=0)
        if not np.isfinite(mx).any():
            return {}
        k = int(np.nanargmax(mx))
        jj, ii = np.where(m)
        peak_t = int(np.nanargmax(np.nanmax(sub, axis=1)))
    peak_dt = field["start_dt"] + datetime.timedelta(hours=peak_t) if field.get("start_dt") else None
    lv = {
        "红色(≥9m)": int(np.sum(mx >= 9)),
        "橙色(6~9m)": int(np.sum((mx >= 6) & (mx < 9))),
        "黄色(4~6m)": int(np.sum((mx >= 4) & (mx < 6))),
        "蓝色(2.5~4m)": int(np.sum((mx >= 2.5) & (mx < 4))),
    }
    return {"box": box, "n_cells": int(np.isfinite(mx).sum()),
            "max_m": round(float(np.nanmax(mx)), 2),
            "mean_m": round(float(np.nanmean(mx)), 2),
            "peak_lon": round(float(LON[jj[k], ii[k]]), 2),
            "peak_lat": round(float(LAT[jj[k], ii[k]]), 2),
            "peak_dt": peak_dt, "levels": lv,
            "level_main": next((k2 for k2, v in lv.items() if v > 0), "无")}


# --------------------------------------------------------------------------- #
# ③ 天文潮预报（CSV，按站按天）
# --------------------------------------------------------------------------- #
def list_tide_dates(force: bool = False) -> List[str]:
    key = "tide_dates"
    if not force and key in _mem:
        return _mem[key]
    out = _dates_from(_ls(TIDE_DIR), r"tide_prediction_(\d{8})")
    _mem[key] = out
    return out


def load_tide_prediction(code: str, date: str = "") -> Optional[Dict[str, Any]]:
    """读取某站某天的逐时天文潮预报（CSV）。

    返回 {"code","date","times":[...],"tide_m":[...],"start_dt"}
    """
    dates = list_tide_dates()
    if not dates:
        return None
    date = date if date in dates else dates[-1]
    name = f"{code}_tide_prediction_{date}.csv"
    entries = {e["name"]: e for e in _ls(TIDE_DIR)}
    e = entries.get(name)
    if not e:
        return None
    lp = fc.fetch(e["path"], expected_size=e["size"])
    if not lp:
        return None
    try:
        with open(lp, encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        times, vals = [], []
        for ln in lines[1:]:
            parts = ln.split(",")
            if len(parts) < 2:
                continue
            try:
                t = datetime.datetime.fromisoformat(parts[0].replace("+00:00", "").strip())
            except Exception:
                continue
            try:
                v = float(parts[1])
            except Exception:
                continue
            times.append(t)
            vals.append(v)
        if not times:
            return None
        return {"code": code, "date": date, "times": times, "tide_m": vals,
                "start_dt": times[0], "n": len(times),
                "source": f"课题三 天文潮预报 {code} {date}",
                "path": e["path"]}
    except Exception as ex:  # noqa: BLE001
        print(f"[ai_daily] 读潮汐预报失败: {ex}")
        return None


# --------------------------------------------------------------------------- #
# ④ 单点（风暴潮 / 波浪）
# --------------------------------------------------------------------------- #
def list_point_surge_files(code: str = "XMN", limit: int = 400) -> List[Dict[str, Any]]:
    """列单点风暴潮预报文件。

    站文件有**多套命名**，全部要认：
        storm_surge_forecast_sp_XMN_20260915-20260921.nc   ← 当前（带 sp_）
        storm_surge_forecast_XMN_20250715-20250721.nc      ← 早期（不带 sp_）
        storm_surge_forecast_sp_CWU_20250705-20250707_gfs.nc ← gfs 后缀
    """
    pat = re.compile(rf"storm_surge_forecast_(?:sp_)?{re.escape(code)}_(\d{{8}})-(\d{{8}})(?:_\w+)?\.nc$")
    out = []
    for e in _ls(POINT_SURGE_DIR):
        if e["dir"]:
            continue
        m = pat.match(e["name"])
        if m:
            out.append({"name": e["name"], "path": e["path"], "size": e["size"],
                        "start": m.group(1), "end": m.group(2), "mtime": e.get("mtime", "")})
    return sorted(out, key=lambda x: x["start"])[-limit:]


def load_point_surge(code: str = "XMN", date: str = "") -> Optional[Dict[str, Any]]:
    """读取单点风暴潮预报（7 天滚动，纯增水 cm）。date 为空取**最新起报**。"""
    import xarray as xr

    files = list_point_surge_files(code)
    if not files:
        return None
    f = files[-1] if not date else next((x for x in files if x["start"] == date), files[-1])
    lp = fc.fetch(f["path"], expected_size=f["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        var = "storm_surge" if "storm_surge" in ds.variables else list(ds.data_vars)[0]
        arr = np.asarray(ds[var].values, dtype=float).ravel()
        base = datetime.datetime.strptime(f["start"], "%Y%m%d")
        ds.close()
    except Exception as ex:  # noqa: BLE001
        print(f"[ai_daily] 读单点风暴潮失败: {ex}")
        return None
    return {"code": code, "name": SURGE_CODE2CN.get(code, code),
            "series_cm": arr.tolist(), "start_dt": base,
            "n": int(arr.size), "file": f["name"],
            "source": f"课题三 AI 每日预报 单点增水 {code} {f['start']}~{f['end']}",
            "path": f["path"]}


def list_point_wave_dates(code: str = "C6W10") -> List[str]:
    """AI 单点波浪的可用起报日。

    注意：文件放在**按日期分的子目录**里：
        wave_for_single_point/outputs/nc_file/{YYYYMMDD}/ATM_point_wave_{站号}_{YYYYMMDD}.nc
    旧格式也可能直接放在 nc_files/ 下，两种都要找。
    """
    out = set()
    pat = re.compile(rf"ATM_point_wave_{re.escape(code)}_(\d{{8}})\.nc$")
    for e in _ls(POINT_WAVE_DIR):
        if e["dir"]:
            d = e["name"]
            if re.fullmatch(r"\d{8}", d):
                for sub in _ls(e["path"]):
                    m = pat.match(sub["name"])
                    if m:
                        out.add(m.group(1))
        else:
            m = pat.match(e["name"])
            if m:
                out.add(m.group(1))
    # 兼容旧目录 nc_files/
    old = POINT_WAVE_DIR.replace("/nc_file", "/nc_files")
    for e in _ls(old):
        if not e["dir"]:
            m = pat.match(e["name"])
            if m:
                out.add(m.group(1))
    return sorted(out)


def list_point_wave_stations(date: str = "") -> List[str]:
    """列出某一期（默认最新）海浪单点的**浮标站号**。

    注意：海浪单点与风暴潮单点是**两套不同的站**——
        风暴潮单点：XMN 厦门 / CWU 崇武 / JNJ 晋江 / DSN 东山东港
        海浪单点  ：46694A / C6W10 … 等浮标站号（无中文名、也没有经纬度表）
    """
    key = f"wpt:sta:{date or 'latest'}"
    now = time.time()
    if key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]

    codes: set = set()
    pat = re.compile(r"ATM_point_wave_([A-Za-z0-9]+)_(\d{8})\.nc$")
    dirs: List[str] = []
    for e in _ls(POINT_WAVE_DIR):
        if e["dir"] and re.fullmatch(r"\d{8}", e["name"]):
            dirs.append(e["name"])
    dirs.sort()
    pick = [date] if (date and date in dirs) else dirs[-1:]
    if pick:
        for sub in _ls(f"{POINT_WAVE_DIR}/{pick[0]}"):
            m = pat.match(sub["name"])
            if m:
                codes.add(m.group(1))
    if not codes:      # 兼容旧布局
        for e in _ls(POINT_WAVE_DIR):
            m = pat.match(e["name"])
            if m:
                codes.add(m.group(1))
    out = sorted(codes)
    _mem[key] = {"t": now, "v": out}
    return out


def load_point_wave(code: str = "C6W10", date: str = "") -> Optional[Dict[str, Any]]:
    """读取单点 AI 波浪预报（swh, m）。date 为空取最新起报日。"""
    import xarray as xr

    dates = list_point_wave_dates(code)
    if not dates:
        return None
    d = date if date in dates else dates[-1]
    name = f"ATM_point_wave_{code}_{d}.nc"
    cands = []
    for cand in (f"{POINT_WAVE_DIR}/{d}/{name}", f"{POINT_WAVE_DIR}/{name}",
                 f"{POINT_WAVE_DIR.replace('/nc_file', '/nc_files')}/{d}/{name}",
                 f"{POINT_WAVE_DIR.replace('/nc_file', '/nc_files')}/{name}"):
        cands.append(cand)
    target = None
    for c in cands:
        base, _, fn = c.rpartition("/")
        for e in _ls(base):
            if e["name"] == fn and not e["dir"]:
                target = e
                break
        if target:
            break
    if not target:
        return None
    lp = fc.fetch(target["path"], expected_size=target["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        base_dt = datetime.datetime.strptime(d, "%Y%m%d")
        row = {"code": code, "date": d, "start_dt": base_dt, "file": name,
               "size": target["size"]}
        for key, v in (("series_m", "swh"), ("period_s", "mwp"), ("dir_deg", "mwd")):
            if v in ds.variables:
                row[key] = np.asarray(ds[v].values, dtype=float).ravel().tolist()
        ds.close()
        row["n"] = len(row.get("series_m") or [])
        arr = np.asarray([v for v in (row.get("series_m") or []) if v is not None], dtype=float)
        row["max_hs_m"] = round(float(arr.max()), 2) if arr.size else None
        row["source"] = f"课题三 AI 波浪预报 单点 {code} 起报 {d}"
        row["path"] = target["path"]
        return row
    except Exception as ex:  # noqa: BLE001
        print(f"[ai_daily] 读单点波浪失败: {ex}")
        return None


# --------------------------------------------------------------------------- #
# ⑦ 每日风场（/group3/wind/atm_forecast_YYYYMMDD.nc，约 260 MB/天）
# --------------------------------------------------------------------------- #
def list_wind_dates(force: bool = False) -> List[str]:
    """可用的每日风场起报日（升序）。"""
    key = "wind:dates"
    now = time.time()
    if not force and key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]
    try:
        dates = _dates_from(_ls(WIND_DIR), r"atm_forecast_(\d{8})\.nc")
    except Exception:
        dates = []
    _mem[key] = {"t": now, "v": dates}
    return dates


def wind_latest() -> str:
    d = list_wind_dates()
    return d[-1] if d else ""


def load_wind(date: str = "", force: bool = False) -> Optional[Dict[str, Any]]:
    """取回每日风场文件（本地路径）。date 为空取最新起报日。

    注意：单个文件约 260 MB，**首次取用 30~60 秒**，之后走本地缓存秒读。
    路径：/group3/wind/atm_forecast_YYYYMMDD.nc
    """
    key = f"wind:{date or 'latest'}"
    now = time.time()
    if not force and key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]

    if not date:
        date = wind_latest()
    if not date:
        return None

    remote = f"{WIND_DIR}/atm_forecast_{date}.nc"
    try:
        ftp = fc.ftp_client._connect()
        try:
            sz = fc._stat_size(ftp, remote)
        finally:
            ftp.quit()
    except Exception:
        sz = 0
    if not sz:
        return None

    local = fc.fetch(remote, force=force, expected_size=sz)
    if not local:
        return None

    info: Dict[str, Any] = {
        "path": local,
        "file": os.path.basename(local),
        "date": date,
        "size_mb": round(sz / 1e6, 1),
        "source": "课题三每日风场 /group3/wind（AI 预报的驱动风场）",
    }
    try:
        info["start_dt"] = datetime.datetime.strptime(date, "%Y%m%d")
    except Exception:
        pass
    _mem[key] = {"t": now, "v": info}
    return info


def wind_stats(info: Dict[str, Any], box: Optional[tuple] = None) -> Dict[str, Any]:
    """读每日风场文件，算关键风力指标（判断"风有多大、影响哪儿"）。

    box = (lon_min, lon_max, lat_min, lat_max)；None 用整个文件覆盖范围。
    返回：峰值风速/位置/时间、区域平均峰值、6/8/10 级格点数、4 个站点的最大风。
    """
    import xarray as xr

    path = (info or {}).get("path")
    if not path:
        return {}
    ds = xr.open_dataset(path, decode_times=True)
    try:
        latn = "latitude" if "latitude" in ds else ("lat" if "lat" in ds else None)
        lonn = "longitude" if "longitude" in ds else ("lon" if "lon" in ds else None)
        un = next((v for v in ("u10", "u10m", "uwnd", "wind_x") if v in ds.variables), None)
        vn = next((v for v in ("v10", "v10m", "vwnd", "wind_y") if v in ds.variables), None)
        if not (latn and lonn and un and vn):
            return {}

        la_all = np.asarray(ds[latn].values).ravel()
        lo_all = np.asarray(ds[lonn].values).ravel()
        sub = ds
        if box:
            if latn in ds.dims and lonn in ds.dims:
                sub = ds.sel({lonn: slice(box[0], box[1]), latn: slice(box[2], box[3])})
            else:
                ldim, odim = ds[latn].dims[0], ds[lonn].dims[0]
                j = np.where((la_all >= box[2]) & (la_all <= box[3]))[0]
                i = np.where((lo_all >= box[0]) & (lo_all <= box[1]))[0]
                if j.size and i.size:
                    sub = ds.isel({ldim: slice(int(j[0]), int(j[-1]) + 1),
                                   odim: slice(int(i[0]), int(i[-1]) + 1)})

        u = np.asarray(sub[un].values, dtype=float)
        v = np.asarray(sub[vn].values, dtype=float)
        spd = np.sqrt(u ** 2 + v ** 2)
        if spd.ndim != 3:
            return {}
        tname = "valid_time" if "valid_time" in sub else ("time" if "time" in sub else None)
        tv = np.asarray(sub[tname].values).ravel() if tname else None
        la = np.asarray(sub[latn].values).ravel()
        lo = np.asarray(sub[lonn].values).ravel()

        per_t = np.nanmax(spd, axis=(1, 2))
        k = int(np.nanargmax(per_t))
        jj, ii = np.unravel_index(np.nanargmax(spd[k]), spd[k].shape)
        peak_ms = float(per_t[k])

        mean_t = np.nanmean(spd, axis=(1, 2))
        km = int(np.nanargmax(mean_t))
        flat = spd[km]

        stations = {}
        for cn, coord in (("厦门", (118.25, 24.50)), ("崇武", (119.00, 25.00)),
                          ("晋江", (118.50, 24.50)), ("东山东港", (117.50, 23.75))):
            ix = int(np.argmin(np.abs(lo - coord[0])))
            iy = int(np.argmin(np.abs(la - coord[1])))
            s = spd[:, iy, ix]
            ks = int(np.nanargmax(s))
            stations[cn] = {
                "speed_ms": round(float(s[ks]), 1),
                "time": str(tv[ks])[:16] if tv is not None else "",
            }

        return {
            "box": list(box) if box else None,
            "peak": {
                "speed_ms": round(peak_ms, 1),
                "speed_kmh": round(peak_ms * 3.6),
                "beaufort": beaufort(peak_ms),
                "lon": round(float(lo[ii]), 3),
                "lat": round(float(la[jj]), 3),
                "time": str(tv[k])[:16] if tv is not None else "",
            },
            "mean_peak_ms": round(float(mean_t[km]), 1),
            "mean_peak_time": str(tv[km])[:16] if tv is not None else "",
            "counts": {
                "g6": int(np.nansum(flat >= 10.8)),
                "g8": int(np.nansum(flat >= 17.2)),
                "g10": int(np.nansum(flat >= 24.5)),
                "n": int(flat.size),
            },
            "stations": stations,
            "n_time": int(spd.shape[0]),
            "lon_range": [round(float(lo.min()), 2), round(float(lo.max()), 2)],
            "lat_range": [round(float(la.min()), 2), round(float(la.max()), 2)],
            "start": str(tv[0])[:16] if tv is not None else "",
            "end": str(tv[-1])[:16] if tv is not None else "",
        }
    finally:
        try:
            ds.close()
        except Exception:
            pass


def beaufort(ms: float) -> str:
    """风速(m/s) → 蒲福风力等级。"""
    try:
        v = float(ms)
    except Exception:
        return ""
    for lim, name in ((0.3, "0级"), (1.6, "1级"), (3.4, "2级"), (5.5, "3级"), (8.0, "4级"),
                      (10.8, "5级"), (13.9, "6级"), (17.2, "7级"), (20.8, "8级"),
                      (24.5, "9级"), (28.5, "10级"), (32.7, "11级")):
        if v < lim:
            return name
    return "12级以上"


# --------------------------------------------------------------------------- #
# ⑧ 每日**精细**增水场（0.01°，福建中南部近海，33 MB/天）
#    surge_predicted_YYYYMMDD.nc  361×136  116.70~120.30°E / 23.83~25.17°N
#    小区域（如闽南）用它，格点细 25 倍，不再一格一格
# --------------------------------------------------------------------------- #
FINE_SURGE_DIR = TOTAL_WATER_DIR
FINE_SURGE_DOMAIN = (116.70, 120.30, 23.83, 25.17)   # lon_min, lon_max, lat_min, lat_max


def list_fine_surge_dates(force: bool = False) -> List[str]:
    key = "fine:dates"
    now = time.time()
    if not force and key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]
    try:
        dates = _dates_from(_ls(FINE_SURGE_DIR), r"surge_predicted_(\d{8})\.nc")
    except Exception:
        dates = []
    _mem[key] = {"t": now, "v": dates}
    return dates


def fine_surge_covers(box) -> bool:
    """给定的经纬度框是否完全落在精细场范围内（留一点余量）。"""
    if not box or len(box) != 4:
        return False
    lo0, lo1, la0, la1 = FINE_SURGE_DOMAIN
    return (box[0] >= lo0 - 0.05 and box[1] <= lo1 + 0.05
            and box[2] >= la0 - 0.05 and box[3] <= la1 + 0.05)


def fine_surge_clip(box, min_ratio: float = 0.5):
    """把请求框与精细场范围取交集。

    完全覆盖 → 原框；部分重叠且重叠面积占比 ≥ min_ratio → 返回交集（只画精细场覆盖的那部分）；
    否则返回 None（改用 0.25° 场）。
    """
    if not box or len(box) != 4:
        return None
    lo0, lo1, la0, la1 = FINE_SURGE_DOMAIN
    if fine_surge_covers(box):
        return tuple(float(x) for x in box)
    ix0, ix1 = max(box[0], lo0), min(box[1], lo1)
    iy0, iy1 = max(box[2], la0), min(box[3], la1)
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    inter = (ix1 - ix0) * (iy1 - iy0)
    whole = max((box[1] - box[0]) * (box[3] - box[2]), 1e-9)
    if inter / whole >= min_ratio:
        return (float(ix0), float(ix1), float(iy0), float(iy1))
    return None


def load_fine_surge_field(date: str = "", force: bool = False) -> Optional[Dict[str, Any]]:
    """读取每日**精细**增水场（0.01°）。date 为空取最新起报日。单文件 33 MB。"""
    key = f"fine:{date or 'latest'}"
    now = time.time()
    if not force and key in _mem and now - _mem[key]["t"] < 600:
        return _mem[key]["v"]

    dates = list_fine_surge_dates()
    if not dates:
        return None
    d = date if (date and date in dates) else dates[-1]
    remote = f"{FINE_SURGE_DIR}/surge_predicted_{d}.nc"
    ftp = fc.ftp_client._connect()
    try:
        sz = fc._stat_size(ftp, remote)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    if not sz:
        return None
    lp = fc.fetch(remote, force=force, expected_size=sz)
    if not lp:
        return None

    import xarray as xr
    try:
        ds = xr.open_dataset(lp, decode_times=True)
        lat = np.asarray(ds["latitude"].values, dtype=float)
        lon = np.asarray(ds["longitude"].values, dtype=float)
        surge = np.asarray(ds["surge"].values, dtype=float)
        base = None
        try:
            tv = np.asarray(ds["time"].values).ravel()
            if tv.size:
                import datetime as _dt
                base = _dt.datetime.strptime(d, "%Y%m%d")
        except Exception:
            pass
        ds.close()
    except Exception as e:
        print(f"[ai_daily] 读精细增水场失败: {e}")
        return None

    # ⭐ 这个场**没有自带陆地掩膜**，陆地上也有非零数值（曾导致"区域峰值"落在泉州内陆）。
    #    这里用 Natural Earth 海岸线生成掩膜，把陆地格点置 NaN。
    try:
        from . import landmask
        surge = landmask.apply_land_nan(surge, lon, lat, key="fine_surge")
    except Exception as e:  # noqa: BLE001
        print(f"[ai_daily] 精细场陆地掩膜失败（按原值使用）: {e}")

    info = {"lat": lat, "lon": lon, "surge_cm": surge, "n_times": int(surge.shape[0]),
            "date": d, "start_dt": base, "file": f"surge_predicted_{d}.nc",
            "size_mb": round(sz / 1e6, 1), "path": remote, "local": lp,
            "fine": True, "res": 0.01, "land_masked": True,
            "source": f"课题三 每日人工智能预报·精细网格(0.01°) 起报 {d}"}
    _mem[key] = {"t": now, "v": info}
    return info


def fine_field_stats(field: Dict[str, Any], box: Optional[tuple] = None) -> Dict[str, Any]:
    """精细场统计（结构同 field_stats，单位 cm）。"""
    st = field_stats(field, box)
    if st:
        st["fine_grid"] = True
        st["res"] = 0.01
    return st


# --------------------------------------------------------------------------- #
# ⑨ 课题三自己出的**成品图**（PNG/GIF）——可直接取用，不必自己画
#    _2 目录：基于 0.01° 旋转网格（福建中南部），平滑
#    _1 目录：基于 0.25° 全场网格，方格明显（且台湾是白洞）
# --------------------------------------------------------------------------- #
# 下面这几个由 refresh_df() 统一重建（勿在别处硬编码路径）
PROD2 = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"
PROD2_EC = f"{DF}/storm_surge_for_spatiotemporal_2/results_ec"   # EC(ECMWF) 强迫，0.01°
PROD1 = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"
PROD1_EC = f"{DF}/storm_surge_for_spatiotemporal_1/results_ec"   # EC(ECMWF) 强迫，0.25° 全场
STATION_CN_FULL = {"XMN": "厦门", "CWU": "崇武", "JNJ": "晋江", "DSN": "东山"}


def _prod_newest_deep(dirpath: str, pattern: str, depth: int = 2):
    """先在本目录找，找不到再往子目录钻 depth 层（成品图常在 gifs_output/ 这类子目录里）。"""
    b = _prod_newest(dirpath, pattern)
    if b:
        return b
    if depth <= 0:
        return None
    try:
        subs = [e for e in _ls(dirpath) if e["dir"]]
    except Exception:  # noqa: BLE001
        return None
    for e in subs:
        b = _prod_newest_deep(e["path"], pattern, depth - 1)
        if b:
            return b
    return None


def _prod_newest(dirpath: str, pattern: str):
    """目录里日期最大的匹配文件 → (日期, entry)。"""
    pat = re.compile(pattern)
    best = None
    for e in _ls(dirpath):
        if e["dir"]:
            continue
        m = pat.search(e["name"])
        if not m:
            continue
        d = m.group(1)
        if best is None or d > best[0]:
            best = (d, e)
    return best


def _tif_to_png(tif_path: str) -> Optional[str]:
    """TIFF → PNG（浏览器不能直接显示 TIFF）。

    只生成**显示用副本**，原图原封不动、内容不重绘；文件名加 _view 以示区分。
    """
    try:
        from PIL import Image
        dst = os.path.splitext(tif_path)[0] + "_view.png"
        im = Image.open(tif_path)
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        im.convert("RGB").save(dst)
        return dst
    except Exception as ex:  # noqa: BLE001
        print(f"[ai_daily] TIFF 转 PNG 失败: {ex}")
        return None


def fetch_product(kind: str, code: str = "XMN", date: str = "") -> Optional[Dict[str, Any]]:
    """取回课题三的成品图，返回 {path,date,kind,file,grid,size_mb}。

    kind:
        field_max   _2 最大增水场图（0.01°，福建中南部）   surge_max_YYYYMMDD.png
        timeseries  _2 站点时序图（0.01° 网格）            surge_XMN_timeseries_YYYYMMDD.png
        anim        _2 增水动图（约 20 MB）                surge_animation_YYYYMMDD.gif
        field_max_1 _1 最大增水场图（0.25°，全场）         surge_max_atm_forecast_YYYYMMDD.png
        curve_1     _1 站点曲线图（0.25° 网格）            <中文站名>_surge_curve_atm_forecast_YYYYMMDD.png
        wind_surge  _1 风+增水双面板动图（约 18 MB）       wind_surge_double_atm_forecast_YYYYMMDD.gif
    """
    code = str(code or "XMN").upper()
    cn = STATION_CN_FULL.get(code, "厦门")

    # ⭐ 对方（课题三）**只有两张成品动图**：AutoWave/gifs_output 里
    #    ATM*(全场预报) 与 EC*(EC 预报) 的风+浪双面板。
    #    spatiotemporal 目录下的 surge_animation*/wind_surge_double* **不是他们的成品**，
    #    已按用户指认停用，避免"乱挪用结果"。
    if kind in ("anim", "wind_surge"):
        return None

    if kind == "station_fig":
        # 站点预报系统的**单站成品图**（用户指认：这才是 group3 每天更新的单点图）
        #   <CODE>_<起报日>_<结束时>.tif
        _pat = re.compile(rf"{code}_(\d{{8}})_\d{{8}}\.tif$")
        b = None
        try:
            for e in _ls(STATION_FIG_DIR):
                if e["dir"]:
                    continue
                m = _pat.match(e["name"])
                if m and (b is None or m.group(1) > b[0]):
                    b = (m.group(1), e)
        except Exception:  # noqa: BLE001
            b = None
        if not b:
            return None
        d, e = b
        lp = fc.fetch(e["path"], expected_size=e["size"])
        if not lp:
            return None
        png = _tif_to_png(lp)                      # 浏览器不能显示 TIFF
        return {"path": png or lp, "date": d, "kind": kind, "file": e["name"],
                "size_mb": round(e["size"] / 1e6, 2),
                "grid": "站点预报系统 · 单站风暴潮过程曲线",
                "converted_from": (e["name"] if png else "")}

    # ===== EC（ECMWF）强迫那一套：只在用户点名 EC 时用 =====
    if kind.startswith("ec_"):
        _ecr = best_ec_root()
        _ec2 = f"{_ecr}/storm_surge_for_spatiotemporal_2/results_ec"
        _ec1 = f"{_ecr}/storm_surge_for_spatiotemporal_1/results_ec"
        if kind == "ec_field_max":          # 0.01° 最大增水场图
            b = _prod_newest(_ec2, r"surge_max_(\d{8})\.png")
            grid = "EC 强迫 · 0.01° 最大增水场图（福建中南部）"
        elif kind == "ec_timeseries":       # 0.01° 站点时序图
            b = _prod_newest(_ec2, rf"surge_{code}_timeseries_(\d{{8}})\.png")
            grid = "EC 强迫 · 0.01° 站点增水时序图（单站）"
        elif kind == "ec_anim":             # 0.01° 增水动图
            b = _prod_newest(_ec2, r"surge_animation_(\d{8})\.gif")
            grid = "EC 强迫 · 0.01° 增水动图"
        elif kind == "ec_field_max_1":      # 0.25° 全场最大增水场图
            b = _prod_newest(_ec1, r"surge_max_(\d{8})\.png")
            grid = "EC 强迫 · 0.25° 全场最大增水场图"
        elif kind == "ec_anim_1":           # 0.25° 全场增水动图
            b = _prod_newest(_ec1, r"surge_animation_(\d{8})\.gif")
            grid = "EC 强迫 · 0.25° 全场增水动图"
        elif kind == "ec_wind_surge":       # 0.25° 风+增水联合动图
            b = _prod_newest(_ec1, r"wind_surge_combined_(\d{8})\.gif")
            grid = "EC 强迫 · 0.25° 风+增水联合动图"
        else:
            return None
        if not b:
            return None
        d, e = b
        lp = fc.fetch(e["path"], expected_size=e["size"])
        return ({"path": lp, "date": d, "kind": kind, "file": e["name"],
                 "size_mb": round(e["size"] / 1e6, 2), "grid": grid}
                if lp else None)

    if kind in ("wave_double", "wave_double_ec"):
        # 风+浪双面板动图（只有这两张是他们出的）：
        #   wave_double    ATM 起报 = 全场预报
        #   wave_double_ec EC  起报 = EC 预报
        _pre, _grid = (("ATM", "全场预报 · 风+浪双面板动图") if kind == "wave_double"
                       else ("EC", "EC 预报 · 风+浪双面板动图"))
        b = _prod_newest_deep(f"{DF}/AutoWave",
                              rf"{_pre}(\d{{8}})_wind_wave_forecast_cartopy\.gif")
        if not b:
            return None
        d, e = b
        lp = fc.fetch(e["path"], expected_size=e["size"])
        return ({"path": lp, "date": d, "kind": kind, "file": e["name"],
                 "size_mb": round(e["size"] / 1e6, 2), "grid": _grid}
                if lp else None)

    if kind in ("buoy_viz",):
        pat = rf"ATM_point_wave_{code}_viz_(\d{{8}})\.png"
        # 图现在放在 wave_for_single_point/outputs/visualization/，nc 在 outputs/nc_file/
        b = (_prod_newest_deep(f"{DF}/wave_for_single_point/outputs/visualization", pat,
                               depth=2)
             or _prod_newest_deep(f"{DF}/wave_for_single_point", pat, depth=3))
        if not b:
            return None
        d, e = b
        lp = fc.fetch(e["path"], expected_size=e["size"])
        return ({"path": lp, "date": d, "kind": kind, "file": e["name"],
                 "size_mb": round(e["size"] / 1e6, 2), "grid": "浮标单点（课题三成品图）"}
                if lp else None)

    if kind in ("field_max", "timeseries", "anim"):
        pat = {"field_max": r"surge_max_(\d{8})\.png",
               "timeseries": rf"surge_{code}_timeseries_(\d{{8}})\.png",
               "anim": r"surge_animation_(\d{8})\.gif"}[kind]
        b = _prod_newest(PROD2, pat)
        if not b:
            return None
        d, e = b
        lp = fc.fetch(e["path"], expected_size=e["size"])
        if not lp:
            return None
        return {"path": lp, "date": d, "kind": kind, "file": e["name"],
                "size_mb": round(e["size"] / 1e6, 2),
                "grid": "0.01° 旋转网格（福建中南部）"}

    if kind in ("field_max_1", "curve_1", "wind_surge"):
        dirs = sorted({e["name"] for e in _ls(PROD1)
                       if e["dir"] and re.fullmatch(r"atm_forecast_\d{8}", e["name"])})
        if not dirs:
            return None
        want = f"atm_forecast_{date}" if date else ""
        pick = want if want in dirs else dirs[-1]
        d = pick.replace("atm_forecast_", "")
        fname = {"field_max_1": f"surge_max_atm_forecast_{d}.png",
                 "curve_1": f"{cn}_surge_curve_atm_forecast_{d}.png",
                 "wind_surge": f"wind_surge_double_atm_forecast_{d}.gif"}[kind]
        remote = f"{PROD1}/{pick}/{fname}"
        ftp = fc.ftp_client._connect()
        try:
            sz = fc._stat_size(ftp, remote)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
        if not sz:
            return None
        lp = fc.fetch(remote, expected_size=sz)
        if not lp:
            return None
        return {"path": lp, "date": d, "kind": kind, "file": fname,
                "size_mb": round(sz / 1e6, 2), "grid": "0.25°（全场）"}
    return None


# --------------------------------------------------------------------------- #
# 概览
# --------------------------------------------------------------------------- #
def overview() -> Dict[str, Any]:
    """当前可用的 AI 每日预报概览（供“今天有什么预报”这类问题）。"""
    sd = list_surge_dates()
    wd = list_wave_dates()
    td = list_tide_dates()
    try:
        nd = list_wind_dates()
    except Exception:
        nd = []
    return {
        "surge_field_dates": sd[-6:], "surge_field_latest": sd[-1] if sd else "",
        "surge_field_n": len(sd),
        "wave_field_dates": wd[-6:], "wave_field_latest": wd[-1] if wd else "",
        "wave_field_n": len(wd),
        "tide_dates": td[-6:], "tide_latest": td[-1] if td else "", "tide_n": len(td),
        "wind_dates": nd[-6:], "wind_latest": nd[-1] if nd else "", "wind_n": len(nd),
        "source": "课题三 /group3/ATM_new/dailyforecast + /group3/wind（人工智能方法）",
    }


# --------------------------------------------------------------------------- #
# 数据时效（每日预报有固定更新时点，agent 必须知道"今天的出来没有"）
# --------------------------------------------------------------------------- #
# 从 FTP 文件修改时间实测到的每日更新时点（北京时间）
UPDATE_SCHEDULE = "约 09:00 与 14:40 分批更新"


def _latest_mtime(force: bool = False) -> Dict[str, Any]:
    """取最新一批预报文件的修改时间，用于说明"数据是什么时候出来的"。"""
    key = "latest_mtime"
    if not force and key in _mem:
        return _mem[key]
    out: Dict[str, Any] = {"surge_field": "", "wave_field": "", "point": ""}
    dates = list_surge_dates()
    if dates:
        sub = f"{SURGE_FIELD_DIR}/atm_forecast_{dates[-1]}"
        es = [e for e in _ls(sub) if not e["dir"]]
        if es:
            out["surge_field"] = max(e.get("mtime", "") for e in es)
    wd = list_wave_dates()
    if wd:
        es = [e for e in _ls(WAVE_FIELD_DIR) if e["name"].startswith(wd[-1])]
        if es:
            out["wave_field"] = max(e.get("mtime", "") for e in es)
    _mem[key] = out
    return out


def _fmt_mtime(mt: str) -> str:
    """FTP 的 modify 形如 20260915144112.000 -> 2026-09-15 14:41。"""
    m = re.match(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})", str(mt))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}" if m else ""


def update_info(now: Optional[datetime.datetime] = None, kind: str = "surge") -> Dict[str, Any]:
    """返回每日 AI 预报的**数据时效状态**。

    kind: "surge"（风暴潮场）或 "wave"（海浪场）

    返回：
        latest_date     最新一次预报的起报日 YYYYMMDD
        latest_start    该次起报时刻（YYYY-MM-DD 00:00）
        cover_end       该次预报覆盖到的时刻（起报 + 时长）
        generated_at    该批文件的实际生成时间（来自 FTP 修改时间）
        today_ready     今天的预报是否已经发布
        note            给用户看的时效说明（今天的没出来 / 请求日期超出覆盖）
    """
    now = now or datetime.datetime.now()
    if kind == "wave":
        dates, hours = list_wave_dates(), 144
        gen_key = "wave_field"
    else:
        dates, hours = list_surge_dates(), 168
        gen_key = "surge_field"
    latest = dates[-1] if dates else ""
    today = now.strftime("%Y%m%d")
    mt = _latest_mtime().get(gen_key, "")

    info: Dict[str, Any] = {
        "latest_date": latest, "today": today, "schedule": UPDATE_SCHEDULE,
        "generated_at": _fmt_mtime(mt), "n_dates": len(dates),
        "today_ready": bool(latest == today),
        "hours": hours,
    }
    if latest:
        try:
            st = datetime.datetime.strptime(latest, "%Y%m%d")
            info["latest_start"] = st.strftime("%Y-%m-%d %H:%M")
            info["cover_end"] = (st + datetime.timedelta(hours=hours - 1)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    # 今天的数据到了没有
    if latest and latest < today:
        d_today = datetime.datetime.strptime(today, "%Y%m%d")
        d_latest = datetime.datetime.strptime(latest, "%Y%m%d")
        lag = (d_today - d_latest).days
        info["note_today"] = (
            f"⏰ **数据时效提醒**：今日（{today[:4]}-{today[4:6]}-{today[6:]}）的预报**尚未更新**"
            f"（课题三每日人工智能预报{UPDATE_SCHEDULE}发布），"
            f"最近一次为**起报 {info.get('latest_start', '')}**"
            + (f"，生成于 {info['generated_at']}" if info.get("generated_at") else "")
            + f"，滞后 {lag} 天。以下结果为该次预报，覆盖至 {info.get('cover_end', '')}。"
        )
    elif latest:
        info["note_today"] = (
            f"⏰ 今日预报已更新（起报 {info.get('latest_start', '')}"
            + (f"，生成于 {info['generated_at']}" if info.get("generated_at") else "")
            + f"，覆盖至 {info.get('cover_end', '')}）。"
        )
    return info


def date_check(target_date: str, now: Optional[datetime.datetime] = None,
               kind: str = "surge") -> Dict[str, Any]:
    """检查用户想看的日期是否在最新预报的覆盖范围内。

    target_date 支持 "今天"/"明天"/"昨天"/"2026-09-16"/"9月16日"/""（空=今天）
    """
    refresh_df()          # 两套镜像里挑最新的一份（带 TTL）
    now = now or datetime.datetime.now()
    s = str(target_date or "").strip()
    d = None
    rel = ""
    if not s or s in ("未指定", "今天", "今日", "现在", "当前", "最近"):
        d, rel = now.date(), "今天"
    elif "明天" in s or "明日" in s:
        d, rel = now.date() + datetime.timedelta(days=1), "明天"
    elif "昨天" in s or "昨日" in s:
        d, rel = now.date() - datetime.timedelta(days=1), "昨天"
    elif "后天" in s:
        d, rel = now.date() + datetime.timedelta(days=2), "后天"
    else:
        m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", s)
        if not m:
            m = re.search(r"(\d{1,2})[-/月](\d{1,2})", s)
            if m:
                try:
                    d = datetime.date(now.year, int(m.group(1)), int(m.group(2)))
                except Exception:
                    d = None
        else:
            try:
                d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                d = None
    info = update_info(now, kind)
    info["target_date"] = d.strftime("%Y-%m-%d") if d else ""
    info["target_rel"] = rel
    if d and info.get("cover_end"):
        try:
            ce = datetime.datetime.strptime(info["cover_end"], "%Y-%m-%d %H:%M")
            if datetime.datetime.combine(d, datetime.time(23, 59)) > ce:
                info["out_of_coverage"] = True
                info["note_target"] = (
                    f"⏰ **数据时效提醒**：{info['target_date']} 超出最近一次预报的覆盖范围"
                    f"（起报 {info.get('latest_start','')}，覆盖至 {info.get('cover_end','')}）。"
                    f"课题三每日人工智能预报{UPDATE_SCHEDULE}发布，"
                    f"{info['target_date']} 的预报尚未更新。以下展示最近一次预报的结果。"
                )
        except Exception:
            pass
    return info


if __name__ == "__main__":  # python -m modules.ai_daily
    import json
    ov = overview()
    print(json.dumps(ov, ensure_ascii=False, indent=2))
    print("\n--- AI 风暴潮场（最新）---")
    f = load_surge_field()
    if f:
        print(f"  {f['file']}  {f['size_mb']} MB  {f['n_times']} 时次  起报 {f['date']}")
        print(f"  网格 lat={f['lat'].size} lon={f['lon'].size}  "
              f"范围 {f['lon'].min():.1f}~{f['lon'].max():.1f}E / {f['lat'].min():.1f}~{f['lat'].max():.1f}N")
        for name, box in (("全域", None), ("福建", (117.0, 120.5, 23.0, 27.5)),
                          ("台湾海峡", (117.5, 121.0, 22.5, 25.5))):
            st = field_stats(f, box)
            if st:
                print(f"  [{name}] 最大增水 {st['max_cm']} cm @({st['peak_lon']},{st['peak_lat']}) "
                      f"峰值 {st['peak_dt']}  分级 {st['levels']}")
    print("\n--- AI 海浪场（最新）---")
    w = load_wave_field()
    if w:
        print(f"  {w['file']}  {w['size_mb']} MB  {w['n_times']} 时次")
        st = wave_field_stats(w, (117.0, 120.5, 23.0, 27.5))
        print(f"  [福建] 最大浪高 {st.get('max_m')} m @({st.get('peak_lon')},{st.get('peak_lat')}) 峰值 {st.get('peak_dt')}")
    print("\n--- 天文潮预报 ---")
    t = load_tide_prediction("XMN")
    if t:
        print(f"  厦门 {t['date']}  {t['n']} 小时  {t['tide_m'][0]:.2f} ~ {max(t['tide_m']):.2f} m")


# 导入时先选一次数据根目录（失败不影响启动，回退默认值）
try:
    _pick_done = True
    refresh_df(force=True)
except Exception as _e:  # noqa: BLE001
    print(f"[ai_daily] 初始化数据根目录失败（沿用默认）: {_e}")
