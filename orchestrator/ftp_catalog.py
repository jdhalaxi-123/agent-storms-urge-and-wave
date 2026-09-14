# -*- coding: utf-8 -*-
"""FTP 数据地图 + 按需取数（不落地全量数据）。

设计原则
--------
课题数据库（FTP）上同一份结果往往有多种"包装"：有的 2 GB，有的 2 MB，内容对回答
一个问题来说够用就行。所以本模块的核心是：

    **按"用户问什么"挑最小的那个文件，临时下载到本地缓存，用完就留着复用。**

取数优先级（体积从小到大）
--------------------------
    station_surge   站点增水过程      8~10 KB/文件   /group3/storm_surge_point/new_wind_v2/
    wave_point      浮标点波高过程    10 KB/文件     /group3/TC_wave_point/wave/
    surge_field     风暴潮场(全场)    2 MB          /group3/storm_surge_field/
    observation     实测观测          1.4 MB        /group5/202609/observation/out2/
    cropped_field   天文潮+总水位     37~117 MB     /group5/202609/dataset_GFS_cropped/
    irregular_mesh  非结构网格三要素  0.2~1.2 GB    /group5/{号}_irregular.nc
    ortho_field     正交网格高精度    710/921 MB    /group1/storm_surge/正交/{号}/
    ensemble_surge  集合(AI)风暴潮    0.1~0.6 GB    /group5/irregular_surge_Ensemble/

缓存：`data/ftp_cache/<远程原文件名>`；同一文件已存在且大小一致则跳过下载。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import ftp_client

# 本地缓存目录
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "ftp_cache"

# --------------------------------------------------------------------------- #
# 数据源定义
# --------------------------------------------------------------------------- #
GROUP3_POINT = "/group3/storm_surge_point/new_wind_v2"
GROUP3_FIELD = "/group3/storm_surge_field"
GROUP3_WAVE_PT = "/group3/TC_wave_point/wave"
OBSERVE = "/group5/202609/observation/out2"
CROPPED = "/group5/202609/dataset_GFS_cropped"
ORTHO = "/group1/storm_surge/正交"
IRREGULAR = "/group5"
ENSEMBLE = "/group5/irregular_surge_Ensemble"

# 站点编号 -> 中文名（课题三单点文件的站号）
STATION_CN = {"XMN": "厦门", "CWU": "崇武", "JNJ": "晋江", "DSN": "东山东港"}

# 用于盘点台风的可扫描根目录
SCAN_DIRS = [ORTHO, GROUP3_POINT, GROUP3_FIELD, GROUP3_WAVE_PT, CROPPED, OBSERVE,
             "/group1/storm_surge", ENSEMBLE]

_cache_mem: Dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# 底层工具
# --------------------------------------------------------------------------- #
def _ls(ftp, path: str) -> List[Dict[str, Any]]:
    out = []
    try:
        for name, meta in ftp.mlsd(path):
            if name in (".", ".."):
                continue
            out.append({
                "name": name,
                "dir": meta.get("type") == "dir",
                "size": int(meta.get("size", 0) or 0),
                "mtime": meta.get("modify", ""),
                "path": f"{path.rstrip('/')}/{name}",
            })
    except Exception:
        return []
    return out


def _typhoon_ids(ftp, path: str, prefix: str = "") -> List[str]:
    """从目录名/文件名里抽出台风编号（4 位数字）。"""
    ids = []
    for e in _ls(ftp, path):
        n = e["name"]
        if prefix:
            if not n.startswith(prefix):
                continue
            n = n[len(prefix):]
        head = n[:4]
        if head.isdigit():
            ids.append(head)
    return sorted(set(ids))


def _stat_size(ftp, path: str) -> int:
    for e in _ls(ftp, path):
        if not e["dir"]:
            return e["size"]
    return 0


# --------------------------------------------------------------------------- #
# 台风清单 / 数据地图
# --------------------------------------------------------------------------- #
def typhoon_list(force: bool = False, ttl: int = 1800) -> List[str]:
    """FTP 上目前有哪些台风的个例数据（扫描若干目录的并集）。"""
    key = "typhoon_list"
    now = time.time()
    if not force and key in _cache_mem and now - _cache_mem[key]["t"] < ttl:
        return _cache_mem[key]["v"]
    ftp = ftp_client._connect()
    try:
        ids = set()
        ids |= set(_typhoon_ids(ftp, ORTHO))
        ids |= set(_typhoon_ids(ftp, GROUP3_POINT, "typhoon_"))
        ids |= set(_typhoon_ids(ftp, GROUP3_FIELD, "typhoon_"))
        ids |= set(_typhoon_ids(ftp, GROUP3_WAVE_PT, "typhoon_"))
        ids |= set(_typhoon_ids(ftp, CROPPED))
        ids |= set(_typhoon_ids(ftp, OBSERVE))
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    out = sorted(ids)
    _cache_mem[key] = {"t": now, "v": out}
    return out


def catalog(typhoon: str, force: bool = False, ttl: int = 1800) -> Dict[str, Any]:
    """列出某个台风在 FTP 上**实际可用**的数据源（含体积，便于选最小的）。"""
    ty = str(typhoon).strip()
    key = f"cat:{ty}"
    now = time.time()
    if not force and key in _cache_mem and now - _cache_mem[key]["t"] < ttl:
        return _cache_mem[key]["v"]

    ftp = ftp_client._connect()
    cat: Dict[str, Any] = {"typhoon": ty, "sources": {}}
    try:
        # ① 站点增水过程（最小，8~10 KB/文件）
        d = f"{GROUP3_POINT}/typhoon_{ty}"
        files = [e for e in _ls(ftp, d) if not e["dir"]]
        if files:
            stations: Dict[str, List[Dict[str, Any]]] = {}
            for e in files:
                # 文件名形如 storm_surge_forecast_sp_CWU_20240716.nc
                m = re.search(r"_sp_([A-Za-z0-9]+)_(\d{8})", e["name"])
                st = m.group(1) if m else "?"
                day = m.group(2) if m else ""
                stations.setdefault(st, []).append(
                    {"path": e["path"], "name": e["name"], "size": e["size"], "date": day})
            cat["sources"]["station_surge"] = {
                "dir": d, "n_files": len(files),
                "total_mb": round(sum(f["size"] for f in files) / 1e6, 2),
                "stations": {k: sorted(v, key=lambda x: x["date"]) for k, v in stations.items()},
                "note": "单点纯增水序列(cm)，每文件约1天；站号 XMN厦门/CWU崇武/JNJ晋江/DSN东山",
            }

        # ② 浮标点波高过程（10 KB/站）
        d = f"{GROUP3_WAVE_PT}/typhoon_{ty}"
        files = [e for e in _ls(ftp, d) if not e["dir"]]
        if files:
            cat["sources"]["wave_point"] = {
                "dir": d, "n_files": len(files),
                "total_mb": round(sum(f["size"] for f in files) / 1e6, 3),
                "files": [{"path": e["path"], "size": e["size"],
                           "station": e["name"].split("_")[2] if "_" in e["name"] else "?"}
                          for e in sorted(files, key=lambda x: x["name"])],
                "note": "16个浮标站波高过程",
            }

        # ③ 风暴潮场（2 MB，全场 114-128E/17-30N）
        d = f"{GROUP3_FIELD}/typhoon_{ty}"
        files = [e for e in _ls(ftp, d) if not e["dir"]]
        if files:
            cat["sources"]["surge_field"] = {
                "dir": d,
                "files": [{"path": e["path"], "name": e["name"], "size": e["size"]}
                          for e in sorted(files, key=lambda x: x["name"])],
                "note": "全场风暴潮 surge(cm)，0.25°网格",
            }

        # ④ 实测观测（1.4 MB）
        for kind, suffix in (("observation_qc", "_observation_qc.nc"),
                             ("observation_origin", "_observation_origin.nc")):
            p = f"{OBSERVE}/{ty}{suffix}"
            sz = _stat_size(ftp, p)
            if sz:
                cat["sources"][kind] = {"path": p, "size": sz,
                                        "note": "浮标实测：波高/潮位/风/气压等"}

        # ⑤ 裁剪版风暴潮场（天文潮 + 总水位，37~117 MB）
        d = f"{CROPPED}/{ty}"
        sub = {e["name"]: e for e in _ls(ftp, d) if not e["dir"]}
        if sub:
            cat["sources"]["cropped_field"] = {
                "dir": d,
                "tide": sub.get("output_0.nc", {}).get("path"),
                "tide_size": sub.get("output_0.nc", {}).get("size", 0),
                "total": sub.get("output_4.nc", {}).get("path"),
                "total_size": sub.get("output_4.nc", {}).get("size", 0),
                "note": "output_0=天文潮(潮驱动)  output_4=总水位(风+潮驱动)  相减=增水",
            }

        # ⑥ 非结构网格（含 elev_all/elev_tide/elev_surge 三要素）
        for tag, p in (("irregular_mesh", f"{IRREGULAR}/{ty}_irregular.nc"),
                       ("irregular_mesh_face", f"{IRREGULAR}/irrgular-face/{ty}_irregular.nc"),
                       ("irregular_mesh_new", f"{IRREGULAR}/irrgular-face/{ty}_irregular_new.nc")):
            sz = _stat_size(ftp, p)
            if sz:
                cat["sources"][tag] = {"path": p, "size": sz,
                                       "note": "非结构三角网格，含天文潮/增水/总水位"}

        # ⑦ 集合(AI)风暴潮
        for tag, p in (("ensemble_surge", f"{ENSEMBLE}/{ty}_irregular_new.nc"),
                       ("ensemble_surge_old", f"{ENSEMBLE}/{ty}_irregular.nc")):
            sz = _stat_size(ftp, p)
            if sz:
                cat["sources"][tag] = {"path": p, "size": sz,
                                       "note": "集合(AI)风暴潮，含三要素"}

        # ⑧ 正交网格高精度场（大：710/921 MB）
        d = f"{ORTHO}/{ty}"
        sub = {e["name"]: e for e in _ls(ftp, d) if not e["dir"]}
        if sub:
            cat["sources"]["ortho_field"] = {
                "dir": d,
                "tide": sub.get("output_0.nc", {}).get("path"),
                "tide_size": sub.get("output_0.nc", {}).get("size", 0),
                "total": sub.get("output_4.nc", {}).get("path"),
                "total_size": sub.get("output_4.nc", {}).get("size", 0),
                "note": "高精度正交网格；文件很大(0.7~0.9GB)，仅在必要时下",
            }
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    _cache_mem[key] = {"t": now, "v": cat}
    return cat


def best_source(cat: Dict[str, Any], want: str) -> Optional[Dict[str, Any]]:
    """按需求挑"最小够用"的数据源。

    want 取值：
        "station"      站点增水过程   -> station_surge
        "wave_point"   浮标波高过程   -> wave_point
        "field"        全场风暴潮     -> surge_field（2MB）优先，否则 cropped/ortho
        "tide_total"   天文潮+总水位  -> cropped_field（小）优先，否则 ortho_field
        "mesh"         非结构网格三要素 -> irregular_mesh*
        "ensemble"     集合(AI)       -> ensemble_surge
        "observation"  实测           -> observation_qc
    """
    s = cat.get("sources", {})
    order = {
        "station": ["station_surge"],
        "wave_point": ["wave_point"],
        "field": ["surge_field", "cropped_field", "ortho_field"],
        "tide_total": ["cropped_field", "ortho_field"],
        "mesh": ["irregular_mesh", "irregular_mesh_face", "irregular_mesh_new"],
        "ensemble": ["ensemble_surge", "ensemble_surge_old"],
        "observation": ["observation_qc", "observation_origin"],
    }.get(want, [])
    for k in order:
        if k in s:
            out = dict(s[k])
            out["kind"] = k
            return out
    return None


# --------------------------------------------------------------------------- #
# 按需下载 + 缓存
# --------------------------------------------------------------------------- #
def fetch(remote: str, force: bool = False, expected_size: int = 0) -> Optional[str]:
    """把远程文件下到本地缓存，返回本地路径；已存在且大小一致则直接复用。"""
    if not remote:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local = CACHE_DIR / os.path.basename(remote)
    if local.exists() and not force:
        if not expected_size or abs(local.stat().st_size - expected_size) < 1024:
            return str(local)
    try:
        ftp_client.download(remote, str(local))
        return str(local)
    except Exception as e:  # noqa: BLE001
        print(f"[ftp_catalog] 下载失败 {remote}: {e}")
        return None


def fetch_many(items: List[Dict[str, Any]], force: bool = False,
               max_total_mb: float = 0) -> List[str]:
    """批量下载。items 为 [{"path":..., "size":...}, ...]。

    max_total_mb > 0 时，累计超过阈值即停止（防止误下超大文件）。
    """
    out, total = [], 0.0
    for it in items:
        p = it.get("path") if isinstance(it, dict) else str(it)
        sz = it.get("size", 0) if isinstance(it, dict) else 0
        if max_total_mb and total + sz / 1e6 > max_total_mb:
            print(f"[ftp_catalog] 已达下载上限 {max_total_mb} MB，跳过 {os.path.basename(p)}")
            continue
        lp = fetch(p, force=force, expected_size=sz)
        if lp:
            out.append(lp)
            total += sz / 1e6
    return out


def cache_info() -> Dict[str, Any]:
    """本地缓存占用情况。"""
    if not CACHE_DIR.exists():
        return {"dir": str(CACHE_DIR), "files": 0, "mb": 0.0}
    fs = [f for f in CACHE_DIR.iterdir() if f.is_file()]
    return {"dir": str(CACHE_DIR), "files": len(fs),
            "mb": round(sum(f.stat().st_size for f in fs) / 1e6, 1)}


def clear_cache(keep_mb: float = 0) -> int:
    """清理缓存；keep_mb>0 时按最近修改时间保留不超过该体积。返回删除文件数。"""
    if not CACHE_DIR.exists():
        return 0
    fs = sorted((f for f in CACHE_DIR.iterdir() if f.is_file()),
                key=lambda f: f.stat().st_mtime, reverse=True)
    kept, n = 0.0, 0
    for f in fs:
        mb = f.stat().st_size / 1e6
        if kept + mb <= keep_mb:
            kept += mb
            continue
        try:
            f.unlink()
            n += 1
        except Exception:
            pass
    return n


if __name__ == "__main__":  # 命令行自检：python -m orchestrator.ftp_catalog [台风号] [--full]
    import sys

    tys = typhoon_list(force=True)
    print(f"FTP 上共有 {len(tys)} 个台风个例：")
    print("  " + " ".join(tys))
    target = next((a for a in sys.argv[1:] if a.isdigit()), tys[-1] if tys else "")
    if target:
        cat = catalog(target, force=True)
        print(f"\n=== {target} 号台风可用数据源 ===")
        for k, v in cat.get("sources", {}).items():
            if k == "station_surge":
                sts = ", ".join(f"{s}({len(vv)}天)" for s, vv in v["stations"].items())
                print(f"  {k:22s} {v['n_files']:3d} 文件 {v['total_mb']:7.2f} MB   站点: {sts}")
            elif k == "wave_point":
                print(f"  {k:22s} {v['n_files']:3d} 文件 {v['total_mb']:7.3f} MB   16个浮标站")
            elif k in ("surge_field",):
                for f in v["files"]:
                    print(f"  {k:22s} {f['name']:44s} {f['size']/1e6:7.2f} MB")
            elif k in ("cropped_field", "ortho_field"):
                print(f"  {k:22s} 天文潮 {v['tide_size']/1e6:8.1f} MB | 总水位 {v['total_size']/1e6:8.1f} MB")
            elif k in ("observation_qc", "observation_origin"):
                print(f"  {k:22s} {v['size']/1e6:8.2f} MB  {v['path']}")
            else:
                print(f"  {k:22s} {v.get('size',0)/1e6:8.2f} MB  {v.get('path','')}")
        if "--full" in sys.argv:
            import json
            print(json.dumps(cat, ensure_ascii=False, indent=2))
    print("\n缓存情况:", cache_info())
