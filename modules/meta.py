"""模块① Meta 分析：扫描 / 管理 NC 数据。

按「各课题文件路径及数据格式约定」扫描本地数据目录，自动分类：
    - 站点风暴潮：  ocr_forecast_* / storm_surge_forecast_sp_* / storm_surge_stations_*
    - 风暴潮网格场：output_*.nc / storm_surge_*.nc
    - 海浪场：      M1_wav / R1_wav / *_wave_forecast_1h
    - 风场：        atm_forecast / ERA5(u10/v10/msl)

数据目录可用环境变量 STORM_DATA_DIR 覆盖，默认 <项目根>/data。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from orchestrator.contract import ModuleContext


def data_root() -> Path:
    env = os.environ.get("STORM_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def scan(folder: Path) -> List[Dict[str, Any]]:
    """扫描目录下所有非空 nc 文件。"""
    if not folder.exists():
        return []
    files = [p for p in folder.rglob("*.nc") if p.is_file() and p.stat().st_size > 0]
    return [
        {
            "path": str(p),
            "name": p.name,
            "rel": str(p.relative_to(folder)) if p.is_relative_to(folder) else p.name,
            "size_mb": round(p.stat().st_size / 1024 / 1024, 2),
        }
        for p in sorted(files)
    ]


def _classify(name: str, rel: str = "") -> str:
    """按文件名/路径归类。"""
    r = (rel or name).replace("\\", "/").lower()
    if re.search(r"(ocn_forecast|storm_surge_forecast_sp|storm_surge_stations)", name):
        return "station"
    if re.search(r"_surge\.nc$|output_\d|storm_surge_", name):
        return "surge"
    # ERA5 风场目录 / 文件名
    if "/era5/" in r or "_era5" in name.lower() or re.search(r"^\d{10}\.nc$", name):
        return "wind"
    if re.search(r"(M1|R1)_wav|wave_forecast|_wave_", name):
        return "wave"
    if re.search(r"atm_forecast|wind", name, re.I):
        return "wind"
    return "other"


def _ftp_typhoon_id(request: Dict[str, Any]) -> str:
    """请求里是否点名了台风编号（返回 4 位台风号，否则空串）。

    注意：这里**只取编号**；是否走 FTP 由 run() 查数据地图后决定 ——
    只要该台风在 FTP 上有可用数据源（站点增水/全场增水/裁剪场/实测）就走 FTP，
    不再限定"数据完整的 10 个"。
    """
    m = re.search(r"(\d{4})", str(request.get("typhoon", "") or ""))
    return m.group(1) if m else ""


# 走 FTP 至少需要其中一类数据源
FTP_USABLE_KEYS = ("station_surge", "surge_field", "cropped_field", "observation_qc",
                   "ortho_field", "irregular_mesh", "ensemble_surge")


def _ftp_window(sources: Dict[str, Any]) -> str:
    """从 FTP 数据源里拼一个可读的数据时间窗描述。"""
    for key in ("surge_field", "station_surge"):
        src = sources.get(key) or {}
        for f in (src.get("files") or []):
            m = re.search(r"(\d{8})-(\d{8})", f.get("name", ""))
            if m:
                return f"{m.group(1)}~{m.group(2)}"
        if src.get("stations"):
            dates = sorted({d["date"] for v in src["stations"].values() for d in v})
            if dates:
                return f"{dates[0]}~{dates[-1]}"
    return ""


def run(ctx: ModuleContext) -> ModuleContext:
    region = ctx.request.get("region", "未知海域")
    tw = ctx.request.get("time_window", "未指定")
    req_ty = str(ctx.request.get("typhoon", "") or "").strip()

    # ⭐⭐ 台风期间数据（FTP 按需取数）：点名台风且 FTP 上有可用数据源时优先走这条路径。
    #      不落地全量数据，只按需拉小文件（站点增水 8.5KB/天、全场 2MB、实测 1.4MB …）
    ftp_ty = _ftp_typhoon_id(ctx.request)
    if ftp_ty:
        try:
            from orchestrator import ftp_catalog as _fcat

            cat = _fcat.catalog(ftp_ty)
            srcs = cat.get("sources", {})
            usable = [k for k in FTP_USABLE_KEYS if k in srcs]
            if usable:
                ctx.files["ftp_typhoon"] = ftp_ty
                ctx.results["meta"] = {
                    "status": "ftp",
                    "root": "FTP://课题数据库",
                    "typhoon": f"typhoon_{ftp_ty}",
                    "request_typhoon": ftp_ty,
                    "ftp_sources": sorted(srcs.keys()),
                    "ftp_usable": sorted(usable),
                    "data_window": _ftp_window(srcs),
                }
                return ctx
        except Exception as e:  # noqa: BLE001
            # FTP 不可用时静默回退到本地数据路径
            ctx.results["meta"] = {"status": "ftp_failed", "error": str(e)[:120]}

    root = data_root()
    found = scan(root)

    if not found:
        # 无数据降级占位
        ctx.files["nc_forecast_num"] = f"E:/data/{region}_数值模式_{tw}.nc"
        ctx.files["nc_forecast_ai"] = f"E:/data/{region}_智能预报_{tw}.nc"
        ctx.results["meta"] = {"status": "placeholder", "root": str(root), "matched": []}
        return ctx

    # 台风号归一化（请求里可能是 "2403" / "2526"）
    import re as _re
    m_ty = _re.search(r"(\d{3,4})", req_ty)
    req_id = m_ty.group(1) if m_ty else ""

    # ⭐ 没点名台风 = 每日预报类问题：**不要**绑定本地遗留的台风文件。
    #    （原实现在这里默认 target="2526"，导致"问福建沿海的场"画出来的
    #      是 2526 台风的旧场图；每日预报一律走 FTP 上的当天数据。）
    if not req_id:
        ctx.results["meta"] = {
            "status": "daily",
            "root": str(root),
            "typhoon": "",
            "request_typhoon": "",
            "total": len(found),
            "note": "未点名台风 → 走每日 AI 预报（FTP 当天数据），不使用本地遗留 nc",
        }
        return ctx

    by_kind: Dict[str, List[Dict[str, Any]]] = {"station": [], "surge": [], "wave": [], "wind": [], "other": []}
    for f in found:
        by_kind[_classify(f["name"], f.get("rel", ""))].append(f)

    target = req_id
    ctx.files["surge_files"] = [f["path"] for f in by_kind["surge"]
                                if target in f["rel"].replace("\\", "/")]
    ctx.files["wave_files"] = [f["path"] for f in by_kind["wave"]
                               if target in f["rel"].replace("\\", "/")]
    ctx.files["wind_files"] = [f["path"] for f in by_kind["wind"]
                               if target in f["rel"].replace("\\", "/")]
    ctx.files["station_files"] = [f["path"] for f in by_kind["station"]
                                  if target in f["rel"].replace("\\", "/") or target in f["name"]]

    # ⭐ FTP 同步数据优先（data/ftp/{台风}/{台风}_surge.nc: 全量 水位/潮位/增水/风场/气压）
    ftp_files = [f for f in found if "ftp" in f["rel"].replace("\\", "/").lower() and target in f["name"]]
    ftp_surge = next((f for f in ftp_files if "_surge" in f["name"] or f["name"].endswith(".nc") and "era5" not in f["name"]), None)
    if ftp_surge:
        ctx.files["nc_forecast_num"] = ftp_surge["path"]
        ctx.files["ftp_sync"] = True
        _wf = next((f for f in ftp_files if "era5" in f["name"]), None)
        if _wf:
            ctx.files["wind_files"] = [_wf["path"]]

    # Ensemble 台风集合（2403/1521/1614）：从 Ensemble 目录按台风挑
    ens_files = [f for f in found if "Ensemble" in f["rel"].replace("\\", "/") and target in f["name"]]
    if ens_files and not ctx.files.get("ftp_sync"):
        ctx.files["ensemble_files"] = [f["path"] for f in ens_files]
        # 主文件：优先 *_irregular_new.nc(float32省内存)，其次 ensemble_*
        best = None
        for f in ens_files:
            n = f["name"]
            if "_irregular_new" in n:
                best = f
                break
        if best is None:
            for f in ens_files:
                if "_irregular" in f["name"]:
                    best = f
                    break
        if best:
            ctx.files["nc_forecast_num"] = best["path"]
            if "wave" in best["rel"].replace("\\", "/") or "Wave" in best["rel"]:
                pass
        # 海浪集合
        wf = next((f for f in ens_files if "_wave" in f["name"].lower() or "wave" in f["rel"].replace("\\", "/").lower()), None)
        if wf:
            ctx.files["wave_files"] = [wf["path"]]

    # 非 Ensemble 场预报（2526 的 output_0/4）——只认当前台风目录下的文件，
    # 避免把 data/sample 等同名样例文件当成真实数据
    for f in by_kind["surge"]:
        if target not in f["rel"].replace("\\", "/"):
            continue
        if f["name"] == "output_0.nc":
            ctx.files["nc_forecast_num"] = ctx.files.get("nc_forecast_num") or f["path"]
        elif f["name"] == "output_4.nc":
            ctx.files["nc_forecast_num_alt"] = f["path"]

    ty_num = f"typhoon_{target}"
    ctx.results["meta"] = {
        "status": "found",
        "root": str(root),
        "typhoon": ty_num,
        "request_typhoon": req_id or "",
        "total": len(found),
        "classified": {k: len(v) for k, v in by_kind.items() if v},
        "station_files": [os.path.basename(p) if isinstance(p, str) else os.path.basename(p["path"]) for p in ctx.files.get("station_files", [])][:20],
        "surge_files": [os.path.basename(p) if isinstance(p, str) else os.path.basename(p["path"]) for p in ctx.files.get("surge_files", [])][:10],
        "wave_files": [os.path.basename(p) if isinstance(p, str) else os.path.basename(p["path"]) for p in ctx.files.get("wave_files", [])][:10],
        "ensemble_files": [os.path.basename(p) if isinstance(p, str) else os.path.basename(p["path"]) for p in ens_files][:10],
    }
    return ctx
