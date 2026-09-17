# -*- coding: utf-8 -*-
"""提交前自检（preflight）：把我踩过的坑做成机械检查，避免再犯。

检查项：
    1. 所有 .py 能否编译
    2. 所有 .ps1 **必须带 UTF-8 BOM** 且能被 PowerShell 解析器解析
       （无 BOM 时 PowerShell 5.1 会按 GBK 读，中文乱码甚至误报语法错误）
    3. 全仓库禁止出现 `--proxy ""` 写法
       （PowerShell 会丢掉空参数，pip 会把下一个参数当代理地址）
    4. .bat 文件是否只含 ASCII（避免 cmd 代码页乱码）
    5. 关键文件是否齐全（部署包/一键部署需要的）
    6. git 未跟踪文件里是否有敏感文件（.env / 密钥 / recovery codes）

用法：python scripts/preflight.py        # 全绿才提交
"""
from __future__ import annotations

import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK, BAD, WARN = "✅", "❌", "⚠️"
problems: list = []

SKIP_DIRS = {".venv", ".git", "dist", "stormdata", "data", "__pycache__",
             "微信数据", "_archive_extract"}


def walk(suffix: str):
    for p in ROOT.rglob(f"*{suffix}"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def check_py() -> None:
    print("\n① Python 语法")
    bad = 0
    for p in walk(".py"):
        try:
            py_compile.compile(str(p), doraise=True, cfile=str(p) + ".pyc")
            Path(str(p) + ".pyc").unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            print(f"  {BAD} {p.relative_to(ROOT)}: {e}")
            problems.append(f"Python 语法错误：{p.relative_to(ROOT)}")
            bad += 1
    print(f"  {OK if not bad else BAD} {bad} 个文件有语法错误" if bad
          else f"  {OK} 全部通过")


def check_ps1() -> None:
    print("\n② PowerShell 脚本（BOM + 语法）")
    ps = list(walk(".ps1"))
    if not ps:
        print("  （没有 .ps1）")
        return
    for p in ps:
        b = p.read_bytes()
        has_bom = b[:3] == b"\xef\xbb\xbf"
        note = []
        if not has_bom:
            note.append("无 UTF-8 BOM")
            problems.append(f"{p.relative_to(ROOT)} 缺 UTF-8 BOM")
        # 用 pwsh 解析（若有）
        try:
            cmd = ["pwsh", "-NoProfile", "-Command",
                   f"$e=$null;[System.Management.Automation.Language.Parser]"
                   f"::ParseFile('{p}',[ref]$null,[ref]$e)|Out-Null;"
                   f"if($e.Count){{$e|%{{$_.Message}};exit 1}}"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                note.append("解析报错: " + r.stdout.strip()[:120])
                problems.append(f"{p.relative_to(ROOT)} 语法错误")
        except FileNotFoundError:
            note.append("（没装 pwsh，跳过语法解析）")
        except Exception as e:  # noqa: BLE001
            note.append(f"解析异常 {e}")
        print(f"  {OK if not note or '跳过' in note[0] else BAD} "
              f"{p.relative_to(ROOT)}" + (f"  ← {'；'.join(note)}" if note else ""))


def check_proxy_flag() -> None:
    """禁止 `--proxy ""` 这种空参数写法（PowerShell 会丢空参数 → pip 报错）。

    只检查**真正的命令行**：跳过注释行、跳过本检查器自身，
    避免把"文档里说明不要这么写"的句子也判成问题。
    """
    print("\n③ 禁止 --proxy 空参数写法")
    pat = re.compile(r'--proxy\s+(""|\'\')')
    hits = []
    for p in list(walk(".py")) + list(walk(".ps1")) + list(walk(".bat")) + \
            list(walk(".md")) + list(walk(".sh")):
        if p.name == "preflight.py":
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if not pat.search(s):
                continue
            if s.startswith(("#", "//", "rem ", "REM ", "*", ">")):   # 注释/说明
                continue
            if "pip" not in s and "$Py" not in s and "%PY%" not in s:
                continue          # 不是命令行，忽略
            hits.append(f"{p.relative_to(ROOT)}:{i}")
    if hits:
        for h in hits:
            print(f"  {BAD} {h} 出现 --proxy 空参数"
                  f"（PowerShell 会丢参数，pip 会报 Failed to resolve '--timeout'）")
            problems.append(f"{h} 含 --proxy 空参数")
    else:
        print(f"  {OK} 未发现")


def check_bat_ascii() -> None:
    print("\n④ 批处理文件编码")
    bad = []
    for p in walk(".bat"):
        b = p.read_bytes()
        if any(x > 127 for x in b):
            txt = b.decode("utf-8", errors="ignore")
            if "chcp 65001" not in txt:      # 有 chcp 65001 就没问题
                bad.append(p.relative_to(ROOT))
    if bad:
        for h in bad:
            print(f"  {WARN} {h} 含非 ASCII 且没有 chcp 65001（cmd 会乱码）")
    else:
        print(f"  {OK} 含中文的批处理都设了 chcp 65001 或用纯 ASCII")


def check_files() -> None:
    print("\n⑤ 关键文件")
    need = ["main.py", "requirements.txt", ".env.example",
            "orchestrator/ftp_catalog.py", "modules/visualize.py",
            "scripts/check_ftp.py", "scripts/check_install.py",
            "scripts/check_pipeline.py", "deploy/setup_windows.ps1",
            "deploy/repair_env.py", "一键部署.bat"]
    miss = [f for f in need if not (ROOT / f).exists()]
    if miss:
        for m in miss:
            print(f"  {BAD} 缺 {m}")
            problems.append(f"缺文件 {m}")
    else:
        print(f"  {OK} {len(need)} 个关键文件齐全")


def check_secrets() -> None:
    print("\n⑥ 未跟踪文件中的敏感项")
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        print(f"  {WARN} 无法执行 git：{e}")
        return
    danger = []
    for line in r.stdout.splitlines():
        if not line.startswith("??"):
            continue
        f = line[3:].strip().strip('"')
        if re.search(r"(^|/)(\.env($|\.)|.*key\.csv|.*recovery-codes.*|腾讯云key)",
                     f, re.I):
            danger.append(f)
    if danger:
        for d in danger:
            print(f"  {BAD} 未忽略的敏感文件：{d}（务必加进 .gitignore）")
            problems.append(f"敏感文件未忽略：{d}")
    else:
        print(f"  {OK} 没有被跟踪/未忽略的敏感文件")


def main() -> int:
    print("=" * 70)
    print("提交前自检 preflight")
    print("=" * 70)
    check_py()
    check_ps1()
    check_proxy_flag()
    check_bat_ascii()
    check_files()
    check_secrets()
    print("\n" + "=" * 70)
    if problems:
        print(f"{BAD} 发现 {len(problems)} 个问题，先修再提交：")
        for p in problems:
            print(f"   · {p}")
        print("=" * 70)
        return 1
    print(f"{OK} 全部通过，可以提交")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
