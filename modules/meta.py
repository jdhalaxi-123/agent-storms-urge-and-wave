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


def _classify(name: str) -> str:
    """按文件名归类。"""
    if re.search(r"(ocn_forecast|storm_surge_forecast_sp|storm_surge_stations)", name):
        return "station"
    if re.search(r"_surge\.nc$|output_\d|storm_surge_", name):
        return "surge"
    if re.search(r"(M1|R1)_wav|wave_forecast|_wave_|_era5", name):
        return "wind" if "_era5" in name else "wave"
    if re.search(r"atm_forecast|wind", name):
        return "wind"
    return "other"


def run(ctx: ModuleContext) -> ModuleContext:
    region = ctx.request.get("region", "未知海域")
    tw = ctx.request.get("time_window", "未指定")
    req_ty = str(ctx.request.get("typhoon", "") or "").strip()

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

    by_kind: Dict[str, List[Dict[str, Any]]] = {"station": [], "surge": [], "wave": [], "wind": [], "other": []}
    for f in found:
        by_kind[_classify(f["name"])].append(f)

    # 目标台风数据筛选（默认 2526）
    target = req_id or "2526"
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

    # 非 Ensemble 场预报（2526 的 output_0/4）
    for f in by_kind["surge"]:
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
