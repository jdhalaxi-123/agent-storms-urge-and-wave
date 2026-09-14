# -*- coding: utf-8 -*-
"""测试：10 个完整台风的台风期间数据取数。"""
import sys
import time

import numpy as np

sys.path.insert(0, ".")
from modules import ftp_typhoon as ft  # noqa: E402

print("完整台风清单:", ft.COMPLETE_TYPHOONS)

TY = "2403"
t0 = time.time()

print(f"\n{'='*88}\n【① 站点增水过程】{TY}\n{'='*88}")
st = ft.load_station_surge(TY)
for s in st:
    arr = np.asarray([v for v in s["series_cm"] if v is not None], dtype=float)
    if arr.size == 0:
        continue
    k = int(np.argmax(arr))
    print(f"  {s['name']:6s}({s['code']}) 共 {len(arr):3d} 小时  "
          f"最大增水 {arr.max():6.1f} cm  最小 {arr.min():6.1f} cm  "
          f"起始 {s['start_dt']}  峰值第{k}小时  文件数 {s['source_files']}")
print(f"  耗时 {time.time()-t0:.1f}s")

t0 = time.time()
print(f"\n{'='*88}\n【② 全场增水（2MB）】{TY}\n{'='*88}")
f = ft.load_surge_field(TY)
if f:
    print(f"  网格 {f['lat'].size}×{f['lon'].size}  时段 {f['n_hours']} 小时  起始 {f['start_dt']}")
    print(f"  全场最大增水 {f['max_cm']} cm  峰值时刻 {f['peak_dt']}")
    for name, (lo, la) in {"厦门": (118.25, 24.50), "崇武": (119.0, 25.0),
                           "福州": (119.45, 26.05), "澎湖": (119.57, 23.57)}.items():
        sp = ft.sample_field(f, lo, la)
        print(f"    {name:5s} → 格点({sp['grid_lon']},{sp['grid_lat']}) 距{sp['dist_km']:5.1f}km  "
              f"最大增水 {sp['max_surge_cm']} cm")
print(f"  耗时 {time.time()-t0:.1f}s")

t0 = time.time()
print(f"\n{'='*88}\n【③ 浮标波高过程】{TY}\n{'='*88}")
wp = ft.load_wave_point(TY)
print(f"  共 {len(wp)} 个浮标站，波高最大的前 5 个：")
for r in wp[:5]:
    print(f"    {r['station']:8s} 最大有效波高 {r['max_hs_m']:6.2f} m  "
          f"→ 海浪{ft.judge_wave(r['max_hs_m'])}预警  起始 {r['start_dt']}")
print(f"  耗时 {time.time()-t0:.1f}s")

t0 = time.time()
print(f"\n{'='*88}\n【④ 实测观测】{TY}\n{'='*88}")
ob = ft.load_observation(TY)
if ob:
    print(f"  浮标站 {len(ob['sta_id'])} 个，潮位站 {len(ob['sta_id_tide'])} 个  起始 {ob['start_dt']}")
    print(f"  实测最大波高 {ob.get('wave_H_max')} m   实测潮位最大 {ob.get('tide_tide_max')} m")
    print(f"  站号: {ob['sta_id'][:6]} …")
print(f"  耗时 {time.time()-t0:.1f}s")

print(f"\n{'='*88}\n【⑤ 天文潮 + 总水位（裁剪场）】{TY}\n{'='*88}")
t0 = time.time()
tt = ft.load_tide_total(TY, [{"name": "厦门", "lon": 118.25, "lat": 24.50},
                             {"name": "崇武", "lon": 119.00, "lat": 25.00}])
if tt:
    print(f"  起始 {tt['start_dt']}  步长 {tt['step_hours']}h  数据源: {tt['source_kind']}")
    for p in tt["points"]:
        tide = np.asarray([v for v in p["series_tide_cm"] if v is not None], float)
        tot = np.asarray([v for v in p["series_total_cm"] if v is not None], float)
        sur = np.asarray([v for v in p["series_surge_cm"] if v is not None], float)
        if tide.size == 0:
            print(f"    {p['name']}: 无有效值（格点在陆地/无效区）")
            continue
        print(f"    {p['name']:5s} 格点({p['grid_lon']},{p['grid_lat']}) 距{p['grid_dist_km']}km")
        print(f"          天文潮 {tide.min():7.1f} ~ {tide.max():7.1f} cm（潮差 {tide.max()-tide.min():.1f}）")
        print(f"          总水位 {tot.min():7.1f} ~ {tot.max():7.1f} cm")
        print(f"          增 水  {sur.min():7.1f} ~ {sur.max():7.1f} cm  ← 相减得到")
else:
    print("  裁剪场不可用")
print(f"  耗时 {time.time()-t0:.1f}s")
print("\n缓存:", __import__("orchestrator.ftp_catalog", fromlist=["x"]).cache_info())
