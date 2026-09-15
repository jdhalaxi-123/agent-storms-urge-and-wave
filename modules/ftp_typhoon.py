# -*- coding: utf-8 -*-
"""台风期间数据取数器 —— 从 FTP 按需取数（不落地全量数据）。

用途
----
给编排引擎提供"某个台风期间的：站点增水 / 全场增水 / 天文潮 / 总水位 / 浮标波高 / 实测"
六类数据，全部按需从课题数据库（FTP）拉取，小文件优先。

数据源与体积（10 个完整台风：1513 1521 1601 1614 1617 1709 1808 2305 2311 2403）
--------------------------------------------------------------------------
    station_surge   站点纯增水      8.5 KB/天 × 4站 × 7~17天   /group3/storm_surge_point/new_wind_v2/
    wave_point      浮标波高过程    10~16 KB/站 × 16站         /group3/TC_wave_point/wave/
    surge_field     全场增水        2 MB                        /group3/storm_surge_field/
    observation     浮标实测        1.4 MB                      /group5/202609/observation/out2/
    cropped_field   天文潮+总水位   37~117 MB × 2               /group5/202609/dataset_GFS_cropped/

语义（已由官方说明文件 + 数据实测双重确认）
------------------------------------------
    cropped/ortho 场：output_0 = 潮驱动 = **天文潮**；output_4 = 风+潮驱动 = **总水位**
                      两者相减 = **风暴增水**
    irregular 网格  ：elev_tide / elev_surge / elev_all 三个变量直接对应 天文潮 / 增水 / 总水位
    课题三 场/单点  ：surge / storm_surge 直接是**纯增水**（cm）
"""
from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np

from orchestrator import ftp_catalog as fc
from orchestrator.contract import ModuleContext

# 数据完整（10/10 或 9/10）的台风
COMPLETE_TYPHOONS = ["1513", "1521", "1601", "1614", "1617", "1709", "1808", "2305", "2311", "2403"]

# 课题三单点站号 <-> 中文名 <-> 坐标（坐标同 2526 单点数据权威值）
STATIONS: Dict[str, Dict[str, Any]] = {
    "厦门": {"code": "XMN", "lon": 118.25, "lat": 24.50},
    "崇武": {"code": "CWU", "lon": 119.00, "lat": 25.00},
    "晋江": {"code": "JNJ", "lon": 118.50, "lat": 24.50},
    "东山东港": {"code": "DSN", "lon": 117.50, "lat": 23.75},
}
CODE2CN = {v["code"]: k for k, v in STATIONS.items()}

# 单个文件超过此大小就**不自动下载**（正交场 710/921 MB、波浪场 2.7 GB 等）
# —— 按需取数的前提是"秒级可得"，超大文件必须显式确认后才下。
MAX_AUTO_DOWNLOAD_MB = 150.0


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _parse_base_dt(units: str) -> Optional[datetime.datetime]:
    """解析 netCDF time 的 units，如 'hours since 2015-08-07 00:00:00'。"""
    m = re.search(r"since\s+(\d{4})-(\d{2})-(\d{2})[T ]?(\d{2})?:?(\d{2})?:?(\d{2})?", str(units))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mi = int(m.group(5) or 0)
    return datetime.datetime(y, mo, d, hh, mi)


def _time_axis(ds, base_hint: Optional[datetime.datetime] = None):
    """返回 (起始时间, 步长小时)。

    兼容三种时间编码：
      - datetime64：直接取
      - 数字 + 小时（如 'hours since 2015-08-07'）
      - 数字 + **秒**（如裁剪场 300, 3900, … 步长 3600）→ 需按秒换算；
        裁剪场没有 units 属性，此时用 base_hint（同台风的课题三场起始日期）兜底。
    """
    if "time" not in ds.variables:
        return base_hint, 1.0
    tv = np.asarray(ds["time"].values).ravel()
    if tv.size == 0:
        return base_hint, 1.0
    if np.issubdtype(tv.dtype, np.datetime64):
        t0 = tv[0].astype("datetime64[s]").item()
        step_h = 1.0
        if tv.size > 1:
            step_h = float((tv[1] - tv[0]) / np.timedelta64(1, "h"))
        return t0, step_h
    step_raw = float(tv[1] - tv[0]) if tv.size > 1 else 1.0
    is_sec = step_raw >= 60
    step_h = step_raw / 3600.0 if is_sec else step_raw
    base = _parse_base_dt(ds["time"].attrs.get("units", "")) or base_hint
    if base is None:
        return None, step_h
    offset_h = float(tv[0]) / 3600.0 if is_sec else float(tv[0])
    return base + datetime.timedelta(hours=offset_h), step_h


def _window_hint(typhoon: str) -> Optional[datetime.datetime]:
    """从课题三场文件名（storm_surge_forecast_YYYYMMDD-YYYYMMDD.nc）取起始日期作时间基准。"""
    cat = fc.catalog(typhoon)
    src = cat.get("sources", {}).get("surge_field") or {}
    for f in src.get("files", []):
        m = re.search(r"(\d{8})-(\d{8})", f.get("name", ""))
        if m:
            try:
                return datetime.datetime.strptime(m.group(1), "%Y%m%d")
            except Exception:
                pass
    return None


def _typhoon_of(request: Dict[str, Any]) -> str:
    """从槽位里取台风编号（4 位数字）。"""
    raw = str(request.get("typhoon", "") or "")
    m = re.search(r"(\d{4})", raw)
    return m.group(1) if m else ""


def is_complete(typhoon: str) -> bool:
    return str(typhoon) in COMPLETE_TYPHOONS


# --------------------------------------------------------------------------- #
# ① 站点增水（8.5 KB/天，最小；优先用它）
# --------------------------------------------------------------------------- #
def load_station_surge(typhoon: str, stations: Optional[List[str]] = None,
                       max_files_per_station: int = 40) -> List[Dict[str, Any]]:
    """读取该台风期间各站的**纯增水**逐时过程（cm）。

    每天一个文件（24 小时），拼接成完整过程。返回：
        [{"name","code","lon","lat","start_dt","series_cm","source_files"}]
    """
    import xarray as xr

    cat = fc.catalog(typhoon)
    src = cat.get("sources", {}).get("station_surge")
    if not src:
        return []
    want = stations or list(STATIONS.keys())
    out: List[Dict[str, Any]] = []
    for cn in want:
        code = STATIONS.get(cn, {}).get("code") or cn
        files = src["stations"].get(code)
        if not files:
            continue
        files = sorted(files, key=lambda x: x["date"])[:max_files_per_station]
        series: List[float] = []
        base0: Optional[datetime.datetime] = None
        used = 0
        for f in files:
            lp = fc.fetch(f["path"], expected_size=f["size"])
            if not lp:
                continue
            try:
                ds = xr.open_dataset(lp, decode_times=False)
                var = "storm_surge" if "storm_surge" in ds.variables else list(ds.data_vars)[0]
                arr = np.asarray(ds[var].values, dtype=float).ravel()
                b, _step = _time_axis(ds)
                # 文件名里的日期更可靠（time units 常是固定的 2010-01-01）
                fd = f.get("date")
                if fd:
                    try:
                        b = datetime.datetime.strptime(fd, "%Y%m%d")
                    except Exception:
                        pass
                if base0 is None:
                    base0 = b
                n = arr.size
                # 按天切片，填入对应时间位置
                if base0 and b:
                    off = int((b - base0).total_seconds() // 3600)
                    while len(series) < off:
                        series.append(float("nan"))
                    for i, v in enumerate(arr):
                        if len(series) <= off + i:
                            series.append(float(v))
                        else:
                            series[off + i] = float(v)
                else:
                    series.extend(float(v) for v in arr)
                used += 1
                ds.close()
            except Exception:
                continue
        if used and series:
            st = STATIONS.get(cn, {})
            out.append({
                "name": cn, "code": code,
                "lon": st.get("lon"), "lat": st.get("lat"),
                "start_dt": base0,
                "series_cm": [round(v, 2) if np.isfinite(v) else None for v in series],
                "source_files": used,
                "source_kind": "课题三 单点增水（每日一个文件）",
            })
    return out


# --------------------------------------------------------------------------- #
# ② 全场增水（2 MB）
# --------------------------------------------------------------------------- #
def load_surge_field(typhoon: str, target_date: Optional[datetime.date] = None) -> Optional[Dict[str, Any]]:
    """读取课题三全场增水（cm），返回最近一次预报的二维最大增水场 + 时间轴信息。"""
    import xarray as xr

    cat = fc.catalog(typhoon)
    src = cat.get("sources", {}).get("surge_field")
    if not src or not src.get("files"):
        return None
    f = sorted(src["files"], key=lambda x: x["name"])[-1]   # 取最新一次
    lp = fc.fetch(f["path"], expected_size=f["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        lat = np.asarray(ds["lat"].values, dtype=float)
        lon = np.asarray(ds["lon"].values, dtype=float)
        arr = np.asarray(ds["surge"].values, dtype=float)      # (lat, lon, time)
        base, step = _time_axis(ds)
        ds.close()
    except Exception:
        return None
    # 时间索引（可按日期过滤）
    idx = np.arange(arr.shape[2])
    if target_date is not None and base is not None and step:
        t0 = int((datetime.datetime.combine(target_date, datetime.time(0, 0)) - base).total_seconds() // 3600)
        t1 = t0 + int(24 / step)
        sel = [k for k in range(arr.shape[2]) if t0 <= k < t1]
        if sel:
            idx = np.array(sel)
    sub = arr[:, :, idx]
    with np.errstate(invalid="ignore"), np.testing.suppress_warnings() as sup:
        sup.filter(RuntimeWarning)
        mx = np.nanmax(sub, axis=2)
        if not np.isfinite(mx).any():
            mx = np.zeros(sub.shape[:2])
        per_t = np.nanmax(sub, axis=(0, 1))
    if np.isfinite(per_t).any():
        peak_hour = int(idx[int(np.nanargmax(per_t))])
    else:
        peak_hour = int(idx[0]) if len(idx) else 0
    return {
        "lat": lat, "lon": lon, "surge_max_cm": mx,
        "start_dt": base, "step_hours": step,
        "n_hours": int(arr.shape[2]),
        "peak_dt": (base + datetime.timedelta(hours=peak_hour * step)) if base else None,
        "max_cm": round(float(np.nanmax(mx)), 1),
        "source_file": f["name"], "source_kind": "课题三 全场增水 0.25°（2 MB）",
        "date_filtered": target_date.strftime("%Y-%m-%d") if target_date else "",
    }


def sample_field(field: Dict[str, Any], lon: float, lat: float) -> Dict[str, Any]:
    """在场上按最近格点采样。"""
    if not field:
        return {}
    lonv, latv = field["lon"], field["lat"]
    i = int(np.abs(lonv - lon).argmin())
    j = int(np.abs(latv - lat).argmin())
    val = float(field["surge_max_cm"][j, i])
    dist = float(np.hypot((lonv[i] - lon) * np.cos(np.radians(lat)), latv[j] - lat)) * 111.0
    return {"grid_lon": round(float(lonv[i]), 3), "grid_lat": round(float(latv[j]), 3),
            "max_surge_cm": round(val, 1) if np.isfinite(val) else None,
            "dist_km": round(dist, 1)}


# --------------------------------------------------------------------------- #
# ③ 浮标波高过程（10~16 KB/站）
# --------------------------------------------------------------------------- #
def load_wave_point(typhoon: str, stations: Optional[List[str]] = None,
                    max_stations: int = 20) -> List[Dict[str, Any]]:
    """读取浮标站波高过程（swh, m）。站号形如 46694A / C6W10。

    注意：波浪单点文件里**没有经纬度**，只有站号，因此只能按站号回答。
    """
    import xarray as xr

    cat = fc.catalog(typhoon)
    src = cat.get("sources", {}).get("wave_point")
    if not src:
        return []
    files = src.get("files", [])
    if stations:
        files = [f for f in files if f.get("station") in stations]
    out = []
    for f in files[:max_stations]:
        lp = fc.fetch(f["path"], expected_size=f["size"])
        if not lp:
            continue
        try:
            ds = xr.open_dataset(lp, decode_times=False)
            base, step = _time_axis(ds)
            row = {"station": f.get("station"), "start_dt": base, "step_hours": step,
                   "source_file": os.path.basename(lp)}
            for key, var in (("series_m", "swh"), ("period_s", "mwp"), ("dir_deg", "mwd")):
                if var in ds.variables:
                    a = np.asarray(ds[var].values, dtype=float).ravel()
                    row[key] = [round(float(v), 2) if np.isfinite(v) else None for v in a]
            ds.close()
            if row.get("series_m"):
                arr = np.asarray([v for v in row["series_m"] if v is not None], dtype=float)
                row["max_hs_m"] = round(float(arr.max()), 2) if arr.size else None
                out.append(row)
        except Exception:
            continue
    out.sort(key=lambda r: (r.get("max_hs_m") or -1), reverse=True)
    return out


def judge_wave(hs_m: float) -> str:
    for name, th in (("红色", 9.0), ("橙色", 6.0), ("黄色", 4.0), ("蓝色", 2.5)):
        if hs_m >= th:
            return name
    return "无"


# --------------------------------------------------------------------------- #
# ④ 实测观测（1.4 MB）
# --------------------------------------------------------------------------- #
def load_observation(typhoon: str) -> Optional[Dict[str, Any]]:
    """读取该台风的浮标实测（波高 wave_H / 潮位 tide_tide / 风 / 气压）。"""
    import xarray as xr

    cat = fc.catalog(typhoon)
    src = cat.get("sources", {}).get("observation_qc") or cat.get("sources", {}).get("observation_origin")
    if not src:
        return None
    lp = fc.fetch(src["path"], expected_size=src["size"])
    if not lp:
        return None
    try:
        ds = xr.open_dataset(lp, decode_times=False)
        base, step = _time_axis(ds)
        out: Dict[str, Any] = {
            "start_dt": base, "step_hours": step,
            "sta_id": [str(x) for x in np.asarray(ds["sta_id"].values).ravel()],
            "sta_id_tide": [str(x) for x in np.asarray(ds["sta_id_tide"].values).ravel()],
            "source_file": os.path.basename(lp),
            "source_kind": "课题五 浮标实测（质控后）",
        }
        for key, var in (("wave_H", "wave_H"), ("wave_T", "wave_T"), ("tide_tide", "tide_tide"),
                         ("pres_P", "pres_P"), ("wind_VM2", "wind_VM2")):
            if var in ds.variables:
                a = np.asarray(ds[var].values, dtype=float)
                out[key] = a
                with np.errstate(invalid="ignore"):
                    out[key + "_max"] = round(float(np.nanmax(a)), 2) if np.isfinite(a).any() else None
        ds.close()
        return out
    except Exception:
        return None


def _spatial_dims(da) -> tuple:
    """返回数据数组的两个空间维名（兼容 lat/lon 与 ny/nx）。"""
    dims = [d for d in da.dims if d != "time"]
    if len(dims) >= 2:
        return dims[-2], dims[-1]
    return "lat", "lon"


def _read_point(ds, var: str, lon2, lat2, lon: float, lat: float):
    """在二维网格上按最近格点取时间序列，返回 (序列, j, i, 距目标点 km)。"""
    d2 = (lon2 - lon) ** 2 + (lat2 - lat) ** 2
    j, i = np.unravel_index(int(np.argmin(d2)), d2.shape)
    da = ds[var]
    ydim, xdim = _spatial_dims(da)
    vals = da.isel({ydim: int(j), xdim: int(i)}).values
    dist = float(np.sqrt(d2[j, i])) * 111.0
    return np.asarray(vals, dtype=float).ravel(), int(j), int(i), dist


# --------------------------------------------------------------------------- #
# ⑤ 天文潮 + 总水位（裁剪场，按点采样）
# --------------------------------------------------------------------------- #
def load_tide_total(typhoon: str, points: List[Dict[str, Any]],
                    prefer: str = "cropped",
                    ref: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """从裁剪场（或正交场）读**天文潮**与**总水位**，并在指定点集上采样。

    points: [{"name": "厦门", "lon": 118.25, "lat": 24.50}, ...]
    ref:    可选的参考序列 {"series": [...], "start_dt": datetime, "name": "厦门"}
            —— 裁剪场的时间轴没有 units 属性，基准日只能猜；
            这里用"相减得到的增水"与参考站的增水序列做互相关，求出真实时移，
            把时间轴对齐到可靠的参考轴上。

    返回 {"start_dt","step_hours","points":[{..,"series_tide_cm","series_total_cm","series_surge_cm"}]}
    """
    import xarray as xr

    cat = fc.catalog(typhoon)
    s = cat.get("sources", {})
    src = s.get("cropped_field") if prefer == "cropped" else None
    src = src or s.get("cropped_field") or s.get("ortho_field")
    if not src or not src.get("tide") or not src.get("total"):
        return None
    # 超大文件（正交场 710/921 MB）不自动下载 —— 否则一次查询要等好几分钟
    biggest = max(src.get("tide_size", 0), src.get("total_size", 0)) / 1e6
    if biggest > MAX_AUTO_DOWNLOAD_MB:
        print(f"[ftp_typhoon] {typhoon} 无裁剪场，正交场单文件 {biggest:.0f} MB "
              f"超过自动下载上限 {MAX_AUTO_DOWNLOAD_MB:.0f} MB，跳过总水位判级")
        return None
    lp0 = fc.fetch(src["tide"], expected_size=src.get("tide_size", 0))
    lp4 = fc.fetch(src["total"], expected_size=src.get("total_size", 0))
    if not lp0 or not lp4:
        return None
    try:
        d0 = xr.open_dataset(lp0, decode_times=False)
        d4 = xr.open_dataset(lp4, decode_times=False)
        lon2 = np.asarray(d0["lon"].values, dtype=float)
        lat2 = np.asarray(d0["lat"].values, dtype=float)
        if lon2.ndim == 1:      # 规则一维坐标
            lon2, lat2 = np.meshgrid(lon2, lat2)
        base, step = _time_axis(d0, base_hint=_window_hint(typhoon))
        res: Dict[str, Any] = {"start_dt": base, "step_hours": step, "points": [],
                               "source_kind": "裁剪场 output_0(天文潮) + output_4(总水位)",
                               "src_paths": [os.path.basename(lp0), os.path.basename(lp4)],
                               "time_axis_reliable": False}
        for pt in points:
            a0, j, i, dist = _read_point(d0, "elev", lon2, lat2, pt["lon"], pt["lat"])
            a4, _j2, _i2, _d2 = _read_point(d4, "elev", lon2, lat2, pt["lon"], pt["lat"])
            a0 = a0 * 100.0     # m -> cm
            a4 = a4 * 100.0
            n = min(a0.size, a4.size)
            a0, a4 = a0[:n], a4[:n]
            res["points"].append({
                "name": pt.get("name", ""), "lon": pt["lon"], "lat": pt["lat"],
                "grid_lon": round(float(lon2[j, i]), 3), "grid_lat": round(float(lat2[j, i]), 3),
                "grid_dist_km": round(dist, 1),
                "series_tide_cm": [round(float(v), 1) if np.isfinite(v) else None for v in a0],
                "series_total_cm": [round(float(v), 1) if np.isfinite(v) else None for v in a4],
                "series_surge_cm": [round(float(v), 1) if np.isfinite(v) else None for v in (a4 - a0)],
            })

        # 用参考序列做互相关，校正时间基准
        if ref and ref.get("series") and res["points"]:
            best = None
            rser = np.asarray([np.nan if v is None else v for v in ref["series"]], dtype=float)
            for p in res["points"]:
                if p["name"] != ref.get("name"):
                    continue
                fser = np.asarray([np.nan if v is None else v for v in p["series_surge_cm"]], dtype=float)
                m = min(rser.size, fser.size)
                if m < 48:
                    continue
                r0, f0 = rser[:m], fser[:m]
                for lag in range(-72, 73):
                    if lag >= 0:
                        a, b = f0[lag:], r0[: m - lag]
                    else:
                        a, b = f0[: m + lag], r0[-lag:]
                    ok = np.isfinite(a) & np.isfinite(b)
                    if ok.sum() < 24:
                        continue
                    c = float(np.corrcoef(a[ok], b[ok])[0, 1])
                    if best is None or c > best[0]:
                        best = (c, lag)
            if best and best[0] > 0.5:
                _c, lag = best
                # 场的时间轴基准 = 参考序列起点 - lag 小时
                res["start_dt"] = ref["start_dt"] - datetime.timedelta(hours=lag)
                res["time_axis_reliable"] = True
                res["align_corr"] = round(float(best[0]), 3)
                res["align_lag_h"] = int(lag)

        d0.close()
        d4.close()
        return res
    except Exception as e:  # noqa: BLE001
        print(f"[ftp_typhoon] 读裁剪场失败: {e}")
        return None


# --------------------------------------------------------------------------- #
# 统一入口：按需组装某个台风的数据
# --------------------------------------------------------------------------- #
def build(typhoon: str, request: Optional[Dict[str, Any]] = None) -> ModuleContext:
    """为指定台风预取数据，写入 ctx.files / ctx.results['ftp_typhoon']。"""
    req = dict(request or {})
    req["typhoon"] = typhoon
    ctx = ModuleContext(request=req)
    info: Dict[str, Any] = {"typhoon": typhoon, "complete": is_complete(typhoon),
                            "catalog": {}, "loaded": []}
    cat = fc.catalog(typhoon)
    info["catalog"] = {k: {"note": v.get("note", ""),
                           "size_mb": round((v.get("size", 0) or v.get("total_mb", 0) * 1e6
                                             or v.get("tide_size", 0)) / 1e6, 2)}
                       for k, v in cat.get("sources", {}).items()}
    ctx.results["ftp_typhoon"] = info
    return ctx
