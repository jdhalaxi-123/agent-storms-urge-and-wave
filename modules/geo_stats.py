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
from typing import Any, Dict, List, Optional, Tuple

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


def _parse_target_date(date_str: str) -> Optional[datetime.date]:
    """解析目标日期：'7月22日' / '2024-07-22' / '07-22' / '2024年7月22日' -> date。"""
    import re

    s = str(date_str or "").strip()
    if not s or s in ("未指定", "无", "全部", "全程"):
        return None
    # 2024-07-22 / 2024/07/22 / 2024年7月22日
    m = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    # 月日（无年份：07-22 / 7月22日）
    m2 = re.search(r"(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?", s)
    if m2:
        # 年份未知，用数据起止年份推断（用2000年占位，由调用方补充）
        return datetime.date(2000, int(m2.group(1)), int(m2.group(2)))
    return None


def _slice_by_date(sites: List[Dict[str, Any]], target_date: datetime.date) -> List[Dict[str, Any]]:
    """按目标日期截取站点序列（保留该日期所在时次）。

    用各站点 start_dt 推算时次与目标日期的对应关系；
    目标日期在序列范围内则截取，否则保留原序列（日期可能超出数据范围）。
    """
    for s in sites:
        st = s.get("start_dt")
        full = s.get("series_full") or s.get("series_cm") or []
        if not st or not full:
            continue
        # 若 target_date 年份为2000(月日占位), 用 st.year 补全
        if target_date.year == 2000:
            try:
                target_date = target_date.replace(year=st.year)
            except Exception:
                pass
        # 计算目标日期对应的时次索引 [start,end)
        day_start = datetime.datetime.combine(target_date, datetime.time(0, 0))
        day_end = day_start + datetime.timedelta(days=1)
        idx0 = int((day_start - st).total_seconds() // 3600)
        idx1 = int((day_end - st).total_seconds() // 3600)
        if idx0 < 0:
            idx0 = 0
        if idx1 > len(full):
            idx1 = len(full)
        if idx0 < idx1:
            s["series_cm"] = full[idx0:idx1]
        # 更新 start_dt 为该日 00:00（画图时间轴/数据范围跟随）
        s["start_dt"] = day_start.replace(tzinfo=None)
    return sites

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


def _mesh_index(ds) -> Dict[str, Any]:
    """非结构三角网格索引信息。

    - npts   节点数（lon/lat/depth 所在维度）
    - nfaces 三角形数（tri 行数）
    - lookup 节点 -> 相邻三角形 的查找表（用于读取"面中心"变量，如 Ensemble）
    """
    npts = int(np.asarray(ds["lon"].values).ravel().size)
    nfaces = 0
    lookup = None
    if "tri" in ds.variables:
        tri = np.asarray(ds["tri"].values)
        if tri.ndim == 2 and tri.shape[1] == 3:
            tri0 = tri.astype(np.int64) - 1          # 1-based -> 0-based
            tri0 = np.clip(tri0, 0, npts - 1)
            nfaces = int(tri0.shape[0])
            node_of = tri0.ravel()
            face_of = np.repeat(np.arange(nfaces), 3)
            order = np.argsort(node_of, kind="stable")
            lookup = (node_of[order], face_of[order])
    return {"npts": npts, "nfaces": nfaces, "lookup": lookup}


def _faces_of_node(idx: Dict[str, Any], k: int) -> Optional[np.ndarray]:
    """节点 k 的相邻三角形编号。"""
    lk = idx.get("lookup")
    if lk is None:
        return None
    node_s, face_s = lk
    lo = int(np.searchsorted(node_s, k, side="left"))
    hi = int(np.searchsorted(node_s, k, side="right"))
    if hi <= lo:
        return None
    return face_s[lo:hi]


def _fill_gaps(arr: np.ndarray) -> np.ndarray:
    """线性插值填补序列中的 NaN（首尾用最近有效值），避免曲线断点/标注为 nan。"""
    a = np.asarray(arr, dtype=float).ravel()
    if a.size == 0:
        return a
    good = np.isfinite(a)
    if good.all():
        return a
    if not good.any():
        return np.nan_to_num(a, nan=0.0)
    idx = np.arange(a.size)
    a = a.copy()
    a[~good] = np.interp(idx[~good], idx[good], a[good])
    return a


def _mesh_series(ds, var: str, k: int, idx: Dict[str, Any]) -> np.ndarray:
    """取非结构网格上节点 k 的时间序列（单位: m）。

    自动识别三种排布（只按需切片，避免整场读入内存）：
        (npts, time)   节点中心
        (time, npts)   节点中心（转置）
        (nfaces, time) 面中心 → 取该节点相邻面平均
    """
    if var not in ds.variables:
        return np.asarray([])
    a = ds[var]
    if a.ndim == 1:
        return np.asarray(a.values, dtype=float).ravel()
    dims = a.dims
    npts = idx["npts"]
    if int(a.shape[0]) == npts:
        return np.asarray(a.isel({dims[0]: int(k)}).values, dtype=float).ravel()
    if int(a.shape[-1]) == npts:
        return np.asarray(a.isel({dims[-1]: int(k)}).values, dtype=float).ravel()
    if int(a.shape[0]) == idx["nfaces"]:
        faces = _faces_of_node(idx, int(k))
        if faces is None or faces.size == 0:
            return np.asarray([])
        sub = np.asarray(a.isel({dims[0]: faces}).values, dtype=float)
        if sub.ndim == 1:
            return sub.ravel()
        with np.errstate(invalid="ignore"):
            s = np.nanmean(sub, axis=0)
        return _fill_gaps(np.asarray(s, dtype=float).ravel())
    return np.asarray([])


def _read_ensemble_sites(path: str) -> List[Dict[str, Any]]:
    """从 Ensemble 集合文件（非结构网格: lon/lat 节点 70775, tri 三角形）按最近节点采样站点。

    变量：elev_all(总水位) / elev_surge(增水) / elev_tide(天文潮)，单位 m；
    站点输出三量序列（cm）：series_all / series_surge / series_tide。
    注意：Ensemble 文件的水位是"面中心"量（nfaces=133431），需按相邻面平均取节点值。
    """
    import xarray as xr

    try:
        ds = xr.open_dataset(path, decode_times=True)
    except Exception:
        return []

    try:
        # 变量名兼容（ensemble_elev_* / elev_*）
        all_var = "elev_all" if "elev_all" in ds.variables else ("ensemble_elev_all" if "ensemble_elev_all" in ds.variables else None)
        surge_var = "elev_surge" if "elev_surge" in ds.variables else ("ensemble_elev_surge" if "ensemble_elev_surge" in ds.variables else None)
        tide_var = "elev_tide" if "elev_tide" in ds.variables else ("ensemble_elev_tide" if "ensemble_elev_tide" in ds.variables else None)
        if all_var is None:
            return []
        lon = np.asarray(ds["lon"].values).ravel()
        lat = np.asarray(ds["lat"].values).ravel()
        idx = _mesh_index(ds)
        time = ds["time"].values
        start_dt = pd_to_dt(time[0]) if len(time) else None

        sites = []
        for name, (lon_pt, lat_pt) in SITES.items():
            d2 = (lon - lon_pt) ** 2 + (lat - lat_pt) ** 2
            idx_n = int(np.argmin(d2))
            row = {
                "name": name, "code": name.split("(")[-1].rstrip(")"),
                "lon": float(lon[idx_n]), "lat": float(lat[idx_n]),
                "start_dt": start_dt,
                "source_file": str(path),
            }
            for key, var in [("series_all", all_var), ("series_surge", surge_var), ("series_tide", tide_var)]:
                if var is None:
                    continue
                s = _mesh_series(ds, var, idx_n, idx)
                if s.size:
                    row[key] = (s * 100.0).round(2).tolist()  # m -> cm
            # 站点主序列: 有 all 用 all(总水位), 否则 surge
            row["series_cm"] = row.get("series_all") or row.get("series_surge")
            if not row["series_cm"]:
                continue
            sites.append(row)
        ds.close()
        return sites
    except Exception:
        try:
            ds.close()
        except Exception:
            pass
        return []


def pd_to_dt(v):
    """numpy.datetime64 -> datetime.datetime"""
    import datetime as _dt
    try:
        if hasattr(v, "astype"):
            v = v.astype("datetime64[s]").item()
        return v if isinstance(v, _dt.datetime) else None
    except Exception:
        return None


def _merge_stations(stations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """合并同名站点（多文件/多时次取数据最长者）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    for s in stations:
        key = s.get("code") or s.get("name")
        if key not in merged or len(s["series_cm"]) > len(merged[key]["series_cm"]):
            merged[key] = s
    return list(merged.values())


# --------------------------------------------------------------------------- #
# ③ 任意经纬度采样（用户点名覆盖区内的任意地点，或直接给经纬度）
# --------------------------------------------------------------------------- #
def _point_from_request(request: Dict[str, Any]) -> Optional[Tuple[float, float, str, str]]:
    """从槽位读取目标点，返回 (lon, lat, 标签, 简称) 或 None。"""
    pt = request.get("point")
    lon = lat = None
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        try:
            lon, lat = float(pt[0]), float(pt[1])
        except (TypeError, ValueError):
            lon = lat = None
    if lon is None or lat is None:
        return None
    name = str(request.get("point_name", "") or "").strip()
    label = f"{name}({lon:.2f}°E,{lat:.2f}°N)" if name else f"({lon:.2f}°E,{lat:.2f}°N)"
    return lon, lat, label, name


def _read_mesh_point(ctx: ModuleContext, path: str, lon_pt: float, lat_pt: float,
                     label: str, short: str = "") -> List[Dict[str, Any]]:
    """非结构三角网格（Ensemble / FTP *_surge.nc）任意点采样：取最近"湿节点"。

    - 节点筛选：depth > 0（排除陆地/干出节点），并按距离由近及远逐个验证序列有效性
    - 增水 = elev_surge（有则用），否则 elev_all - elev_tide
    - 返回单站点行（series_cm 为增水，另带 series_all / series_tide 参照）
    """
    import xarray as xr

    try:
        ds = xr.open_dataset(path, decode_times=True)
    except Exception:
        return []

    try:
        if "lon" not in ds.variables or "lat" not in ds.variables:
            return []
        lon = np.asarray(ds["lon"].values).ravel()
        lat = np.asarray(ds["lat"].values).ravel()
        if lon.size < 10:
            return []
        all_var = "elev_all" if "elev_all" in ds.variables else None
        surge_var = "elev_surge" if "elev_surge" in ds.variables else None
        tide_var = "elev_tide" if "elev_tide" in ds.variables else None
        if all_var is None and surge_var is None:
            return []
        midx = _mesh_index(ds)

        d2 = (lon - lon_pt) ** 2 + (lat - lat_pt) ** 2
        if "depth" in ds.variables:
            depth = np.asarray(ds["depth"].values).ravel()
            if depth.size == d2.size and (depth > 0).any():
                d2 = np.where(depth > 0, d2, np.inf)

        # 有效性判据：节点要有真实的潮位/水位幅度（排除河口内/边界上"数值≈0"的假节点）；
        # 取最近 3 个有效节点做中位数，避免个别近岸浅水格点的孤立异常值
        use_tide = tide_var is not None
        thr = 0.3 if (use_tide or all_var is not None) else 0.05   # 单位 m
        order = np.argsort(d2)
        picks: List[int] = []
        for cand in order[:80]:
            cand = int(cand)
            if not np.isfinite(d2[cand]):
                continue
            probe_var = tide_var if use_tide else (all_var or surge_var)
            probe = _mesh_series(ds, probe_var, cand, midx)
            fin = probe[np.isfinite(probe)]
            if fin.size and float(np.nanmax(np.abs(fin))) > thr:
                picks.append(cand)
                if len(picks) >= 3:
                    break
        if not picks:
            return []
        k = picks[0]

        start_dt = _time0_dt(ds, path, _base_date_hint(ctx, path))
        row: Dict[str, Any] = {
            "name": label,
            "short": short or label,
            "code": "PT",
            "lon": round(float(lon_pt), 3), "lat": round(float(lat_pt), 3),
            "grid_lon": round(float(lon[k]), 3), "grid_lat": round(float(lat[k]), 3),
            "grid_dist_km": round(float(np.sqrt(d2[k])) * 111.0, 1),
            "grid_nodes": len(picks),
            "start_dt": start_dt,
            "source_file": str(path),
        }
        for key, var in [("series_all", all_var), ("series_surge", surge_var), ("series_tide", tide_var)]:
            if var is None:
                continue
            cols = [_mesh_series(ds, var, kk, midx) for kk in picks]
            cols = [c for c in cols if c.size]
            if not cols:
                continue
            n = min(len(c) for c in cols)
            if n == 0:
                continue
            with np.errstate(invalid="ignore"):
                s = np.nanmedian(np.vstack([c[:n] for c in cols]), axis=0)
            row[key] = _fill_gaps(np.asarray(s, dtype=float) * 100.0).round(2).tolist()  # m -> cm
        # 增水序列：优先 elev_surge，否则 all - tide
        surge = row.get("series_surge")
        if not surge and row.get("series_all") and row.get("series_tide"):
            a = np.asarray(row["series_all"], dtype=float)
            t = np.asarray(row["series_tide"], dtype=float)
            n = min(len(a), len(t))
            surge = (a[:n] - t[:n]).round(2).tolist()
        row["series_cm"] = surge or row.get("series_all") or []
        ds.close()
        return [row] if row["series_cm"] else []
    except Exception:
        try:
            ds.close()
        except Exception:
            pass
        return []


_GRID_META_CACHE: Dict[str, Any] = {}


def _grid_meta(path: str):
    """读取结构化网格的坐标/深度，返回"图层"列表（带缓存）。

    同一文件可能有多层网格（如 2526 output_0：粗网格 elev + 厦门细网格 elevs），
    每层形如 {"var","lon","lat","depth","extent","res"}，由调用方挑选合适的一层。
    """
    key = str(path)
    if key in _GRID_META_CACHE:
        return _GRID_META_CACHE[key]
    import xarray as xr

    layers: List[Dict[str, Any]] = []
    try:
        ds = xr.open_dataset(path, decode_times=True)
    except Exception:
        try:
            ds = xr.open_dataset(path, decode_times=False)
        except Exception:
            _GRID_META_CACHE[key] = []
            return []
    try:
        has_time = ("time" in ds.dims) or ("time" in ds.coords) or ("time" in ds.variables)
        if not has_time:
            layers = []
        else:
            # 图层候选：(变量, 经度名, 纬度名, 深度名)
            cands = [
                ("elevs", "lons", "lats", "depths"),   # 嵌套细网格（厦门附近）
                ("elev", "lon", "lat", "depth"),       # 粗网格
            ]
            for var, ln, lt, dn in cands:
                if var not in ds.variables:
                    continue
                lonv = ds[ln].values if ln in ds.variables else None
                latv = ds[lt].values if lt in ds.variables else None
                if lonv is None or latv is None:
                    continue
                lonv = np.asarray(lonv, dtype=float)
                latv = np.asarray(latv, dtype=float)
                if lonv.shape != latv.shape or lonv.ndim != 2:
                    continue
                dep = np.asarray(ds[dn].values, dtype=float) if dn in ds.variables else None
                if dep is not None and dep.shape != lonv.shape:
                    dep = None
                layers.append({
                    "var": var, "lon": lonv, "lat": latv, "depth": dep,
                    "extent": (float(np.nanmin(lonv)), float(np.nanmax(lonv)),
                               float(np.nanmin(latv)), float(np.nanmax(latv))),
                    "res": float(np.nanmean(np.abs(np.diff(lonv, axis=1)))) if lonv.shape[1] > 1 else 1.0,
                })
    except Exception:
        layers = []
    finally:
        try:
            ds.close()
        except Exception:
            pass
    _GRID_META_CACHE[key] = layers
    return layers


def _pick_layer(layers: List[Dict[str, Any]], lon_pt: float, lat_pt: float) -> Optional[Dict[str, Any]]:
    """挑最合适的一层：优先"包含该点且分辨率最高"的图层，否则取范围最近的一层。"""
    if not layers:
        return None
    inside = [L for L in layers
              if L["extent"][0] <= lon_pt <= L["extent"][1] and L["extent"][2] <= lat_pt <= L["extent"][3]]
    if inside:
        return min(inside, key=lambda L: L["res"])
    def _dist(L):
        e = L["extent"]
        dx = max(e[0] - lon_pt, 0.0, lon_pt - e[1])
        dy = max(e[2] - lat_pt, 0.0, lat_pt - e[3])
        return dx * dx + dy * dy
    return min(layers, key=_dist)


def _base_date_hint(ctx: ModuleContext, path: str) -> Optional[datetime.date]:
    """推断无时间戳文件（如 output_0.nc）的起始日期。

    优先文件名自带日期；否则取同台风其他带日期文件中最早的日期。
    注意排除 atm_forecast 这类"模式大气强迫"文件——它的起报时间早于
    风暴潮场文件的预报时段，会把基准日拉偏。
    """
    import re as _re

    m = _re.search(r"(20\d{2})(\d{2})(\d{2})", os.path.basename(str(path)))
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    dates: List[datetime.date] = []
    for key in ("wind_files", "wave_files", "station_files", "surge_files", "ensemble_files"):
        for p in (ctx.files.get(key) or []):
            base = os.path.basename(str(p))
            if "atm_forecast" in base.lower() or "forcing" in base.lower():
                continue
            mm = _re.search(r"(20\d{2})(\d{2})(\d{2})", base)
            if not mm:
                continue
            try:
                dates.append(datetime.date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3))))
            except Exception:
                continue
    return min(dates) if dates else None


def _time0_dt(ds, path: str, base_date: Optional[datetime.date]) -> Optional[datetime.datetime]:
    """数据集时间轴起点，兼容三种编码：
      - datetime64：直接取首值
      - 数值 + 秒（如 2526 output_0：300, 3900, … 步长3600秒）→ 基准日 + 秒
      - 数值 + 小时（如 0,1,2…）→ 基准日 + 小时
    """
    import re as _re

    if "time" not in ds.variables and "time" not in ds.coords:
        return None
    tv = np.asarray(ds["time"].values).ravel()
    if tv.size == 0:
        return None
    if np.issubdtype(tv.dtype, np.datetime64):
        return pd_to_dt(tv[0])
    try:
        v0 = float(tv[0])
        step = float(tv[1] - tv[0]) if tv.size > 1 else 3600.0
    except (TypeError, ValueError):
        return None
    base = base_date
    if base is None:
        m = _re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", os.path.basename(str(path)))
        if m:
            try:
                base = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                base = None
    if base is None:
        return None
    base_dt = datetime.datetime.combine(base, datetime.time(0, 0))
    if step >= 60:      # 秒
        return base_dt + datetime.timedelta(seconds=v0)
    return base_dt + datetime.timedelta(hours=v0)


def _read_grid_point(ctx: ModuleContext, path: str, lon_pt: float, lat_pt: float,
                     label: str, short: str = "") -> List[Dict[str, Any]]:
    """结构化网格（output_0/4 等）任意点采样：取最近"有效格点"。

    有效 = depth>0（陆地/未计算区 depth=0）且该格点时间序列有真实变化（量级 > 0.5cm）。
    多层网格时优先"包含该点、分辨率最高"的一层。
    """
    import xarray as xr

    layers = _grid_meta(path)
    if not layers:
        return []
    layer = _pick_layer(layers, lon_pt, lat_pt)
    if layer is None:
        return []
    try:
        ds = xr.open_dataset(path, decode_times=True)
    except Exception:
        try:
            ds = xr.open_dataset(path, decode_times=False)
        except Exception:
            return []
    try:
        lon2, lat2, dep = layer["lon"], layer["lat"], layer["depth"]
        d2 = (lon2 - lon_pt) ** 2 + (lat2 - lat_pt) ** 2
        if dep is not None and dep.size == d2.size:
            d2 = np.where(dep > 0, d2, np.inf)

        arr = ds[layer["var"]]
        dims = arr.dims
        flat = d2.ravel()
        picks: List[int] = []

        def _at(cand: int) -> Optional[np.ndarray]:
            jj, ii = np.unravel_index(int(cand), d2.shape)
            try:
                if "lat" in dims and "lon" in dims:
                    return np.asarray(arr.isel(lat=int(jj), lon=int(ii)).values, dtype=float).ravel()
                if dims[0] == "time":
                    return np.asarray(arr.isel(time=slice(None))[..., int(jj), int(ii)].values, dtype=float).ravel()
            except Exception:
                return None
            return None

        # 取最近 3 个"有效格点"（有真实变化量级）做中位数，抑制孤立异常格点
        for cand in np.argsort(flat)[:120]:
            cand = int(cand)
            if not np.isfinite(flat[cand]):
                continue
            ts = _at(cand)
            if ts is None:
                continue
            fin = ts[np.isfinite(ts)]
            if fin.size and float(np.nanmax(np.abs(fin))) > 5e-3:   # > 0.5 cm
                picks.append(cand)
                if len(picks) >= 3:
                    break
        if not picks:
            return []
        cand0 = picks[0]
        j, i = np.unravel_index(cand0, d2.shape)
        cols = [c for c in (_at(c2) for c2 in picks) if c is not None and c.size]
        n = min(len(c) for c in cols)
        with np.errstate(invalid="ignore"):
            series = np.nanmedian(np.vstack([c[:n] for c in cols]), axis=0)
        series = _fill_gaps(np.asarray(series, dtype=float))

        start_dt = _time0_dt(ds, path, _base_date_hint(ctx, path))
        depth_v = float(dep[j, i]) if (dep is not None and dep.size == d2.size) else None
        row: Dict[str, Any] = {
            "name": label,
            "short": short or label,
            "code": "PT",
            "lon": round(float(lon_pt), 3), "lat": round(float(lat_pt), 3),
            "grid_lon": round(float(lon2[j, i]), 3), "grid_lat": round(float(lat2[j, i]), 3),
            "grid_dist_km": round(float(np.sqrt((lon2[j, i] - lon_pt) ** 2 + (lat2[j, i] - lat_pt) ** 2)) * 111.0, 1),
            "grid_depth_m": round(depth_v, 1) if depth_v is not None else None,
            "grid_layer": layer["var"],
            "grid_nodes": len(cols),
            "start_dt": start_dt,
            "source_file": str(path),
            "series_cm": (series * 100.0).round(2).tolist(),  # m -> cm
        }
        ds.close()
        return [row]
    except Exception:
        try:
            ds.close()
        except Exception:
            pass
        return []


def _point_source_chain(ctx: ModuleContext) -> List[str]:
    """任意点采样的数据源尝试顺序（非结构网格优先，其次结构化网格）。"""
    cands = [
        ctx.files.get("nc_forecast_num") or "",
        ctx.files.get("nc_forecast_num_alt") or "",
    ]
    cands += list(ctx.files.get("surge_files") or [])
    out: List[str] = []
    for p in cands:
        if p and p not in out:
            out.append(p)
    return out


def _run_point(ctx: ModuleContext, lon_pt: float, lat_pt: float, label: str, short: str,
               region: str, hours: Optional[int],
               target_date: Optional[datetime.date] = None) -> Optional[Dict[str, Any]]:
    """在模式场/网格上按点采样；成功返回 geo_stats 结果，失败返回 None。"""
    for path in _point_source_chain(ctx):
        sites = _read_mesh_point(ctx, path, lon_pt, lat_pt, label, short)
        src = "mesh"
        if not sites:
            sites = _read_grid_point(ctx, path, lon_pt, lat_pt, label, short)
            src = "grid"
        if sites:
            if target_date:
                sites = _slice_by_date(sites, target_date)
            geo = _finalize(sites, region, "ensemble" if src == "mesh" else "grid", path, hours)
            geo["custom_point"] = True
            geo["point_lon"] = round(lon_pt, 3)
            geo["point_lat"] = round(lat_pt, 3)
            geo["point_name"] = short
            geo["sample_kind"] = src
            s0 = sites[0]
            geo["sample_lon"] = s0.get("grid_lon")
            geo["sample_lat"] = s0.get("grid_lat")
            geo["sample_dist_km"] = s0.get("grid_dist_km")
            if s0.get("series_all"):
                geo["max_all_cm"] = round(float(np.nanmax(np.asarray(s0["series_all"], dtype=float))), 1)
            return geo
    return None


def _nearest_station_fallback(ctx: ModuleContext, lon_pt: float, lat_pt: float,
                              region: str, hours: Optional[int],
                              target_date: Optional[datetime.date] = None) -> Optional[Dict[str, Any]]:
    """兜底：该台风只有本站单点数据时，用最近站点代替并注明。"""
    from orchestrator import geo_domain

    st_name, dist_km = geo_domain.nearest_station(lon_pt, lat_pt)
    paths = _pick_station_files(ctx.files.get("station_files") or [],
                                ctx.results.get("meta", {}).get("typhoon", "") or "")
    sites = _read_station_data(paths) if paths else []
    if not sites:
        return None
    want = [s for s in sites if st_name in str(s.get("name", ""))]
    if not want:
        return None
    if target_date:
        want = _slice_by_date(want, target_date)
    geo = _finalize(want[:1], region, "station", paths[0] if paths else "", hours)
    geo["custom_point"] = True
    geo["point_lon"] = round(lon_pt, 3)
    geo["point_lat"] = round(lat_pt, 3)
    geo["sample_kind"] = "nearest_station"
    geo["sample_station"] = st_name
    geo["sample_dist_km"] = dist_km
    geo["sample_lon"] = want[0].get("lon")
    geo["sample_lat"] = want[0].get("lat")
    return geo


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
    target_date = _parse_target_date(ctx.request.get("date", ""))

    # ⭐⭐ 任意经纬度/任意地名：按点采样（优先级最高）
    pt = _point_from_request(ctx.request)
    if pt:
        lon_pt, lat_pt, label, short = pt
        geo = _run_point(ctx, lon_pt, lat_pt, label, short, region, hours, target_date)
        if geo is None:
            geo = _nearest_station_fallback(ctx, lon_pt, lat_pt, region, hours, target_date)
        if geo:
            ctx.results["geo_stats"] = geo
            _attach_wave(ctx)
            return ctx

    # ⭐ Ensemble/FTP 集合数据优先（2403/1521/1614：自带总水位/天文潮/增水）
    ens_path = ctx.files.get("nc_forecast_num", "")
    ens_like = ("Ensemble" in ens_path.replace("\\", "/")) or ("ftp" in ens_path.replace("\\", "/").lower())
    if ens_path and ens_like:
        sites = _read_ensemble_sites(ens_path)
        if sites:
            sites = _filter_sites(sites, ctx.request)
            if target_date:
                sites = _slice_by_date(sites, target_date)
            ctx.results["geo_stats"] = _finalize(sites, region, "ensemble", ens_path, hours)
            _attach_wave(ctx)
            return ctx

    # ① 单点数据优先（只取当前台风的主文件）
    paths = _pick_station_files(ctx.files.get("station_files") or [], typhoon)
    sites = _read_station_data(paths) if paths else []
    if sites:
        # 按请求站点过滤（问厦门就只画厦门）
        sites = _filter_sites(sites, ctx.request)
        if target_date:
            sites = _slice_by_date(sites, target_date)
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
    """海浪统计：扫描 M1/R1 海浪文件。

    - 未指定点：采样目标海域(厦门附近 WAVE_BOX)逐时最大波高
    - 指定点(lon/lat)：在波高场上按最近格点取该点的逐时波高序列
    """
    import xarray as xr

    paths = ctx.files.get("wave_files") or []
    if not paths:
        return {"status": "no_data", "series": []}

    pt = _point_from_request(ctx.request)

    # 优先 M1（细网格,厦门附近），否则 R1
    m1 = [p for p in paths if "M1" in os.path.basename(p)]
    r1 = [p for p in paths if "R1" in os.path.basename(p)]
    if pt:
        # 点采样：点在 M1 细网格范围内用 M1，否则用 R1（范围更大）
        in_m1 = False
        if m1:
            try:
                ds0 = xr.open_dataset(m1[0], decode_times=False)
                alon = np.asarray(ds0["alon"].values if "alon" in ds0.variables else ds0["lon"].values, dtype=float)
                alat = np.asarray(ds0["alat"].values if "alat" in ds0.variables else ds0["lat"].values, dtype=float)
                ds0.close()
                in_m1 = (np.nanmin(alon) <= pt[0] <= np.nanmax(alon)) and (np.nanmin(alat) <= pt[1] <= np.nanmax(alat))
            except Exception:
                in_m1 = False
        chosen = (sorted(m1) if in_m1 else sorted(r1)) or sorted(m1) or sorted(r1)
    else:
        chosen = sorted(m1) or sorted(r1)
    if not chosen:
        return {"status": "no_data", "series": []}

    # 按时间窗取需要的日文件数(每天24h)
    need_files = max(1, -(-(hours or 24) // 24)) if hours else len(chosen)
    chosen = chosen[:need_files]

    # 拼接各文件逐时序列
    full_series: List[float] = []
    sampled_at: Dict[str, Any] = {}
    for p in chosen:
        try:
            ds = xr.open_dataset(p, decode_times=False)
        except Exception:
            continue
        try:
            hs = ds["hs"]
            alon = ds["alon"].values if "alon" in ds.variables else ds["lon"].values
            alat = ds["alat"].values if "alat" in ds.variables else ds["lat"].values
            if pt:
                # —— 任意点采样：取"离点最近且波高有效"的格点（排除陆地/全 0 格点）——
                lonv = ds["lon"].values if "lon" in ds.variables else np.asarray(alon).ravel()
                latv = ds["lat"].values if "lat" in ds.variables else np.asarray(alat).ravel()
                ts = np.asarray([])
                if np.asarray(lonv).ndim == 1 and np.asarray(latv).ndim == 1:
                    lonv = np.asarray(lonv, dtype=float)
                    latv = np.asarray(latv, dtype=float)
                    cands = []
                    for di in range(-10, 11):
                        for dj in range(-10, 11):
                            i = int(np.abs(lonv - pt[0]).argmin()) + di
                            j = int(np.abs(latv - pt[1]).argmin()) + dj
                            if not (0 <= i < lonv.size and 0 <= j < latv.size):
                                continue
                            sel = {}
                            if "lon" in hs.dims:
                                sel["lon"] = i
                            if "lat" in hs.dims:
                                sel["lat"] = j
                            if not sel:
                                continue
                            try:
                                cand = np.asarray(hs.isel(**sel).values, dtype=float).ravel()
                            except Exception:
                                continue
                            fin = cand[np.isfinite(cand)]
                            if not fin.size or float(np.nanmax(fin)) <= 0.2:   # 波高 <= 0.2m 视为无效(陆地/静水)
                                continue
                            d = float(np.hypot((lonv[i] - pt[0]) * np.cos(np.radians(pt[1])), latv[j] - pt[1])) * 111.0
                            if d > 55.0:      # 离点太远（>55km）不作为该点代表
                                continue
                            cands.append((d, i, j, cand))
                    if cands:
                        cands.sort(key=lambda t: t[0])
                        d, i, j, ts = cands[0]
                        sampled_at = {"lon": round(float(lonv[i]), 3), "lat": round(float(latv[j]), 3),
                                      "dist_km": round(d, 1)}
                else:  # 非结构：最近节点
                    m = np.asarray(alon).ravel()
                    n = np.asarray(alat).ravel()
                    k = int(np.argmin((m - pt[0]) ** 2 + (n - pt[1]) ** 2))
                    ts = np.asarray(hs.values[k, :], dtype=float) if hs.shape[0] == m.size else np.asarray(hs.values, dtype=float).ravel()
                    sampled_at = {"lon": round(float(m[k]), 3), "lat": round(float(n[k]), 3)}
                if ts.size:
                    valid = ts[np.isfinite(ts)]
                    if valid.size:
                        full_series.extend(float(v) for v in valid)
                        continue
                # 该文件不含有效数据 → 换下一个文件
                continue
            # —— 默认：目标海域海域最大 ——
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
        "source": "M1" if (chosen and chosen[0] in m1) else "R1",
        "file": best["file"],
        "max_hs_m": best["max_hs_m"],
        "level": level,
        "peak_time": f"第{best['peak_idx']}时次",
        "series": best["series_m"],
        "time_window_hours": hours,
        "point": sampled_at or None,
        "mode": "point" if pt else "box",
    }
