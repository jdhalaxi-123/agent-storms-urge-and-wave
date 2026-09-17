# -*- coding: utf-8 -*-
"""配置 FTP 连接信息到 .env（可交互，也可带参数一条命令搞定）。

交互式（双击 5-配置FTP.bat 即可）：
    python deploy/setup_ftp.py

一条命令：
    python deploy/setup_ftp.py --host 120.42.36.229 --port 22210 --user zdyfsjgx --pass 密码

行为：
    - 读现有 .env（没有就从 .env.example 复制），只改 FTP_* 四行，其余原样保留
    - 改动前备份为 .env.bak.<时间戳>
    - 写完自动跑一次 scripts/check_ftp.py 验证是否连得上
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

DEFAULT_HOST = "120.42.36.229"
DEFAULT_PORT = "22210"


def upsert(lines: list, key: str, value: str) -> list:
    """把 KEY=value 写进配置行（有则替换，无则追加）。"""
    out, done = [], False
    for ln in lines:
        if ln.strip().startswith(f"{key}=") or ln.strip().startswith(f"# {key}="):
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="配置 FTP 连接信息")
    ap.add_argument("--host", default="")
    ap.add_argument("--port", default="")
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="pwd", default="")
    ap.add_argument("--no-check", action="store_true", help="写完后不跑自检")
    args = ap.parse_args()

    host = args.host or input(f"FTP 服务器地址 [{DEFAULT_HOST}]: ").strip() or DEFAULT_HOST
    port = args.port or input(f"FTP 端口（注意不是 21）[{DEFAULT_PORT}]: ").strip() or DEFAULT_PORT
    user = args.user or input("FTP 账号: ").strip()
    pwd = args.pwd or input("FTP 密码: ").strip()
    if not (host and port and user and pwd):
        print("❌ 四项都要填：服务器地址 / 端口 / 账号 / 密码")
        return 1

    if not ENV.exists():
        if EXAMPLE.exists():
            shutil.copy2(EXAMPLE, ENV)
            print(f"已从 .env.example 生成 {ENV.name}")
        else:
            ENV.write_text("", encoding="utf-8")
            print(f"已新建 {ENV.name}")
    else:
        bak = ENV.with_name(f".env.bak.{datetime.datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(ENV, bak)
        print(f"已备份原配置 → {bak.name}")

    lines = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
    lines = upsert(lines, "FTP_HOST", host)
    lines = upsert(lines, "FTP_PORT", port)
    lines = upsert(lines, "FTP_USER", user)
    lines = upsert(lines, "FTP_PASS", pwd)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n已写入 .env：")
    print(f"  FTP_HOST = {host}")
    print(f"  FTP_PORT = {port}")
    print(f"  FTP_USER = {user}")
    print(f"  FTP_PASS = {'*' * max(len(pwd) - 4, 0)}{pwd[-4:]}（共 {len(pwd)} 位）")

    if args.no_check:
        return 0

    print("\n跑一次连接自检……\n")
    checker = ROOT / "scripts" / "check_ftp.py"
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.exists() else sys.executable
    if checker.exists():
        return subprocess.call([exe, str(checker)])
    print("（没找到 scripts/check_ftp.py，跳过自检）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
