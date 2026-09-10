"""端到端测试：任意经纬度 + 地名采样。"""
import json
import sys
import time

sys.path.insert(0, ".")

from orchestrator import engine  # noqa: E402

CASES = [
    # (说明, 槽位)
    ("2526 福州 地名", {"disaster": "storm_surge", "region": "福州"}),
    ("2526 澎湖 地名", {"disaster": "storm_surge", "region": "澎湖"}),
    ("2526 任意经纬度 120.5E/25.5N", {"disaster": "storm_surge", "region": "(120.50°E, 25.50°N)", "lon": 120.5, "lat": 25.5}),
    ("2526 厦门(本站)", {"disaster": "storm_surge", "region": "厦门"}),
    ("2526 温州 地名", {"disaster": "storm_surge", "region": "温州"}),
    ("2526 汕头 地名", {"disaster": "storm_surge", "region": "汕头"}),
    ("上海(超范围)", {"disaster": "storm_surge", "region": "上海"}),
    ("台湾(大范围)", {"disaster": "storm_surge", "region": "台湾"}),
]

for desc, slots in CASES:
    slots.setdefault("time_window", "未指定")
    slots.setdefault("risk_type", "general")
    slots.setdefault("typhoon", "")
    slots.setdefault("date", "")
    slots.setdefault("plot", "")
    t0 = time.time()
    r = engine.run_with_slots(dict(slots), raw=str(slots))
    dt = time.time() - t0
    geo = r.get("meta", {})
    reply = (r.get("reply") or "").replace("\n", " ")
    print("=" * 78)
    print(f"[{desc}] 用时 {dt:.1f}s  图片 {len(r.get('images') or [])} 张")
    print("  reply:", reply[:420])
    if r.get("images"):
        for im in r["images"]:
            print("   img:", im)
