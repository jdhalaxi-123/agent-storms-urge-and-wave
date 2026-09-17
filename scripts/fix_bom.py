# -*- coding: utf-8 -*-
"""给 .ps1 补 UTF-8 BOM（PowerShell 5.1 读无 BOM 的 UTF-8 中文脚本会乱码）。

被 preflight 检查出问题时跑这个即可。
用法：python scripts/fix_bom.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


def main() -> int:
    fixed = 0
    for p in ROOT.rglob("*.ps1"):
        if any(x in p.parts for x in (".venv", ".git", "dist")):
            continue
        b = p.read_bytes()
        if b.startswith(BOM):
            continue
        txt = b.decode("utf-8", errors="ignore").lstrip("\ufeff")
        txt = txt.replace("\r\n", "\n").replace("\n", "\r\n")
        p.write_bytes(BOM + txt.encode("utf-8"))
        print(f"  已补 BOM：{p.relative_to(ROOT)}")
        fixed += 1
    print(f"完成，处理 {fixed} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())