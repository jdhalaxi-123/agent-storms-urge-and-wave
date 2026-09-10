#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打交付包：把「程序本体 + 一键部署脚本」压成一个 zip（不含数据、不含密钥）。

用法：
    python scripts/build_deploy_package.py
    python scripts/build_deploy_package.py --out dist            # 指定输出目录
    python scripts/build_deploy_package.py --with-data           # 连 data/ 一起打（很大）

产物：
    dist/stormsurge-agent-部署包-YYYYMMDD.zip
    （解压后根目录直接就是 1-一键部署-Windows.bat，双击即用）
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 需要打进包里的顶层条目
INCLUDE_TOP = [
    "main.py",
    "requirements.txt",
    "README.md",
    "部署运行说明.md",
    ".env.example",
    ".gitignore",
    "orchestrator",
    "modules",
    "scenarios",
    "scripts",
    "deploy",
]

# 一律排除
EXCLUDE_DIRS = {
    ".venv", "venv", "__pycache__", ".git", ".idea", ".vscode",
    "outputs", "dist", "data", "厦门中心简报材料",
    "_archive_extract",
}
EXCLUDE_FILE_PATTERNS = [
    "*.pyc", "*.pyo", "*.log", "*.nc", "*.nc4", "*.grib", "*.grib2",
    "*.rar", "*.zip", "*.7z", "*.pem", "*.ppk", "*.key.csv",
    ".env", "腾讯云key.csv", "github-recovery-codes.txt",
    "AgentRecord.*.jsonl", "_tmp_*", "_delivery_*",
    "环境自检报告.md", "部署日志.txt", "*.bak",
]

# deploy/ 里的脚本要复制到 zip 根目录，方便双击
ROOT_LEVEL_COPIES = {
    "deploy/1-一键部署-Windows.bat": "1-一键部署-Windows.bat",
    "deploy/2-启动.bat": "2-启动.bat",
    "deploy/3-环境自检.bat": "3-环境自检.bat",
    "deploy/部署说明.md": "部署说明.md",
    "deploy/AI部署与使用说明.md": "AI部署与使用说明.md",
}
# 这些在 deploy/ 下保留一份即可，不重复放根目录
KEEP_IN_DEPLOY = {"setup_windows.ps1", "setup_linux.sh", "start_linux.sh", "check_env.py"}


def excluded(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    name = Path(rel).name
    for pat in EXCLUDE_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return True
    if rel.endswith(".bat") and "deploy" not in rel.replace("\\", "/"):
        return False
    return False


def iter_files(with_data: bool):
    """产出 (磁盘路径, zip 内相对路径)。"""
    for top in INCLUDE_TOP:
        p = ROOT / top
        if not p.exists():
            continue
        if p.is_file():
            if not excluded(top):
                yield p, top
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(ROOT).as_posix()
            if excluded(rel):
                continue
            yield f, rel

    # 部署脚本复制到根目录（双击友好）
    for src, dst in ROOT_LEVEL_COPIES.items():
        sp = ROOT / src
        if sp.exists():
            yield sp, dst

    if with_data:
        d = ROOT / "data"
        if d.exists():
            for f in sorted(d.rglob("*")):
                if f.is_file() and not any(part in EXCLUDE_DIRS for part in f.parts):
                    yield f, f.relative_to(ROOT).as_posix()


def _encode_for_package(rel: str, data: bytes):
    """按扩展名规范化编码，避免目标机器上因编码问题跑不起来。

    - .ps1：Windows PowerShell 5.1 读「无 BOM 的 UTF-8」会按 GBK 解码，
            中文注释里的字节会被当成引号/花括号，导致脚本解析失败 → 强制加 UTF-8 BOM
    - .bat/.cmd：cmd.exe 按 OEM 代码页(中文 Windows 为 GBK)读批处理，
            中文会被截断成乱码甚至拆断命令行 → 强制纯 ASCII（中文提示应放在 .ps1 里）
    """
    name = rel.lower()
    if name.endswith(".ps1"):
        text = data.decode("utf-8-sig", errors="replace")
        return text.encode("utf-8-sig")          # 带 BOM
    if name.endswith((".bat", ".cmd")):
        non_ascii = sum(1 for b in data if b > 127)
        if non_ascii:
            print(f"  [警告] {rel} 含 {non_ascii} 个非 ASCII 字节，"
                  f"中文 Windows 下 cmd 可能乱码（中文提示请放到 .ps1 里）")
        return data
    if name.endswith((".py", ".md", ".txt", ".sh", ".yaml", ".yml", ".json")):
        text = data.decode("utf-8-sig", errors="replace")
        return text.encode("utf-8")              # 无 BOM
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--with-data", action="store_true", help="连 data/ 一起打包（体积很大）")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    suffix = "-含数据" if args.with_data else ""
    zip_path = out_dir / f"stormsurge-agent-部署包{suffix}-{stamp}.zip"

    n = 0
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, rel in iter_files(args.with_data):
            try:
                data = src.read_bytes()
                data = _encode_for_package(rel, data)
                z.writestr(rel, data)
                n += 1
                total += len(data)
            except Exception as e:  # noqa: BLE001
                print(f"  跳过 {rel}: {e}")

    print(f"交付包已生成：{zip_path}")
    print(f"  文件数：{n}")
    print(f"  原始大小：{total / 1024 / 1024:.1f} MB")
    print(f"  压缩后：{zip_path.stat().st_size / 1024 / 1024:.1f} MB")
    print()
    print("解压后根目录有：")
    for _, dst in ROOT_LEVEL_COPIES.items():
        print(f"  {dst}")


if __name__ == "__main__":
    main()
