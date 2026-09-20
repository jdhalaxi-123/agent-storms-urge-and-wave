#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每日数据自动下载（预热）：FTP 上有新的一期就下到 stormdata，已存在就跳过。

更新规律（2026-09 实测，北京时间）
---------------------------------
    每日风场        /group3/wind                          前一天 22:05~23:32
    AI 增水场        .../storm_surge_for_spatiotemporal_1   当天 14:41（有时早上 07:37）
    AI 海浪场        .../AutoWave/res_ATM                   当天 14:38（有时早上 06:18）
    站点单点增水     .../storm_surge_point_system/nc_file   当天 14:38
    增水场大版/站点npy .../storm_surge_for_spatiotemporal_2 当天 14:38
    海浪单点         .../wave_for_single_point/outputs      当天 14:41
    ECMWF 风场       /group3/EC_wind                        当天 10:59（1059 MB，默认不下）

用法
----
    python scripts/daily_prewarm.py                 # 默认：含风场，保留最近 30 天风场
    python scripts/daily_prewarm.py --no-wind       # 不自动下 259 MB 的风场
    python scripts/daily_prewarm.py --keep-wind-days 15
    python scripts/daily_prewarm.py --check-only    # 只看有没有新的，不下载
    python scripts/daily_prewarm.py --quiet         # 定时任务用：只写日志

退出码：0 正常（含"没有新数据"），1 出错。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import ftp_catalog as fc  # noqa: E402
from orchestrator import paths  # noqa: E402

DF = "/group3/ATM_new/dailyforecast"
POINT_DIR = f"{DF}/storm_surge_point_system/nc_file"
SURGE_FIELD_DIR = f"{DF}/storm_surge_for_spatiotemporal_1/results_atm"
WAVE_FIELD_DIR = f"{DF}/AutoWave/res_ATM"
TOTAL_DIR = f"{DF}/storm_surge_for_spatiotemporal_2/results_atm"
WAVE_POINT_DIR = f"{DF}/wave_for_single_point/outputs/nc_file"
WIND_DIR = "/group3/wind"

STATIONS = ["XMN", "CWU", "JNJ", "DSN"]

LOG_FILE = paths.LOGS_DIR / "prewarm.log"


def log(msg: str, quiet: bool = False) -> None:
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if not quiet:
        print(line)


def newest(dirpath: str, pattern: str, ftp=None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """目录里日期最大的那个文件/目录 → (日期, 条目)。"""
    entries = fc._ls(ftp, dirpath) if ftp is not None else _ls_standalone(dirpath)
    best: Optional[Tuple[str, Dict[str, Any]]] = None
    for e in entries:
        m = re.search(pattern, e["name"])
        if not m:
            continue
        d = m.group(1)
        if best is None or d > best[0]:
            best = (d, e)
    return best


def _ls_standalone(dirpath: str) -> List[Dict[str, Any]]:
    ftp = fc.ftp_client._connect()
    try:
        return fc._ls(ftp, dirpath)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def already(local_remote: str) -> bool:
    return paths.cache_path_for(local_remote).exists()


def grab(remote: str, size: int, quiet: bool, label: str) -> bool:
    if already(remote):
        return False
    local = fc.fetch(remote, expected_size=size, quiet=True)
    if local:
        log(f"  ↓ {label}: {Path(local).name}  ({size/1e6:.2f} MB) → {local}", quiet)
        return True
    log(f"  ✗ {label}: 下载失败 {remote}", quiet)
    return False


def prune_wind(keep_days: int, quiet: bool) -> int:
    """只保留最近 keep_days 天的风场文件（259 MB/天，很大）。"""
    if keep_days <= 0:
        return 0
    root = paths.CACHE_DIR / "daily"
    if not root.exists():
        return 0
    files = sorted(root.glob("*/wind/atm_forecast_*.nc"),
                   key=lambda p: p.parent.parent.name)
    removed = 0
    for p in files[:-keep_days] if len(files) > keep_days else []:
        try:
            mb = p.stat().st_size / 1e6
            p.unlink()
            removed += 1
            log(f"  ⌫ 清理旧风场 {p.parent.parent.name}/{p.name} ({mb:.0f} MB)", quiet)
        except Exception:
            pass
    return removed


def main() -> int:
    ap = argparse.ArgumentParser(description="每日数据自动下载")
    ap.add_argument("--no-wind", action="store_true", help="不下载风场（259 MB/天）")
    ap.add_argument("--keep-wind-days", type=int, default=30,
                    help="风场保留天数（默认 30，约 7.8 GB）")
    ap.add_argument("--check-only", action="store_true", help="只检查，不下载")
    ap.add_argument("--quiet", action="store_true", help="只写日志，不打印")
    args = ap.parse_args()

    paths.ensure_tree()
    log("===== 自动下载开始 =====", args.quiet)
    got = 0
    ftp = fc.ftp_client._connect()
    try:
        # ① 站点单点增水
        entries = fc._ls(ftp, POINT_DIR)
        sizes = {e["name"]: e["size"] for e in entries}
        all_dates = sorted({re.search(r"_(\d{8})-", n).group(1)
                            for n in sizes if re.search(r"_(\d{8})-", n)})
        day = all_dates[-1] if all_dates else ""
        if day:
            log(f"① 站点单点增水：最新起报 {day}", args.quiet)
            for st in STATIONS:
                for n in [x for x in sizes if f"_sp_{st}_{day}-" in x]:
                    if not args.check_only and grab(f"{POINT_DIR}/{n}", sizes[n],
                                                    args.quiet, f"站点增水 {st}"):
                        got += 1
        else:
            log("① 站点单点增水：未找到", args.quiet)

        # ② AI 增水场
        b = newest(SURGE_FIELD_DIR, r"atm_forecast_(\d{8})", ftp)
        if b:
            day = b[0]
            sub = fc._ls(ftp, f"{SURGE_FIELD_DIR}/atm_forecast_{day}")
            f = next((e for e in sub if e["name"].startswith("surge_pred_atm_forecast")), None)
            log(f"② AI 增水场：最新起报 {day}", args.quiet)
            if f and not args.check_only:
                got += grab(f["path"], f["size"], args.quiet, "AI 增水场")
        else:
            log("② AI 增水场：未找到", args.quiet)

        # ③ AI 海浪场
        w = newest(WAVE_FIELD_DIR, r"(\d{8})_wave_forecast_1h\.nc", ftp)
        if w:
            log(f"③ AI 海浪场：最新起报 {w[0]}", args.quiet)
            if not args.check_only:
                got += grab(w[1]["path"], w[1]["size"], args.quiet, "AI 海浪场")
        else:
            log("③ AI 海浪场：未找到", args.quiet)

        # ④ 站点序列 npy + **精细增水场**（0.01°，33 MB，小区域出图用）
        t = newest(TOTAL_DIR, r"surge_stations_(\d{8})\.npy", ftp)
        if t:
            log(f"④ 站点序列 npy：最新 {t[0]}", args.quiet)
            if not args.check_only:
                got += grab(t[1]["path"], t[1]["size"], args.quiet, "站点 npy")
        fp = newest(TOTAL_DIR, r"surge_predicted_(\d{8})\.nc", ftp)
        if fp:
            log(f"④b 精细增水场 0.01°：最新 {fp[0]}（{fp[1]['size']/1e6:.0f} MB）", args.quiet)
            if not args.check_only:
                got += grab(fp[1]["path"], fp[1]["size"], args.quiet, "精细增水场")

        # ⑤ 海浪单点（一整天的目录，每个约 11 KB）
        wp = newest(WAVE_POINT_DIR, r"(\d{8})", ftp)
        if wp:
            log(f"⑤ 海浪单点：最新 {wp[0]}", args.quiet)
            if not args.check_only:
                sub = fc._ls(ftp, wp[1]["path"])
                n_ok = 0
                for e in sub:
                    if e["dir"]:
                        continue
                    if grab(e["path"], e["size"], args.quiet, "海浪单点"):
                        n_ok += 1
                got += n_ok
                if n_ok:
                    log(f"  （海浪单点新增 {n_ok} 个站）", args.quiet)

        # ⑥ 每日风场（259 MB）
        if args.no_wind:
            log("⑥ 每日风场：已按 --no-wind 跳过", args.quiet)
        else:
            wd = newest(WIND_DIR, r"atm_forecast_(\d{8})\.nc", ftp)
            if wd:
                log(f"⑥ 每日风场：最新 {wd[0]}（{wd[1]['size']/1e6:.0f} MB）", args.quiet)
                if not args.check_only:
                    got += grab(wd[1]["path"], wd[1]["size"], args.quiet, "每日风场")
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    pruned = prune_wind(args.keep_wind_days, args.quiet)
    info = fc.cache_info()
    log(f"===== 结束：新增 {got} 个文件，清理旧风场 {pruned} 个，"
        f"缓存 {info['files']} 个 / {info['mb']:.0f} MB =====", args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
