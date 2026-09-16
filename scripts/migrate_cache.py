#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把旧版扁平缓存（项目内 data/ftp_cache）一次性搬进数据仓 stormdata/cache。

旧命名规则：`group3__dailyforecast__...__文件.nc`（远程路径用 __ 连接）。
能反解出远程路径的就搬，搬不了的（早期只存 basename 的）留在原地并报告。

用法：
    python scripts/migrate_cache.py            # 实际搬迁
    python scripts/migrate_cache.py --dry-run  # 只看会搬到哪
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import paths  # noqa: E402

DRY = "--dry-run" in sys.argv


def main():
    legacy = paths.LEGACY_CACHE_DIR
    if not legacy.exists():
        print(f"没有旧缓存目录：{legacy}")
        return

    files = sorted(f for f in legacy.iterdir() if f.is_file())
    print(f"旧缓存：{legacy}")
    print(f"共 {len(files)} 个文件，{sum(f.stat().st_size for f in files)/1e6:.1f} MB\n")

    moved = skipped = failed = 0
    for f in files:
        name = f.name
        if "__" not in name:
            skipped += 1
            continue
        remote = "/" + "/".join(name.split("__"))
        target = paths.cache_path_for(remote)
        if DRY:
            print(f"  {name}\n     → {target}")
            moved += 1
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == f.stat().st_size:
                f.unlink()
            else:
                f.replace(target)
            moved += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {e}")

    print(f"\n{'（dry-run）' if DRY else ''}搬迁 {moved} 个，"
          f"无法反解保留 {skipped} 个，失败 {failed} 个")
    if not DRY and moved:
        from orchestrator import ftp_catalog as fc
        print(f"缓存统计：{fc.cache_info()}")


if __name__ == "__main__":
    main()
