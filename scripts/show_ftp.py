# -*- coding: utf-8 -*-
"""打印 FTP 连接信息（供在另一台电脑上照抄）。密码按需显示。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    show = "--show-pass" in sys.argv
    env = ROOT / ".env"
    cfg = {}
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("FTP_") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()

    print("=" * 60)
    print("FTP 连接信息（照抄到另一台电脑的 .env）")
    print("=" * 60)
    for k in ("FTP_HOST", "FTP_PORT", "FTP_USER"):
        print(f"  {k} = {cfg.get(k, '(缺失)')}")
    pwd = cfg.get("FTP_PASS", "")
    if show:
        print(f"  FTP_PASS = {pwd}")
    else:
        print(f"  FTP_PASS = {'*' * max(len(pwd) - 4, 0)}{pwd[-4:]}  "
              f"（共 {len(pwd)} 位；加 --show-pass 显示完整值）")
    print("\n  密码特征检查：")
    print(f"    长度 {len(pwd)}")
    print(f"    含感叹号 ! ：{'是（cmd 里可能被吞，务必用引号或交互输入）' if '!' in pwd else '否'}")
    print(f"    含空格/引号：{'是 ⚠️ 需要引号包裹' if any(c.isspace() or c in chr(34) + chr(39) for c in pwd) else '否'}")
    print("\n  可直接粘贴到新电脑 .env 的四行：")
    print("-" * 60)
    for k in ("FTP_HOST", "FTP_PORT", "FTP_USER", "FTP_PASS"):
        print(f"{k}={cfg.get(k, '')}")
    print("-" * 60)


if __name__ == "__main__":
    main()
