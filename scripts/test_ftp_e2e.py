# -*- coding: utf-8 -*-
"""端到端测试：走 FTP 取数的台风期间预报。"""
import sys
import time

sys.path.insert(0, ".")

from orchestrator import engine  # noqa: E402

CASES = [
    ("2403 厦门（本站）", {"disaster": "storm_surge", "region": "厦门", "typhoon": "2403"}),
    ("2403 崇武+晋江+东山", {"disaster": "storm_surge", "region": "福建沿海", "typhoon": "2403"}),
    ("2403 指定日期 7月25日", {"disaster": "storm_surge", "region": "厦门", "typhoon": "2403", "date": "7月25日"}),
    ("1513 厦门", {"disaster": "storm_surge", "region": "厦门", "typhoon": "1513"}),
    ("1808 厦门", {"disaster": "storm_surge", "region": "厦门", "typhoon": "1808"}),
    ("1709 厦门", {"disaster": "storm_surge", "region": "厦门", "typhoon": "1709"}),
]

for desc, slots in CASES:
    slots.setdefault("time_window", "未指定")
    slots.setdefault("risk_type", "general")
    slots.setdefault("date", "")
    slots.setdefault("plot", "")
    t0 = time.time()
    r = engine.run_with_slots(dict(slots), raw=str(slots))
    dt = time.time() - t0
    reply = (r.get("reply") or "").replace("\n", " ")
    print("=" * 90)
    print(f"[{desc}]  {dt:.0f}s  图 {len(r.get('images') or [])} 张")
    # 只打印关键行
    for line in reply.split("  "):
        if any(k in line for k in ("将出现", "预警级别", "| ", "数据范围", "注：", "最高总水位", "风暴增水")):
            print("   ", line[:250])
    for im in (r.get("images") or []):
        print("    img:", im)
