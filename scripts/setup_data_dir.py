#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""建好数据目录树（默认 <项目>\\stormdata），并做一次取数落盘自检。

用法：
    python scripts/setup_data_dir.py                # 建目录 + 打印目录树
    python scripts/setup_data_dir.py --fetch 20260915   # 顺带下几个小文件验证落盘位置
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import paths  # noqa: E402


def main():
    example = ""

    args = sys.argv[1:]
    do_fetch = "--fetch" in args
    if do_fetch:
        idx = args.index("--fetch")
        if idx + 1 < len(args):
            example = args[idx + 1]

    print("=" * 70)
    made = paths.ensure_tree(example_date=example)
    print(f"DATA_ROOT = {paths.DATA_ROOT}")
    print(f"旧缓存位置 = {paths.LEGACY_CACHE_DIR}")
    for k, v in made.items():
        print(f"  ✓ {k}: {v}")

    if do_fetch:
        import datetime as _dt
        from orchestrator import ftp_catalog as fc
        day = example or "20260915"
        end = (_dt.datetime.strptime(day, "%Y%m%d") + _dt.timedelta(days=6)).strftime("%Y%m%d")
        print("\n" + "=" * 70)
        print(f"取数落盘自检（只下小文件）：{day} ~ {end}")
        targets = [
            f"/group3/dailyforecast/storm_surge_point_system/nc_file/"
            f"storm_surge_forecast_sp_XMN_{day}-{end}.nc",
            f"/group3/dailyforecast/storm_surge_point_system/nc_file/"
            f"storm_surge_forecast_sp_CWU_{day}-{end}.nc",
        ]
        # 台风个例：从目录里真实挑一个小文件（站点增水 8.5 KB）
        try:
            cat = fc.catalog("2403")
            st = cat.get("sources", {}).get("station_surge", {})
            xmn = (st.get("stations") or {}).get("XMN") or []
            if xmn:
                targets.append(xmn[-1]["path"])
        except Exception as e:
            print(f"  （台风个例清单获取失败：{e}）")

        for remote in targets:
            local = fc.fetch(remote)
            print(f"  {'✅' if local else '❌'} {remote}")
            if local:
                print(f"      → {local}")

    print("\n" + "=" * 70)
    print(paths.tree_text(max_depth=3))
    try:
        from orchestrator import ftp_catalog as fc
        print(f"\n缓存统计: {fc.cache_info()}")
    except Exception as e:
        print(f"缓存统计失败: {e}")


if __name__ == "__main__":
    main()
