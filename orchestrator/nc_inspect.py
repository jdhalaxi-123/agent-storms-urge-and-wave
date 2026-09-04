"""NC 数据探查工具：读文件、识别变量、体检报告。

不依赖编排引擎，可单独命令行使用：
    python -m orchestrator.nc_inspect <nc文件或目录> [--limit N]

用途：
    - 自动识别变量名/维度/坐标（不用预知变量命名）
    - 给出时空范围、缺测情况、字段单位
    - 为 meta/geo_stats 真实实现提供结构依据
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def inspect_file(path: Path, limit_rows: int = 5) -> Dict[str, Any]:
    """检查单个 NC 文件，返回结构报告（纯 dict，可 JSON 序列化）。"""
    import xarray as xr

    ds = xr.open_dataset(path, decode_cf=True)
    try:
        info: Dict[str, Any] = {
            "file": str(path),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
            "coords": {},
            "variables": {},
        }

        # 坐标
        for name, c in ds.coords.items():
            info["coords"][str(name)] = {
                "dims": list(c.dims),
                "size": c.size,
                "dtype": str(c.dtype),
                "values_head": _head(c.values, limit_rows),
            }

        # 变量
        for name, var in ds.variables.items():
            if name in ds.coords:
                continue
            info["variables"][str(name)] = {
                "dims": list(var.dims),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "attrs": {k: str(v) for k, v in var.attrs.items()},
                "nan_ratio": _nan_ratio(var),
            }

        # 全局属性
        info["attrs"] = {str(k): str(v) for k, v in ds.attrs.items()}
        return info
    finally:
        ds.close()


def _head(values, n: int = 5) -> List[Any]:
    """取前 n 个值，datetime 转字符串。"""
    try:
        arr = values.ravel()
        out = []
        for i in range(min(n, len(arr))):
            v = arr[i]
            if hasattr(v, "strftime"):
                v = v.strftime("%Y-%m-%d %H:%M")
            out.append(str(v))
        return out
    except Exception:
        return []


def _nan_ratio(var) -> float:
    import numpy as np

    try:
        data = var.values
        if np.issubdtype(data.dtype, np.number):
            return round(float(np.isnan(data).mean()), 4)
        return 0.0
    except Exception:
        return -1.0


def is_file_locked(path: Path) -> bool:
    """探测文件是否被其他进程占用（如下载中）。"""
    try:
        with open(path, "rb"):
            return False
    except (PermissionError, OSError):
        return True


def inspect_dir(path: Path, limit_rows: int = 5) -> List[Dict[str, Any]]:
    """扫描目录下所有 .nc 文件。

    仍在写入/被占用的文件会跳过并在返回值里以 "skipped" 标注。
    """
    files = sorted(p for p in path.rglob("*.nc") if p.is_file() and p.stat().st_size > 0)
    if not files:
        return []
    locked = [p for p in files if is_file_locked(p)]
    if locked:
        names = ", ".join(p.name for p in locked)
        # 直接抛出带说明的异常，调用方决定如何降级
        raise RuntimeError(f"以下文件仍被占用（可能下载未完成）: {names}")
    return [inspect_file(f, limit_rows) for f in files]


def _dump_json(obj: Any, path: Optional[Path] = None) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if path:
        path.write_text(s, encoding="utf-8")
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="NC 数据体检")
    ap.add_argument("target", help="NC文件 或 包含nc文件的目录")
    ap.add_argument("--limit", type=int, default=5, help="坐标取值展示条数")
    ap.add_argument("--json-out", type=str, default="", help="另存报告到json文件")
    args = ap.parse_args()

    target = Path(args.target)
    if target.is_dir():
        reports = inspect_dir(target, args.limit)
    else:
        reports = [inspect_file(target, args.limit)]

    for r in reports:
        print(_dump_json(r, Path(args.json_out) if args.json_out else None))
        print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
