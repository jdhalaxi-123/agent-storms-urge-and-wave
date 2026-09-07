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
    if re.search(r"output_\d|storm_surge_", name):
        return "surge"
    if re.search(r"(M1|R1)_wav|wave_forecast|_wave_", name):
        return "wave"
    if re.search(r"atm_forecast|wind", name):
        return "wind"
    return "other"


def run(ctx: ModuleContext) -> ModuleContext:
    region = ctx.request.get("region", "未知海域")
    tw = ctx.request.get("time_window", "未指定")

    root = data_root()
    found = scan(root)

    if not found:
        # 无数据降级占位
        ctx.files["nc_forecast_num"] = f"E:/data/{region}_数值模式_{tw}.nc"
        ctx.files["nc_forecast_ai"] = f"E:/data/{region}_智能预报_{tw}.nc"
        ctx.results["meta"] = {"status": "placeholder", "root": str(root), "matched": []}
        return ctx

    by_kind: Dict[str, List[Dict[str, Any]]] = {"station": [], "surge": [], "wave": [], "wind": [], "other": []}
    for f in found:
        by_kind[_classify(f["name"])].append(f)

    # 登记关键路径
    ctx.files["station_files"] = [f["path"] for f in by_kind["station"]]
    ctx.files["surge_files"] = [f["path"] for f in by_kind["surge"]]
    ctx.files["wave_files"] = [f["path"] for f in by_kind["wave"]]
    ctx.files["wind_files"] = [f["path"] for f in by_kind["wind"]]

    for f in by_kind["surge"]:
        if f["name"] == "output_0.nc":
            ctx.files["nc_forecast_num"] = f["path"]
        elif f["name"] == "output_4.nc":
            ctx.files["nc_forecast_num_alt"] = f["path"]

    # 台风编号推断：优先 typhoon_2526（当前更新台风），否则按最常见的编号
    import collections
    ty_ids = re.findall(r"typhoon_(\d+)", " ".join(f["rel"] for f in found))
    if "2526" in ty_ids:
        ty_num = "typhoon_2526"
    elif ty_ids:
        ty_num = f"typhoon_{collections.Counter(ty_ids).most_common(1)[0][0]}"
    else:
        ty_num = "unknown"

    ctx.results["meta"] = {
        "status": "found",
        "root": str(root),
        "typhoon": ty_num,
        "total": len(found),
        "classified": {k: len(v) for k, v in by_kind.items() if v},
        "station_files": [os.path.basename(f["path"]) for f in by_kind["station"]][:20],
        "surge_files": [os.path.basename(f["path"]) for f in by_kind["surge"]][:10],
        "wave_files": [os.path.basename(f["path"]) for f in by_kind["wave"]][:10],
    }
    return ctx
