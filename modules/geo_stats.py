"""模块② 地理信息提取 · 站点统计。

数据源优先级（越靠前越准）：
    ① 单点站点数据（ocr_forecast / storm_surge_forecast_sp_*, 按站组织, 含权威坐标）
    ② 网格风暴潮场（elevs 细网格 → elev 粗网格, 站点最近点采样）

输出 ctx.results["geo_stats"]：
    {
        "status": "ok" | "no_data",
        "source": "station" | "grid" | "none",
        "source_file": str,
        "sites": [{"name","lon","lat","max_surge_cm","peak_idx","peak_time","series"}],
        "max_surge_cm": float,   # 全区最大站点值
        "peak_time": str, "peak_site": str,
        "series": [...], "region": str,
    }
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

import numpy as np

from orchestrator.contract import ModuleContext

# 权威站点坐标（来自 2526 单点数据 ocr_forecast 的 longitude/latitude）
SITES: Dict[str, tuple] = {
    "厦门(XMN)": (118.25, 24.50),
    "崇武(CWU)": (119.00, 25.00),
    "晋江(JNJ)": (118.50, 24.50),
    "东山东港(DSN)": (117.50, 23.75),
}

# 单点数据站名缩写 -> 中文
STATION_CN = {"XMN": "厦门", "CWU": "崇武", "JNJ": "晋江", "DSN": "东山东港"}


def _parse_start_dt(path: str) -> Optional[datetime.datetime]:
    """从文件名解析起始时间：如 ocn_forecast_20251110-20251116.nc -> 2025-11-10 00:00。"""
    import re

    m = re.search(r"(\d{8})[-_](\d{8})", os.path.basename(path))
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d")
        except Exception:
            return None
    return None

# 请求文本 -> 目标站点中文名 的别名映射
# 用于"问哪个站就画哪个站"的过滤
STATION_ALIASES = {
    "厦门": ["厦门", "厦门港", "厦门站", "xm", "xmn"],
    "崇武": ["崇武", "崇武站", "cwu"],
    "晋江": ["晋江", "晋江站", "jnj"],
    "东山东港": ["东山", "东山东港", "东山站", "东山东港站", "dsn"],
}


def _filter_sites(sites: List[Dict[str, Any]], request: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按请求中的站点名过滤站点列表（问哪个站就保留哪个站）。

    匹配依据：request 的 region 字段（如"厦门"、"厦门站"、"崇武"）。
    - 若请求明确点名某站（厦门/崇武/晋江/东山任一），只保留匹配站；
    - 若未点名（如"福建沿海"），保留全部。
    """
    text = str(request.get("region", "") or "").strip()
    # 从请求文本里找命中的站点
    hit_stations: List[str] = []
    for station, aliases in STATION_ALIASES.items():
        for a in aliases:
            if a and a.lower() in text.lower():
                hit_stations.append(station)
                break
    if not hit_stations:
        return sites  # 未点名，全部保留
    # 按站点中文名/别名过滤
    out = []
    for s in sites:
        name = str(s.get("name", ""))
        matched = False
        for st in hit_stations:
            if st in name or name in st:
                matched = True
                break
        if matched:
            out.append(s)
    return out if out else sites  # 若过滤后为空(名字不匹配)，保底返回全部

# 预警级别阈值（增水 cm）
THRESHOLDS = {"蓝色": 30.0, "黄色": 50.0, "橙色": 80.0, "红色": 120.0}


def _fmt_time(t_val: Any, base: Optional[str] = None) -> str:
    """把时间值格式化为字符串。

    支持：datetime64 / datetime / 相对小时(0~200) / matlab日序数(27000+) / 纳秒时间戳。
    """
    try:
        if hasattr(t_val, "astype") and "datetime64" in str(getattr(t_val, "dtype", "")):
            t_val = t_val.astype("datetime64[s]").item()
        elif hasattr(t_val, "item"):
            t_val = t_val.item()
        if isinstance(t_val, np.datetime64):
            t_val = t_val.astype("datetime64[s]").item()
        if isinstance(t_val, (datetime.datetime, datetime.date)):
            return t_val.strftime("%m-%d %H:%M") if isinstance(t_val, datetime.datetime) else t_val.strftime("%m-%d")
        if isinstance(t_val, (int, float)):
            v = float(t_val)
            if abs(v) < 200:  # 相对小时（0~167）
                if base:
                    return (datetime.datetime.strptime(base, "%Y-%m-%d") + datetime.timedelta(hours=v)).strftime("%m-%d %H:%M")
                return f"第{v:.0f}小时"
            if 27000 < v < 100000:  # matlab datenum 日序数
                # matlab datenum 起点 0000-01-01; 需用 delta 换算(相对 2025-11-08 已知偏移)
                # 直接按 1 天=1 换算 + 已知 27705.0=2025-11-08
                base_dt = datetime.datetime(2025, 11, 8) - datetime.timedelta(days=27705.0)
                return (base_dt + datetime.timedelta(days=v)).strftime("%m-%d %H:%M")
            if 10**17 < abs(v) < 10**19:  # 纳秒时间戳
                return datetime.datetime.fromtimestamp(v / 1e9).strftime("%m-%d %H:%M")
    except Exception:
        pass
    return str(t_val)


# --------------------------------------------------------------------------- #
# ① 单点数据读取
# --------------------------------------------------------------------------- #
# 只读"当前台风"的单点文件：排除历史台风目录与 _new 后缀重复文件
def _pick_station_files(paths: List[str], typhoon: str = "") -> List[str]:
    """选出当前台风的主单点文件（优先 ocn_forecast / storm_surge_stations）。"""
    if not paths:
        return []
    # 优先级：文件名含 ocn_forecast > storm_surge_stations > storm_surge_forecast_sp
    def rank(p: str) -> int:
        base = os.path.basename(p).lower()
        if "_new" in base:
            return 30  # 排除 _new 重复
        if "ocn_forecast" in base:
            return 0
        if "storm_surge_stations" in base:
            return 1
        if "storm_surge_forecast_sp" in base:
            return 2
        return 10
    if typhoon:
        # 只保留当前台风目录下的
        tp = [p for p in paths if typhoon in p.replace("\\", "/")]
        if tp:
            paths = tp
    return sorted(paths, key=rank)[:3]


def _read_station_data(paths: List[str]) -> List[Dict[str, Any]]:
    """从单点 NC(ocr_forecast/sp_*) 读站点序列（主文件优先）。"""
    import xarray as xr

    results: List[Dict[str, Any]] = []
    for path in paths[:1]:  # 只读第一优先级的主文件，避免多文件混读
        try:
            ds = xr.open_dataset(path, decode_times=False)
        except Exception:
            continue
        try:
            var = "surge" if "surge" in ds.variables else ("storm_surge" if "storm_surge" in ds.variables else None)
            if var is None:
                continue
            data = ds[var].values
            multi = data.ndim == 2
            stations = list(ds["station"].values) if multi and "station" in ds.coords else []
            lons = ds["longitude"].values if "longitude" in ds.variables else None
            lats = ds["latitude"].values if "latitude" in ds.variables else None
            if not multi:
                lon = float(np.asarray(ds["longitude"].values).ravel()[0]) if "longitude" in ds.variables else None
                lat = float(np.asarray(ds["latitude"].values).ravel()[0]) if "latitude" in ds.variables else None
                import re
                m = re.search(r"sp_([A-Z]+)", path)
                code = m.group(1) if m else "ST"
                results.append({
                    "name": STATION_CN.get(code, code), "code": code,
                    "lon": lon, "lat": lat,
                    "series_cm": np.asarray(data).ravel().tolist(),
                    "start_dt": _parse_start_dt(path),
                    "source_file": str(path),
                })
            else:
                for i, st in enumerate(stations):
                    code = str(st).strip() if not isinstance(st, (list, np.ndarray)) else str(np.asarray(st).item())
                    lo = float(np.asarray(lons[i])) if lons is not None and i < len(lons) else None
                    la = float(np.asarray(lats[i])) if lats is not None and i < len(lats) else None
                    results.append({
                        "name": STATION_CN.get(code, code), "code": code,
                        "lon": lo, "lat": la,
                        "series_cm": np.asarray(data[:, i]).ravel().tolist(),
                        "start_dt": _parse_start_dt(path),
                        "source_file": str(path),
                    })
            ds.close()
        except Exception:
            try:
                ds.close()
            except Exception:
                pass
            continue
    return results


def _merge_stations(stations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并同名站点（多文件/多时次取数据最长者）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for s in stations:
        key = s.get("code") or s.get("name")
        if key not in merged or len(s["series_cm"]) > len(merged[key]["series_cm"]):
            merged[key] = s
    return list(merged.values())


# --------------------------------------------------------------------------- #
# ② 网格数据读取
# --------------------------------------------------------------------------- #
def _read_grid_data(path: str) -> List[Dict[str, Any]]:
    import xarray as xr

    try:
        ds = xr.open_dataset(path)
    except Exception:
        return []
    try:
        var = "elevs" if "elevs" in ds.variables else ("elev" if "elev" in ds.variables else None)
        if var is None:
            return []
        time = ds["time"].values if "time" in ds.coords else None
        sites = []
        for name, (lon_p, lat_p) in SITES.items():
            try:
                ts = _sample_at(ds, var, lon_p, lat_p)
                valid = np.asarray(ts)[~np.isnan(np.asarray(ts, dtype=float))]
                if len(valid) == 0:
                    continue
                peak = int(np.nanargmax(np.asarray(ts, dtype=float)))
                peak_time = _fmt_time(time[peak]) if time is not None else ""
                sites.append({
                    "name": name, "code": "", "lon": lon_p, "lat": lat_p,
                    "max_surge_cm": round(float(np.nanmax(valid)) * 100.0, 1),
                    "peak_idx": peak, "peak_time": peak_time,
                    "series_cm": [round(float(v) * 100.0, 1) for v in np.asarray(ts, dtype=float)[:: max(1, len(ts) // 30)]],
                    "source_file": str(path),
                })
            except Exception:
                continue
        return sites
    finally:
        ds.close()


def _sample_at(ds, var: str, lon_pt: float, lat_pt: float) -> np.ndarray:
    """在 2D 网格(lons/lats)上取最近点的时间序列。"""
    lons = ds["lons"].values if "lons" in ds.coords or "lons" in ds.variables else None
    lats = ds["lats"].values if "lats" in ds.coords or "lats" in ds.variables else None
    if lons is None or lats is None:
        # 粗网格：1D 坐标
        lon_1d = ds["lon"].values
        lat_1d = ds["lat"].values
        i = int(np.abs(lon_1d - lon_pt).argmin())
        j = int(np.abs(lat_1d - lat_pt).argmin())
        return ds[var].isel(lat=j, lon=i).values
    d2 = (lons - lon_pt) ** 2 + (lats - lat_pt) ** 2
    j, i = np.unravel_index(int(np.argmin(d2)), d2.shape)
    if "lats" in ds[var].dims:
        return ds[var].isel(lats=j, lons=i).values
    return ds[var].isel(lat=j, lon=i).values


def _finalize(sites: List[Dict[str, Any]], region: str, source: str, source_file: str, hours: Optional[int] = None) -> Dict[str, Any]:
    """汇总统计。hours: 时间窗小时数(截取后)。"""
    if not sites:
        return {"status": "no_data", "source": "none", "sites": [], "series": []}
    # 从文件名推断起始日期（如 ocn_forecast_20251110-20251116.nc -> 2025-11-10 00:00）
    base_dt = None
    import re
    m = re.search(r"(\d{8})-(\d{8})", os.path.basename(source_file))
    if m:
        try:
            base_dt = datetime.datetime.strptime(m.group(1), "%Y%m%d")
        except Exception:
            base_dt = None
    for s in sites:
        if "series_cm" in s and s.get("max_surge_cm") is None:
            arr = np.asarray(s["series_cm"], dtype=float)
            if len(arr):
                s["max_surge_cm"] = round(float(np.nanmax(arr)), 1)
                peak = int(np.nanargmax(arr))
                s["peak_idx"] = peak
                # 峰值时间：优先 start_dt(文件名起始) + 时次
                base_dt2 = s.get("start_dt") or base_dt
                if base_dt2:
                    peak_dt = base_dt2 + datetime.timedelta(hours=peak)
                    s["peak_time"] = peak_dt.strftime("%m-%d %H:%M")
                    s["peak_date"] = peak_dt.strftime("%Y-%m-%d")
                else:
                    s["peak_time"] = f"第{peak}时次"
                s["series"] = arr.tolist()
                s["series_full"] = arr.tolist()  # 完整序列(画图用)
    top = max(sites, key=lambda s: s.get("max_surge_cm", -1e9))
    # 站点序列(统一30点降采样; 完整序列保留在 series_full)
    for s in sites:
        arr = np.asarray(s.get("series_cm") or s.get("series") or [], dtype=float)
        if len(arr):
            s["series"] = arr[:: max(1, len(arr) // 30)].round(1).tolist()

    # 数据真实起止时间（用于简报标注；来自文件名起始 + 序列长度）
    data_start = data_end = ""
    if sites:
        s0 = sites[0]
        st = s0.get("start_dt") or base_dt
        full = s0.get("series_full") or s0.get("series_cm") or []
        if st:
            data_start = st.strftime("%Y-%m-%d %H:%M")
            if full:
                data_end = (st + datetime.timedelta(hours=len(full) - 1)).strftime("%Y-%m-%d %H:%M")
            else:
                data_end = st.strftime("%Y-%m-%d %H:%M")
    return {
        "status": "ok",
        "source": source,
        "source_file": source_file,
        "region": region,
        "time_window_hours": hours,
        "data_start": data_start,
        "data_end": data_end,
        "sites": sites,
        "max_surge_cm": top.get("max_surge_cm", 0.0),
        "peak_time": top.get("peak_time", ""),
        "peak_date": top.get("peak_date", ""),
        "peak_site": top.get("name", ""),
        "series": sites[0].get("series", []),
        "site_count": len(sites),
    }


def _parse_window_hours(tw: str) -> Optional[int]:
    """从 time_window 字符串解析小时数，如 '未来5天'/'3天'/'72小时'->72。"""
    if not tw:
        return None
    import re
    m = re.search(r"(\d+)\s*(天|日|d|h|小时)", str(tw))
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ("天", "日", "d"):
        return n * 24
    return n  # 小时


def run(ctx: ModuleContext) -> ModuleContext:
    region = ctx.request.get("region", "未知海域")
    typhoon = ctx.results.get("meta", {}).get("typhoon", "") or ""
    hours = _parse_window_hours(ctx.request.get("time_window", ""))

    # ① 单点数据优先（只取当前台风的主文件）
    paths = _pick_station_files(ctx.files.get("station_files") or [], typhoon)
    sites = _read_station_data(paths) if paths else []
    if sites:
        # 按请求站点过滤（问厦门就只画厦门）
        sites = _filter_sites(sites, ctx.request)
        ctx.results["geo_stats"] = _finalize(sites, region, "station", paths[0] if paths else "", hours)
        _attach_wave(ctx)
        return ctx

    # ② 网格数据兜底
    grid_path = ctx.files.get("nc_forecast_num") or (ctx.files.get("surge_files") or [None])[0]
    if grid_path:
        sites = _read_grid_data(grid_path)
        if sites:
            sites = _filter_sites(sites, ctx.request)
            ctx.results["geo_stats"] = _finalize(sites, region, "grid", grid_path, hours)
            _attach_wave(ctx)
            return ctx

    ctx.results["geo_stats"] = {"status": "no_data", "source": "none", "sites": [], "series": []}
    _attach_wave(ctx)
    return ctx


def _attach_wave(ctx: ModuleContext) -> None:
    """附加海浪统计到 ctx.results["wave_stats"]（带时间窗截取）。"""
    try:
        hours = _parse_window_hours(ctx.request.get("time_window", ""))
        ctx.results["wave_stats"] = run_wave(ctx, hours)
    except Exception:
        ctx.results["wave_stats"] = {"status": "no_data", "series": []}


# --------------------------------------------------------------------------- #
# 海浪统计（独立入口：wave_stats）
# --------------------------------------------------------------------------- #
WAVE_LEVELS = [("红色", 9.0), ("橙色", 6.0), ("黄色", 4.0), ("蓝色", 2.5)]

# 重点关注海域（厦门附近）
WAVE_BOX = (118.00, 118.40, 24.30, 24.60)


def judge_wave(hs_m: float) -> str:
    """按有效波高判级。"""
    for name, th in WAVE_LEVELS:
        if hs_m >= th:
            return name
    return "无"


def run_wave(ctx: ModuleContext, hours: Optional[int] = None) -> Dict[str, Any]:
    """海浪统计：扫描 M1/R1 海浪文件，采样目标海域最大波高（可按时间窗截取）。"""
    import xarray as xr

    paths = ctx.files.get("wave_files") or []
    if not paths:
        return {"status": "no_data", "series": []}

    # 优先 M1（细网格,厦门附近），否则 R1
    m1 = [p for p in paths if "M1" in os.path.basename(p)]
    r1 = [p for p in paths if "R1" in os.path.basename(p)]
    chosen = sorted(m1) or sorted(r1)
    if not chosen:
        return {"status": "no_data", "series": []}

    # 按时间窗取需要的日文件数(每天24h)
    need_files = max(1, -(-(hours or 24) // 24)) if hours else len(chosen)
    chosen = chosen[:need_files]

    # 拼接各文件逐时最大序列
    full_series: List[float] = []
    for p in chosen:
        try:
            ds = xr.open_dataset(p, decode_times=False)
        except Exception:
            continue
        try:
            hs = ds["hs"].values
            alon = ds["alon"].values if "alon" in ds.variables else ds["lon"].values
            alat = ds["alat"].values if "alat" in ds.variables else ds["lat"].values
            if np.asarray(alon).ndim == 1:
                mask = ((alon >= WAVE_BOX[0]) & (alon <= WAVE_BOX[1]))[:, None] & \
                       ((alat >= WAVE_BOX[2]) & (alat <= WAVE_BOX[3]))[None, :]
                sel = hs[:, mask]
            else:
                mask = (alon >= WAVE_BOX[0]) & (alon <= WAVE_BOX[1]) & (alat >= WAVE_BOX[2]) & (alat <= WAVE_BOX[3])
                sel = hs[:, mask]
            daily = np.nanmax(sel, axis=1)
            valid = daily[~np.isnan(daily)]
            if len(valid):
                full_series.extend(float(v) for v in valid)
        finally:
            ds.close()

    if hours:
        full_series = full_series[: hours]
    if not full_series:
        return {"status": "no_data", "series": []}

    arr = np.asarray(full_series, dtype=float)
    best = {
        "file": str(chosen[0]) if chosen else "",
        "max_hs_m": round(float(np.nanmax(arr)), 2),
        "peak_idx": int(np.nanargmax(arr)),
        "series_m": [round(float(v), 2) for v in arr[:: max(1, len(arr) // 30)]],
        "hours": hours,
    }
    level = judge_wave(best["max_hs_m"])
    return {
        "status": "ok",
        "source": "M1" if m1 else "R1",
        "file": best["file"],
        "max_hs_m": best["max_hs_m"],
        "level": level,
        "peak_time": f"第{best['peak_idx']}时次",
        "series": best["series_m"],
        "time_window_hours": hours,
    }
