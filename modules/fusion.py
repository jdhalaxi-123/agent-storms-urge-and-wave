# -*- coding: utf-8 -*-
"""第五组「融合（fusion）」产品接入。

数据位置（课题库 FTP）
----------------------
    /group5/fusion_df/<kind>/fusion_forecast_<起报YYYYMMDDHH>_<grid>.nc    每日预报
    /group5/fusion_typhoon/<kind>/fusion_<台风号>_<grid>.nc                台风个例（21 个）

    kind：low_tide / high_tide（风暴潮）　low_wave / high_wave（海浪）
    grid：regular（全场 0.05°）　regular-H（福建中南部 0.0083°）
          即目录名里的 low/high 指**低/高分辨率网格**，不是低潮/高潮

变量与含义（以 nc 自带属性为准）
--------------------------------
    tide_ensemble  风暴潮**总水位**（天文潮 + 增水），单位 m
                   longname = "Storm-surge total water level（fusion）"
    hs_ensemble    **有效波高**，单位 m
                   longname = "wave height（fusion）"

口径（第五组答复 + nc 属性）
-----------------------------
    - 时间轴：**UTC**，逐时；每日期 144 个时次（6 天），台风个例 288 个（12 天）
    - 基准面：**0 = 平均海平面**（提供方口径）
    - 生成：`predict_surge.py` / `predict_wave.py`，MATLAB-parity recurrent SAC 集合融合
    - nc 属性带 `fusion_constant_source_1_cells`：约 44% 的格点是"常数源"
      （整段几乎不随时间变化）→ 取点时优先挑**随时间变化**的格点，避免给出一条直线
"""
from __future__ import annotations

import datetime
import re
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from orchestrator import ftp_catalog as fc

ROOT = "/group5"
DF_DIR = f"{ROOT}/fusion_df"
TY_DIR = f"{ROOT}/fusion_typhoon"

# kind -> (变量名, 中文量名, 单位, 网格类型, 目录名)
KINDS: Dict[str, Dict[str, str]] = {
    "tide": {"var": "tide_ensemble", "cn": "风暴潮总水位", "unit": "m",
             "kind_dir": "low_tide", "fine_dir": "high_tide", "grid": "regular"},
    "wave": {"var": "hs_ensemble", "cn": "有效波高", "unit": "m",
             "kind_dir": "low_wave", "fine_dir": "high_wave", "grid": "regular"},
}

_mem: Dict[str, Any] = {}
_TTL = 600.0


def _ls(path: str, tries: int = 2, timeout: float = 12.0) -> List[Dict[str, Any]]:
    """列 FTP 目录。**绝不抛异常**（FTP 偶发 10060 超时），失败重试后返回 []。

    超时收紧到 12 秒：课题库不稳时，30 秒 × 多次重试会让"列目录"卡好几分钟，
    把整轮对话拖死（实测出现过）。融合这层宁可快速失败、如实说取不到。
    """
    import time as _t
    for i in range(max(1, tries)):
        try:
            ftp = fc.ftp_client._connect(timeout=timeout)
        except Exception:
            _t.sleep(0.8)
            continue
        try:
            return fc._ls(ftp, path)
        except Exception:
            _t.sleep(0.6)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
    return []


def _dir(kind: str, fine: bool = False, typhoon: str = "") -> str:
    k = KINDS[kind]
    name = k["fine_dir"] if fine else k["kind_dir"]
    return f"{TY_DIR if typhoon else DF_DIR}/{name}"


# --------------------------------------------------------------------------- #
# 列目录 / 最新一期
# --------------------------------------------------------------------------- #
def list_issues(kind: str, typhoon: str = "", force: bool = False) -> List[str]:
    """该 kind 有哪些起报日（YYYYMMDD）——两种网格的并集。

    台风个例请用 list_typhoons()。FTP 偶发超时会让某次列目录变少，
    因此这里把"历史上见过的最新期"缓存起来，避免最新期忽然后退。
    """
    key = f"issues:{kind}:{typhoon}"
    now = __import__("time").time()
    if not force and key in _mem and now - _mem[key]["t"] < _TTL:
        return _mem[key]["v"]
    out: List[str] = []
    for fine in (False, True):
        for e in _ls(_dir(kind, fine, typhoon)):
            m = re.search(r"fusion_forecast_(\d{8})", e["name"])
            if m:
                out.append(m.group(1))
    out = sorted(set(out))
    seen = set(_mem.get(f"seen:{key}", {}).get("v") or [])
    seen |= set(out)
    _mem[f"seen:{key}"] = {"t": now, "v": sorted(seen)}
    if len(seen) > len(out):                     # 本次列目录被截断 → 用见过的并集
        out = sorted(seen)
    _mem[key] = {"t": now, "v": out}
    return out


def issues_by_grid(kind: str, typhoon: str = "") -> Dict[str, List[str]]:
    """分别列出两种网格各有哪些起报日（看清到底哪种网格传了）。"""
    res: Dict[str, List[str]] = {}
    for fine in (False, True):
        ds = []
        for e in _ls(_dir(kind, fine, typhoon)):
            m = re.search(r"fusion_forecast_(\d{8})" if not typhoon
                          else r"fusion_(\d{4})_", e["name"])
            if m:
                ds.append(m.group(1))
        res["regular-H（精细）" if fine else "regular（全场）"] = sorted(set(ds))
    return res


def latest_for(kind: str, fine: bool, force: bool = False,
               typhoon: str = "") -> str:
    """**只列要用的那种网格**，取该网格的最新起报日（FTP 偶发超时会重试）。

    之前直接取"两种网格的并集最新"，一旦全场目录那次列超时，
    就会退到精细目录里的旧日期（曾出现"最新期=20260503"）。
    """
    key = f"latest:{kind}:{fine}:{typhoon}"
    now = __import__("time").time()
    if not force and key in _mem and now - _mem[key]["t"] < _TTL:
        return _mem[key]["v"]
    ds: List[str] = []
    for e in _ls(_dir(kind, fine, typhoon), tries=4):
        m = re.search(r"fusion_forecast_(\d{8})" if not typhoon
                      else r"fusion_(\d{4})_", e["name"])
        if m:
            ds.append(m.group(1))
    best = max(ds) if ds else ""
    seen = str(_mem.get(f"seenL:{key}", {}).get("v") or "")
    if best and best > seen:
        _mem[f"seenL:{key}"] = {"t": now, "v": best}
    elif seen and not best:
        best = seen                                  # 这次列目录失败 → 用见过的
    _mem[key] = {"t": now, "v": best}
    return best


def latest_issue(kind: str, typhoon: str = "", force: bool = False) -> str:
    ds = list_issues(kind, typhoon, force=force)
    return ds[-1] if ds else ""


def list_typhoons(kind: str = "tide", force: bool = False) -> List[str]:
    key = f"ty:{kind}"
    now = __import__("time").time()
    if not force and key in _mem and now - _mem[key]["t"] < _TTL:
        return _mem[key]["v"]
    out: List[str] = []
    for fine in (False, True):
        try:
            ents = _ls(_dir(kind, fine, typhoon="x"))
        except Exception:
            ents = []
        for e in ents:
            m = re.search(r"fusion_(\d{4})_", e["name"])
            if m:
                out.append(m.group(1))
    out = sorted(set(out))
    _mem[key] = {"t": now, "v": out}
    return out


# --------------------------------------------------------------------------- #
# 取数 + 读 nc
# --------------------------------------------------------------------------- #
def _find_entry(kind: str, issue: str, fine: bool, typhoon: str = "") -> Tuple[str, int]:
    """返回 (远程路径, 字节数)。fine=True 找 regular-H，否则找 regular。"""
    pat = (rf"fusion_{typhoon}_regular" if typhoon
           else rf"fusion_forecast_{issue}00_regular")
    for f in ((True, False) if fine else (False, True)):
        for e in _ls(_dir(kind, f, typhoon)):
            n = e["name"]
            if not n.startswith(pat) or n.startswith("."):
                continue
            is_fine = n.endswith("-H.nc")
            if is_fine != bool(f):          # 严格区分 regular / regular-H，别串台
                continue
            if not (n.endswith(".nc")):
                continue
            return e["path"], int(e.get("size", 0) or 0)
    return "", 0


_FAIL_TTL = 900.0            # 某个文件下载失败后，15 分钟内不再重试（熔断）


def _breaker_open(remote: str) -> bool:
    import time as _t
    v = _mem.get(f"fail:{remote}") or {}
    if v and _t.time() - float(v.get("t") or 0) < _FAIL_TTL:
        return True
    return False


def _breaker_trip(remote: str) -> None:
    import time as _t
    _mem[f"fail:{remote}"] = {"t": _t.time()}


def load(kind: str, issue: str = "", fine: bool = False,
         typhoon: str = "") -> Optional[Dict[str, Any]]:
    """取并读取一份融合 nc。指定的网格没上传时**自动回退到另一种网格**。

    返回结构化字典（含"是否随时间变化"的格点掩膜、常数源占比、口径文案所需字段）。
    """
    import xarray as xr

    if not issue and not typhoon:
        # 先按日期倒着探测（稳），再退回列目录
        d, f = latest_by_probe(kind, fine)
        if d:
            issue, fine = d, f
        else:
            issue = latest_for(kind, fine) or latest_for(kind, not fine)
    if not issue and not typhoon:
        return None
    if typhoon:
        # 台风个例：网格由探测结果决定
        _d, _f = latest_by_probe(kind, fine, typhoon=typhoon)
        if _d:
            fine = _f
    # 先按请求的网格找，找不到再换另一种（并如实记录实际用的是哪种）
    plans = [fine, not fine]
    remote = size = ""
    used_fine = fine
    for f in plans:
        remote, size = _find_entry(kind, issue, f, typhoon)
        if remote:
            used_fine = f
            break
    if not remote:
        # 该日期在这两种网格里都没有 → 换成"另一种网格自己的最新期"再试一次
        for f in plans:
            alt = latest_for(kind, f, typhoon=typhoon)
            if alt and alt != issue:
                remote, size = _find_entry(kind, alt, f, typhoon)
                if remote:
                    issue, used_fine = alt, f
                    break
    if not remote:
        return None
    key = f"load:{kind}:{issue}:{used_fine}:{typhoon}"
    now = __import__("time").time()
    if key in _mem and now - _mem[key]["t"] < _TTL:
        return _mem[key]["v"]

    if _breaker_open(remote):
        print(f"[fusion] 该文件最近取数失败（熔断中），先跳过：{remote}")
        return None
    local = fc.fetch(remote, expected_size=size)
    if not local:
        _breaker_trip(remote)
        print(f"[fusion] 取数失败，已熔断 15 分钟不再重试：{remote}")
        return None
    ds = xr.open_dataset(local, decode_times=True)
    try:
        var = KINDS[kind]["var"]
        if var not in ds.variables:
            return None
        la = np.asarray(ds["lat"].values, dtype=float).ravel()
        lo = np.asarray(ds["lon"].values, dtype=float).ravel()
        tv = np.asarray(ds["time"].values).ravel()
        arr = np.asarray(ds[var].values, dtype=float)
        if arr.ndim != 3:
            return None
        # 只保留"随时间变化"的格点（避开常数源）：整段极差 > 5 cm
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rng = np.nanmax(arr, axis=0) - np.nanmin(arr, axis=0)
        varying = np.isfinite(rng) & (rng > 0.05)
        attrs = {k: str(v)[:200] for k, v in ds.attrs.items()}
        out = {
            "kind": kind, "var": var, "cn": KINDS[kind]["cn"], "unit": "m",
            "issue": issue, "typhoon": typhoon, "fine": bool(used_fine),
            "remote": remote, "local": local,
            "lat": la, "lon": lo,
            "times": [str(t)[:19] for t in tv],
            "values": arr,                       # (t, lat, lon) 单位 m
            "varying": varying,                  # 随时间变化的格点
            "constant_ratio": round(float(1.0 - varying.sum() / max(rng.size, 1)), 3),
            "attrs": attrs,
            "file": remote.rsplit("/", 1)[-1],
        }
        _mem[key] = {"t": now, "v": out}
        return out
    finally:
        ds.close()


# --------------------------------------------------------------------------- #
# 取点 / 时间 / 文案
# --------------------------------------------------------------------------- #
def to_bjt(s: str) -> str:
    """UTC 串（'2026-10-09T00:00:00'）→ 北京时 'YYYY-MM-DD HH:MM'。"""
    try:
        t = datetime.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
        return (t + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            t = datetime.datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M")
            return (t + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""


def fmt(s: str) -> str:
    """'2026-10-09T00:00:00' → '2026-10-09 00:00'。"""
    return str(s)[:16].replace("T", " ")


def time_label(s: str) -> str:
    b = to_bjt(s)
    return f"{fmt(s)} UTC（北京时 {b[11:] if b else '—'}）"


def _exists(remote: str) -> int:
    """直接问 FTP 该文件多大（单条 SIZE，比列整个目录抗超时）。"""
    try:
        ftp = fc.ftp_client._connect(timeout=12.0)
    except Exception:
        return 0
    try:
        return int(fc._stat_size(ftp, remote) or 0)
    except Exception:
        return 0
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def latest_by_probe(kind: str, fine: bool, days: int = 21,
                    typhoon: str = "") -> Tuple[str, bool]:
    """从今天往前逐日探测"这一期的文件到底在不在"，返回 (起报日, 是否精细网格)。

    为什么不用列目录：FTP 偶发超时/截断，曾导致"最新期"被判成几周前的旧期
    （实测出现过把 20261009 判成 20260804）。SIZE 探测是单条命令，稳得多。
    """
    if typhoon:
        for f in (fine, not fine):
            p = (f"{_dir(kind, f, typhoon)}/fusion_{typhoon}_regular"
                 f"{'-H' if f else ''}.nc")
            if _exists(p):
                return typhoon, f
        return "", fine
    today = datetime.date.today()
    miss_streak = 0
    for i in range(max(1, days)):
        d = (today - datetime.timedelta(days=i)).strftime("%Y%m%d")
        hit = False
        for f in (fine, not fine):
            p = f"{_dir(kind, f)}/fusion_forecast_{d}00_regular{'-H' if f else ''}.nc"
            if _exists(p):
                return d, f
            hit = True
        # 连续 3 天两种网格都"探测不到" → 大概率是 FTP 连不上，赶紧收手
        miss_streak = miss_streak + 1 if hit else 0
        if miss_streak >= 3:
            print(f"[fusion] 连续 {miss_streak} 天探测不到 {kind} 文件，"
                  "疑似课题库连接不稳，停止探测")
            break
    return "", fine


def point(fld: Dict[str, Any], lon: float, lat: float,
          prefer_varying: bool = True) -> Optional[Dict[str, Any]]:
    """取站点/任意点的序列（优先"随时间明显变化"的格点）。

    ⚠️ 融合产品里约 30~45% 的格点是"常数源"（整段几乎不动）。
    只按"最近"取点会拿到一条直线（例如东山那个格点 6 天变幅只有 13 cm），
    所以在站点周围 0.3° 内**优先挑变幅足够大的格点**：
        总水位要变幅 > 1.0 m、浪高要 > 0.5 m；找不到才退回"最近的有效格点"。
    返回里带 varied / range_m / cell 坐标 / 距离，供出图与说明如实标注。
    """
    if not fld:
        return None
    la, lo = fld["lat"], fld["lon"]
    vals = fld["values"]
    if vals is None or not np.isfinite(vals).any():
        return None
    LON, LAT = np.meshgrid(lo, la)
    dist = np.hypot(LON - lon, LAT - lat)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rng = np.nanmax(vals, axis=0) - np.nanmin(vals, axis=0)
    good = np.isfinite(rng)
    # 变幅门槛：总水位看 1.0 m，浪高看 0.5 m
    need = 1.0 if fld.get("kind") == "tide" else 0.5
    cand = good & (rng >= need) if prefer_varying else good
    near = dist <= 0.3
    if (cand & near).any():
        pool = cand & near
    elif cand.any():
        pool = cand
    else:                                   # 全都不达标 → 最近的有限格点
        pool = good
    if not pool.any():
        pool = np.ones_like(dist, dtype=bool)
    d = np.where(pool, dist, np.inf)
    j, i = np.unravel_index(int(np.argmin(d)), d.shape)
    ser = np.asarray(vals[:, j, i], dtype=float)
    tv = fld["times"]
    k = int(np.nanargmax(ser)) if np.isfinite(ser).any() else 0
    kmin = int(np.nanargmin(ser)) if np.isfinite(ser).any() else 0
    return {
        "series_m": [None if not np.isfinite(v) else round(float(v), 3) for v in ser],
        "series_cm": [None if not np.isfinite(v) else round(float(v) * 100.0, 1) for v in ser],
        "cell_lon": round(float(lo[i]), 4), "cell_lat": round(float(la[j]), 4),
        "dist_km": round(float(np.hypot(lo[i] - lon, la[j] - lat) * 111.0), 1),
        "varied": bool(np.isfinite(rng[j, i]) and rng[j, i] >= need),
        "cell_range_m": (round(float(rng[j, i]), 2) if np.isfinite(rng[j, i]) else None),
        "max_m": (round(float(np.nanmax(ser)), 2) if np.isfinite(ser).any() else None),
        "min_m": (round(float(np.nanmin(ser)), 2) if np.isfinite(ser).any() else None),
        "peak_time": fmt(tv[k]) if tv else "",
        "peak_time_bjt": to_bjt(tv[k]) if tv else "",
        "low_time": fmt(tv[kmin]) if tv else "",
        "range_m": (round(float(np.nanmax(ser) - np.nanmin(ser)), 2)
                    if np.isfinite(ser).any() else None),
        "n": int(ser.size),
    }


def provenance(fld: Dict[str, Any]) -> str:
    """统一口径说明（回复/图题都照这句说）。"""
    if not fld:
        return ""
    grid = "福建中南部精细 0.0083°" if fld.get("fine") else "全场 0.05°"
    head = (f"第五组融合产品（AI+数值模式融合）· {fld['cn']} · "
            f"{'台风个例 ' + fld['typhoon'] if fld.get('typhoon') else '起报 ' + fld['issue']} · "
            f"{grid}")
    return (f"{head}；基准：平均海平面；时间：UTC（括号内为北京时）；"
            f"数据来自 {fld.get('file', '')}")
