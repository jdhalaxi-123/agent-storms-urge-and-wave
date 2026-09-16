# -*- coding: utf-8 -*-
"""数据落盘位置统一管理（下载的数据、图、简报、日志都放 DATA_ROOT 下）。

目录约定
--------
    <DATA_ROOT>/
      cache/                              从 FTP 下载的数据（按"来源+日期"分好）
        daily/<起报日 YYYYMMDD>/
            surge_point/                  课题三 4 站单点增水（10 KB × 4）
            surge_field/                  课题三 AI 增水场 0.25°（2 MB）
            surge_field_big/              同上的大版（33 MB）
            stations_npy/                 站点序列 npy
            wave_field/                   课题三 AI 海浪场（13 MB）
            wave_point/                   浮标单点波高
            tide/                         天文潮预报
            total_water_field/            总水位场
            wind/  wind_ec/               风场（259 MB / 1059 MB，按需）
        typhoon/<台风号>/
            station_surge/  surge_field/  wave_point/  observation/
            cropped_field/  ortho_field/  mesh/  ensemble/  era5_wind/
        other/<类别>/                     其他零散文件
      inbox/                              人工放进去的数据（如老师微信发的 tif）
      figures/                            生成的图（文件名自带日期/站点）
      briefs/                             Word / Markdown 简报
      logs/                               取数与预热日志

DATA_ROOT 取值顺序
------------------
    1) 环境变量 STORM_DATA_ROOT
    2) 项目 .env 里的 DATA_ROOT
    3) 默认 <项目>/stormdata（E 盘上，紧挨代码）
    4) 退回 <项目>/data
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 默认数据根目录：<项目>/stormdata（在 E 盘上、紧挨代码）
DEFAULT_ROOT = PROJECT_ROOT / "stormdata"
LEGACY_CACHE_DIR = PROJECT_ROOT / "data" / "ftp_cache"


# --------------------------------------------------------------------------- #
# 根目录选择
# --------------------------------------------------------------------------- #
def _env_value(key: str) -> str:
    import os
    v = os.environ.get(key)
    if v:
        return v.strip()
    try:
        from .ftp_client import _load_env
        return ( _load_env().get(key) or "" ).strip()
    except Exception:
        return ""


def _pick_root() -> Path:
    import os
    cand = _env_value("STORM_DATA_ROOT") or _env_value("DATA_ROOT")
    cands: List[Path] = []
    if cand:
        cands.append(Path(cand))
    cands.append(DEFAULT_ROOT)
    cands.append(PROJECT_ROOT / "data")
    for p in cands:
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            continue
    return PROJECT_ROOT / "data"


DATA_ROOT: Path = _pick_root()
CACHE_DIR: Path = DATA_ROOT / "cache"
INBOX_DIR: Path = DATA_ROOT / "inbox"
FIGURES_DIR: Path = DATA_ROOT / "figures"
BRIEFS_DIR: Path = DATA_ROOT / "briefs"
LOGS_DIR: Path = DATA_ROOT / "logs"

# 每日预报相关的类别（决定是否放进 daily/<日期>/ 下）
DAILY_CATEGORIES = {
    "surge_point", "surge_field", "surge_field_big", "stations_npy",
    "wave_field", "wave_point", "tide", "total_water_field", "wind", "wind_ec",
}

# 远程路径关键字 → 类别（按顺序匹配，先命中先用）
CATEGORY_RULES = [
    ("storm_surge_for_spatiotemporal_2/results_atm/stations_nc", "total_water_field"),
    ("storm_surge_for_spatiotemporal_2/results_atm/tide", "tide"),
    ("storm_surge_for_spatiotemporal_2/results_atm", "surge_field_big"),
    ("storm_surge_for_spatiotemporal_1/results_atm", "surge_field"),
    ("storm_surge_for_spatiotemporal_1/results_ec", "surge_field_ec"),
    ("storm_surge_for_spatiotemporal/", "stations_npy"),
    ("storm_surge_point_system", "surge_point"),
    ("AutoWave/res_EC", "wave_field_ec"),
    ("AutoWave", "wave_field"),
    ("wave_for_single_point", "wave_point"),
    ("dataset_GFS_cropped", "cropped_field"),
    ("observation", "observation"),
    ("irregular_surge_Ensemble", "ensemble"),
    ("正交", "ortho_field"),
    ("_irregular", "mesh"),
    ("era5", "era5_wind"),
    ("storm_surge_field", "surge_field"),
    ("storm_surge_point", "station_surge"),
    ("TC_wave_point", "wave_point"),
    ("EC_wind", "wind_ec"),
    ("/wind", "wind"),
    ("/tide", "tide"),
]

_DATE_RE = re.compile(r"(20\d{6})")
_TY_RE = re.compile(r"typhoon_(\w+)")


def category_of(remote: str) -> str:
    """根据远程路径判断数据类别。"""
    r = str(remote).replace("\\", "/")
    for key, cat in CATEGORY_RULES:
        if key in r:
            return cat
    return "misc"


def _date_of(remote: str, name: str) -> str:
    m = _DATE_RE.search(name) or _DATE_RE.search(str(remote))
    return m.group(1) if m else "undated"


def _typhoon_of(remote: str) -> Optional[str]:
    m = _TY_RE.search(str(remote))
    if m:
        return m.group(1)
    m = re.search(r"/(\d{4})_irregular", str(remote))
    return m.group(1) if m else None


def cache_path_for(remote: str) -> Path:
    """远程路径 → 本地缓存路径（按类别/日期/台风号分目录）。

    同名不同台风的大文件（`output_0.nc` / `output_4.nc`）用上级目录名做前缀，
    避免互相覆盖。
    """
    remote = str(remote).strip()
    name = remote.rstrip("/").split("/")[-1]
    if name in ("output_0.nc", "output_4.nc"):
        parent = remote.rstrip("/").split("/")[-2]
        name = f"{parent}__{name}"

    cat = category_of(remote)
    ty = _typhoon_of(remote)
    if ty:
        base = CACHE_DIR / "typhoon" / ty / cat
    elif cat in DAILY_CATEGORIES:
        base = CACHE_DIR / "daily" / _date_of(remote, name) / cat
    else:
        base = CACHE_DIR / "other" / cat
    return base / name


def legacy_cache_paths(remote: str) -> List[Path]:
    """旧版（项目内 data/ftp_cache，扁平命名）里可能存在的同一文件。"""
    parts = [p for p in str(remote).strip("/").split("/") if p]
    safe = "__".join(parts).replace(":", "_").replace("*", "_").replace("?", "_")
    return [LEGACY_CACHE_DIR / safe, LEGACY_CACHE_DIR / parts[-1]]


# --------------------------------------------------------------------------- #
# 建目录
# --------------------------------------------------------------------------- #
DAILY_SUBDIRS = ["surge_point", "surge_field", "surge_field_big", "stations_npy",
                 "wave_field", "wave_point", "tide", "total_water_field", "wind", "wind_ec"]
TYPHOON_SUBDIRS = ["station_surge", "surge_field", "wave_point", "observation",
                   "cropped_field", "ortho_field", "mesh", "ensemble", "era5_wind"]

_TREE_README = """# 风暴潮与海浪智能预报助手 · 数据目录

本目录是 agent **下载数据与产出结果**的统一存放位置。

```
{DATA_ROOT}
├── cache/                 从课题数据库(FTP)按需下载的数据
│   ├── daily/<起报日>/    每日 AI 预报
│   │   ├── surge_point/        4 站单点增水（10 KB×4）
│   │   ├── surge_field/        AI 增水场 0.25°（2 MB）
│   │   ├── surge_field_big/    同上大版（33 MB）
│   │   ├── wave_field/         AI 海浪场（13 MB）
│   │   ├── wave_point/         浮标单点波高
│   │   ├── tide/               天文潮预报
│   │   ├── total_water_field/  总水位场
│   │   └── wind/  wind_ec/     风场（259 MB / 1059 MB，按需）
│   ├── typhoon/<台风号>/   台风个例数据
│   │   ├── station_surge/  surge_field/  wave_point/  observation/
│   │   └── cropped_field/  ortho_field/  mesh/  ensemble/  era5_wind/
│   └── other/             其他零散文件
├── inbox/                 人工放进去的数据（如老师微信发的 tif）
├── figures/               生成的图
├── briefs/                生成的 Word / Markdown 简报
└── logs/                  取数与预热日志
```

- 文件名与 FTP 上保持一致，方便和老师/课题三核对。
- 删除原则：只清 `cache/` 即可，`inbox/` 与 `briefs/` 是人工材料，别删。
- 换机器部署时，可用环境变量 `STORM_DATA_ROOT` 或 `.env` 里的 `DATA_ROOT`
  把数据仓指到别的盘（例如 `D:\\stormdata`）；不指定就用项目内的 `stormdata`。
"""


def ensure_tree(example_date: str = "") -> Dict[str, str]:
    """建好整套目录（含一个示例日期目录），返回各目录路径。"""
    made: Dict[str, str] = {}
    for d in (CACHE_DIR, INBOX_DIR, FIGURES_DIR, BRIEFS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
        made[d.name] = str(d)

    day = example_date or ""
    if day:
        for sub in DAILY_SUBDIRS:
            (CACHE_DIR / "daily" / day / sub).mkdir(parents=True, exist_ok=True)
    for sub in TYPHOON_SUBDIRS:
        (CACHE_DIR / "typhoon" / "_模板" / sub).mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "other" / "misc").mkdir(parents=True, exist_ok=True)

    readme = DATA_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(_TREE_README.format(DATA_ROOT=DATA_ROOT), encoding="utf-8")

    inbox_note = INBOX_DIR / "放这里.txt"
    if not inbox_note.exists():
        inbox_note.write_text(
            "人工获取的数据放这里（例如老师微信发来的天文潮 tif）：\n"
            "  XMN_20260915_20260921.tif   厦门\n"
            "  DSN_20260915_20260921.tif   东山东港\n"
            "  JNJ_20260915_20260921.tif   晋江\n"
            "  CWU_20260915_20260921.tif   崇武（如有）\n",
            encoding="utf-8")

    return made


def tree_text(max_depth: int = 4) -> str:
    """把当前目录树打成文本（供自检/展示）。"""
    lines: List[str] = [str(DATA_ROOT) + "\\"]

    def walk(p: Path, depth: int, prefix: str = ""):
        if depth > max_depth:
            return
        try:
            kids = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except Exception:
            return
        for i, k in enumerate(kids):
            last = i == len(kids) - 1
            branch = "└── " if last else "├── "
            mark = "\\" if k.is_dir() else ""
            lines.append(prefix + branch + k.name + mark)
            if k.is_dir():
                walk(k, depth + 1, prefix + ("    " if last else "│   "))

    walk(DATA_ROOT, 1)
    return "\n".join(lines)


if __name__ == "__main__":
    made = ensure_tree()
    print(f"DATA_ROOT = {DATA_ROOT}")
    for k, v in made.items():
        print(f"  {k}: {v}")
    print()
    print(tree_text())
