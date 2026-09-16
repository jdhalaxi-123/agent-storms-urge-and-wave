# -*- coding: utf-8 -*-
"""课题三「每日业务化预报」取数器（**人工智能方法**）。

数据性质（已核实）
------------------
`/group3/dailyforecast/` 下**全部是人工智能方法的预报结果**，模型为 `CuboidWaveModel`
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
from typing import Any, Dict, List, Optional

import numpy as np

from orchestrator import ftp_catalog as fc

# 各数据源路径
DF = "/group3/dailyforecast"
SURGE_FIELD_DIR = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"      # atm_forecast_YYYYMMDD/
WAVE_FIELD_DIR = f"{DF}/AutoWave/res_ATM"                                   # YYYYMMDD_wave_forecast_1h.nc
WAVE_FIELD_DIR_EC = f"{DF}/AutoWave/res_EC"
TOTAL_WATER_DIR = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"      # rotated_total_water_level_*.nc
TIDE_DIR = f"{TOTAL_WATER_DIR}/tide"                                        # 站_tide_prediction_*.csv
STATION_FIELD_DIR = f"{TOTAL_WATER_DIR}/stations_nc"                        # total_water_level_field_站_*.nc
POINT_SURGE_DIR = f"{DF}/storm_surge_point_system/nc_file"
POINT_WAVE_DIR = f"{DF}/wave_for_single_point/outputs/nc_file"

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
    mx = np.nanmax(sub, axis=0)            # 每格点过程最大
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
        base = None
        if "time" in ds.variables:
            base = datetime.datetime.strptime(date, "%Y%m%d")
        src_attrs = {k: str(v)[:60] for k, v in ds.attrs.items()}
        ds.close()
    except Exception as e2:  # noqa: BLE001
        print(f"[ai_daily] 读 AI 海浪场失败: {e2}")
        return None
    return {"lat": lat, "lon": lon, "hs_m": hs, "n_times": int(hs.shape[0]),
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
# 概览
# --------------------------------------------------------------------------- #
def overview() -> Dict[str, Any]:
    """当前可用的 AI 每日预报概览（供“今天有什么预报”这类问题）。"""
    sd = list_surge_dates()
    wd = list_wave_dates()
    td = list_tide_dates()
    return {
        "surge_field_dates": sd[-6:], "surge_field_latest": sd[-1] if sd else "",
        "surge_field_n": len(sd),
        "wave_field_dates": wd[-6:], "wave_field_latest": wd[-1] if wd else "",
        "wave_field_n": len(wd),
        "tide_dates": td[-6:], "tide_latest": td[-1] if td else "", "tide_n": len(td),
        "source": "课题三 /group3/dailyforecast（人工智能方法）",
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
