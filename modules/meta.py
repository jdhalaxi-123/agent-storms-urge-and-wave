"""模块① Meta 分析：扫描 / 管理 NC 数据。

真实实现：按「各课题文件路径及数据格式约定」扫描本地数据目录，
按「灾种 + 数据来源(数值/AI/融合)」匹配文件，登记到 ctx.files。

数据目录约定（可被环境变量 STORM_DATA_DIR 覆盖）：
    <项目根>/data/                        # 数据仓库根
      ├── 2526/                           # 按台风编号的文件夹
      │     ├── output_0.nc               # 课题一·风暴潮场（正交）
      │     ├── output_4.nc
      │     └── ...
      ├── wind/typhoon_2526/atm_forecast_*.nc         # 风场
      ├── wave/typhoon_2526/M1_wav_*.nc               # 海浪场
      └── ...
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from orchestrator.contract import ModuleContext


def data_root() -> Path:
    """数据仓库根目录，可用环境变量覆盖。"""
    env = os.environ.get("STORM_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def scan(folder: Path) -> List[Dict[str, Any]]:
    """扫描一个目录（或数据仓库根），列出所有非空 nc 文件。"""
    if not folder.exists():
        return []
    files = [
        p
        for p in folder.rglob("*.nc")
        if p.is_file() and p.stat().st_size > 0
    ]
    return [
        {
            "path": str(p),
            "name": p.name,
            "rel": str(p.relative_to(folder)) if p.is_relative_to(folder) else p.name,
            "size_mb": round(p.stat().st_size / 1024 / 1024, 2),
        }
        for p in sorted(files)
    ]


def run(ctx: ModuleContext) -> ModuleContext:
    region = ctx.request.get("region", "未知海域")
    tw = ctx.request.get("time_window", "未指定")

    root = data_root()
    found = scan(root)

    # 按文件名特征分类（约定：output_* 为风暴潮场，M1/R1_wav 为海浪，atm_forecast 为风）
    surge = [f for f in found if "output_" in f["name"] or "storm_surge" in f["name"].lower()]
    wave = [f for f in found if "wav" in f["name"].lower()]
    wind = [f for f in found if "wind" in f["name"].lower()]

    if found:
        # 真实数据已就位：登记路径（优先取 output_0 / output_4 作为风暴潮代表）
        selects = {
            "surge": surge,
            "wave": wave,
            "wind": wind,
        }
        ctx.files["surge_files"] = [f["path"] for f in surge]
        ctx.files["wave_files"] = [f["path"] for f in wave]
        ctx.files["wind_files"] = [f["path"] for f in wind]
        # 主风暴潮文件约定为 output_0.nc（正交分量0），output_4.nc 为分量4
        for f in surge:
            if f["name"] == "output_0.nc":
                ctx.files["nc_forecast_num"] = f["path"]
            elif f["name"] == "output_4.nc":
                ctx.files["nc_forecast_num_alt"] = f["path"]

        ctx.results["meta"] = {
            "status": "found",
            "root": str(root),
            "total": len(found),
            "classified": {
                "surge": len(surge),
                "wave": len(wave),
                "wind": len(wind),
            },
            "files": found,
        }
    else:
        # 数据未就位：降级占位，保持链路可跑
        ctx.files["nc_forecast_num"] = f"E:/data/{region}_数值模式_{tw}.nc"
        ctx.files["nc_forecast_ai"] = f"E:/data/{region}_智能预报_{tw}.nc"
        ctx.results["meta"] = {
            "status": "placeholder",
            "root": str(root),
            "matched": [],
        }
    return ctx
