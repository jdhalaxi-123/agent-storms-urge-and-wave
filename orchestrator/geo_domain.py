"""覆盖范围判定：用户问的地点是否在本系统数据覆盖区内。

用途：
    当用户询问超出覆盖范围的地点（如上海、青岛、大连）时，
    不展示任何数据/图表，只返回文字说明，避免给出无依据的结果。

覆盖范围依据实际数据边界（取各数据源交集/并集的保守范围）：
    - FTP/Ensemble 风暴潮三角网格：114.5~127.2°E，17.3~29.4°N
    - 2526 场数据 output_0/4   ：113~128°E，18~30°N
    - 2526 ERA5 风场           ：112~129°E，17~31°N
    本判定取：114.5~127.5°E，17.0~29.5°N（台湾海峡及福建、浙南沿海）
"""
from __future__ import annotations

from typing import Optional, Tuple

# 覆盖区（保守范围）
LON_MIN, LON_MAX = 114.5, 127.5
LAT_MIN, LAT_MAX = 17.0, 29.5

DOMAIN_DESC = "114.5°E ~ 127.5°E，17.0°N ~ 29.5°N（台湾海峡及福建、浙江南部沿海）"

# 系统当前支持查询的站点（与 modules/geo_stats.py 的 SITES 对应）
SUPPORTED_STATIONS = "厦门、崇武、晋江、东山东港"

# 沿海/近海地点坐标字典（用于判断是否在覆盖区内）
# 坐标为近似值，仅用于范围判定，不用于精确采样
KNOWN_PLACES = {
    # ===== 覆盖区内（台湾海峡及福建、浙南沿海）=====
    "厦门": (118.10, 24.48),
    "厦门港": (118.07, 24.45),
    "鼓浪屿": (118.07, 24.45),
    "同安湾": (118.15, 24.55),
    "崇武": (119.00, 25.00),
    "晋江": (118.50, 24.50),
    "石狮": (118.65, 24.75),
    "东山": (117.50, 23.75),
    "东山东港": (117.50, 23.75),
    "漳州": (117.65, 24.50),
    "漳浦": (117.62, 23.99),
    "泉州": (118.68, 24.87),
    "惠安": (118.80, 24.95),
    "湄洲湾": (119.10, 25.10),
    "莆田": (119.10, 25.43),
    "平潭": (119.79, 25.50),
    "福清": (119.38, 25.72),
    "福州": (119.45, 26.05),
    "宁德": (119.55, 26.65),
    "三沙": (120.20, 26.90),
    "温州": (120.70, 28.00),
    "台州": (121.45, 28.65),
    "台湾海峡": (119.00, 24.00),
    "台湾海峡北部": (120.00, 25.00),
    "台湾海峡南部": (118.50, 23.00),
    "澎湖": (119.57, 23.57),
    "金门": (118.32, 24.44),
    "马祖": (119.95, 26.15),
    # ===== 覆盖区外（用于明确拒绝）=====
    "上海": (121.50, 31.23),
    "长江口": (121.90, 31.40),
    "杭州湾": (121.20, 30.40),
    "宁波": (121.90, 29.90),
    "舟山": (122.20, 30.02),
    "嘉兴": (120.90, 30.60),
    "连云港": (119.30, 34.60),
    "青岛": (120.38, 36.07),
    "烟台": (121.40, 37.50),
    "威海": (122.10, 37.50),
    "大连": (121.60, 38.90),
    "天津": (117.70, 39.00),
    "秦皇岛": (119.60, 39.90),
    "深圳": (114.06, 22.54),
    "香港": (114.17, 22.30),
    "广州": (113.30, 23.10),
    "珠海": (113.55, 22.27),
    "珠江口": (113.80, 22.30),
    "湛江": (110.40, 21.20),
    "海口": (110.30, 20.05),
    "三亚": (109.50, 18.25),
    "北海": (109.10, 21.48),
    "南海": (114.00, 16.00),
    "东海": (124.00, 30.00),
    "黄海": (122.00, 34.00),
    "渤海": (119.50, 38.50),
    "日本": (135.00, 35.00),
    "韩国": (127.00, 36.00),
    "菲律宾": (121.00, 14.00),
    "马尼拉": (120.98, 14.60),
    "关岛": (144.80, 13.50),
}


def _norm(s: str) -> str:
    return str(s or "").strip().replace(" ", "").replace("附近", "").replace("海域", "").replace("沿海", "").replace("站", "")


def locate(region: str) -> Tuple[Optional[str], Optional[tuple]]:
    """在字典中匹配地点名（最长匹配优先）。

    返回 (匹配到的地点名, 坐标) 或 (None, None)。
    """
    r = str(region or "")
    if not r:
        return None, None
    # 最长名称优先，避免"台湾海峡北部"被"台湾海峡"抢先
    for name in sorted(KNOWN_PLACES.keys(), key=len, reverse=True):
        if name and name in r:
            return name, KNOWN_PLACES[name]
    # 归一化后再试
    r2 = _norm(r)
    for name in sorted(KNOWN_PLACES.keys(), key=len, reverse=True):
        if name and _norm(name) and _norm(name) in r2:
            return name, KNOWN_PLACES[name]
    return None, None


def in_domain(lon: float, lat: float) -> bool:
    return (LON_MIN <= lon <= LON_MAX) and (LAT_MIN <= lat <= LAT_MAX)


def check_region(region: str, lon=None, lat=None) -> dict:
    """检查请求地点是否在覆盖区内。

    返回：
        {"ok": True,  "matched": 地点名或None, "coord": (lon,lat)或None}
        {"ok": False, "matched": 地点名, "coord": (lon,lat), "message": 拒绝说明}
    """
    # 1) 若直接给了经纬度，按坐标判定
    if lon is not None and lat is not None:
        try:
            lo, la = float(lon), float(lat)
            if not in_domain(lo, la):
                return {
                    "ok": False,
                    "matched": f"({lo:.2f}°E, {la:.2f}°N)",
                    "coord": (lo, la),
                    "message": _refuse_msg(f"坐标 ({lo:.2f}°E, {la:.2f}°N)"),
                }
            return {"ok": True, "matched": f"({lo:.2f}°E, {la:.2f}°N)", "coord": (lo, la)}
        except (TypeError, ValueError):
            pass

    # 2) 按地点名判定
    name, coord = locate(region)
    if name and coord and not in_domain(*coord):
        return {"ok": False, "matched": name, "coord": coord, "message": _refuse_msg(name)}
    return {"ok": True, "matched": name, "coord": coord}


def _refuse_msg(place: str) -> str:
    return (
        f"抱歉，「{place}」不在本系统当前的预报覆盖范围内，因此无法提供该海域的数据与图表。\n\n"
        f"**覆盖范围**：{DOMAIN_DESC}\n"
        f"**当前可查询的站点**：{SUPPORTED_STATIONS}\n\n"
        f"如需其他海域的预报，请提供覆盖范围内的位置。"
    )
