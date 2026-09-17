# -*- coding: utf-8 -*-
"""检查画图相关依赖是否就绪（新电脑照这个清单装）。"""
from __future__ import annotations

import importlib

MODS = ["matplotlib", "cartopy", "shapely", "pyproj", "netCDF4", "xarray", "gradio", "docx"]

print("画图/数据依赖检查：")
bad = []
for m in MODS:
    try:
        mod = importlib.import_module(m)
        ver = getattr(mod, "__version__", "?")
        print(f"  [OK]   {m:<12} {ver}")
    except Exception as e:  # noqa: BLE001
        bad.append(m)
        print(f"  [MISS] {m:<12} {type(e).__name__}: {e}")
print()
if bad:
    print("缺少：" + ", ".join(bad))
    print("修复命令（项目目录下执行）：")
    print("  .venv\\Scripts\\python.exe -m pip install " + " ".join(bad)
          + " -i https://pypi.tuna.tsinghua.edu.cn/simple")
else:
    print("全部就绪 ✅")
