# -*- coding: utf-8 -*-
"""一键卸载：把 agent 在 Windows 上留下的东西清干净。

    python scripts/uninstall.py --dry-run     # 只看会删什么，不动手
    python scripts/uninstall.py               # 交互确认后执行

清理内容（部署时装的）：
    1. 运行中的服务进程（python main.py）
    2. 计划任务 StormSurge-DailyPrewarm（若跑过 4-设置自动下载.bat）
    3. 桌面快捷方式「风暴潮智能预报助手.lnk」
    4. 整个项目目录（含 .venv、.env、stormdata 数据仓）
    5. 可选：卸载随部署安装的 Python 3.10.11（会提示，不自动做）

不会动的东西：VC++ 运行库（其他软件也在用）、系统里的其他 Python。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "StormSurge-DailyPrewarm"
SHORTCUT_NAME = "风暴潮智能预报助手.lnk"


def human(n: float) -> str:
    return f"{n/1e6:.1f} MB" if n > 1e6 else f"{n/1e3:.0f} KB"


def dir_size(p: Path) -> int:
    tot = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    tot += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return tot


def running_services() -> list:
    """找到正在跑本项目 main.py 的 python 进程。"""
    out = []
    try:
        ps = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get",
             "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        for line in ps.splitlines():
            if "main.py" in line and str(ROOT) in line:
                parts = [x for x in line.strip().split(",") if x]
                if parts and parts[-1].isdigit():
                    out.append(int(parts[-1]))
    except Exception:
        pass
    if not out:      # 退化方案
        try:
            ps = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"],
                                capture_output=True, text=True, timeout=15).stdout
            for line in ps.splitlines():
                f = line.split()
                if len(f) >= 2 and f[0].lower() == "python.exe" and f[1].isdigit():
                    out.append(int(f[1]))
        except Exception:
            pass
    return out


def task_exists() -> bool:
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def shortcut_path() -> Path:
    return Path(os.path.expanduser("~")) / "Desktop" / SHORTCUT_NAME


def main() -> int:
    ap = argparse.ArgumentParser(description="卸载风暴潮智能预报助手")
    ap.add_argument("--dry-run", action="store_true", help="只列出会删什么")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    args = ap.parse_args()

    print("=" * 66)
    print("卸载：风暴潮与海浪智能预报助手")
    print("=" * 66)
    print(f"\n项目目录：{ROOT}")

    pids = running_services()
    has_task = task_exists()
    sc = shortcut_path()
    has_sc = sc.exists()
    venv = ROOT / ".venv"
    data = ROOT / "stormdata"
    envf = ROOT / ".env"
    py310 = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310"

    print("\n将清理以下内容：")
    print(f"  1. 运行中的服务进程        {'✅ ' + str(pids) if pids else '（未在运行）'}")
    print(f"  2. 计划任务 {TASK_NAME}  {'✅ 存在' if has_task else '（没有）'}")
    print(f"  3. 桌面快捷方式            {'✅ ' + sc.name if has_sc else '（没有）'}")
    print(f"  4. 项目目录                ✅ {ROOT}（含 .venv"
          f"{'、.env' if envf.exists() else ''}"
          f"{'、stormdata ' + human(dir_size(data)) if data.exists() else ''}）")
    if venv.exists():
        print(f"     其中 .venv 约 {human(dir_size(venv))}，"
              f"数据仓约 {human(dir_size(data)) if data.exists() else '0'}")
    print(f"\n  保留不动：VC++ 运行库、系统 Python；"
          f"Python310 随部署装的话会单独提示（{'已装' if py310.exists() else '未见'}）")

    if args.dry_run:
        print("\n（--dry-run 模式，未做任何改动）")
        return 0

    if not args.yes:
        print("\n⚠️  这会删除整个项目目录（包括已下载的数据、配置里的密钥）。")
        ans = input("确认卸载请输入大写 YES：").strip()
        if ans != "YES":
            print("已取消。")
            return 1

    # ① 停进程
    if pids:
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                               capture_output=True, timeout=20)
                print(f"  ✅ 已结束进程 {pid}")
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ 结束进程 {pid} 失败：{e}")

    # ② 删计划任务
    if has_task:
        try:
            subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                           capture_output=True, timeout=20)
            print("  ✅ 已删除计划任务")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 删除计划任务失败（可在任务计划程序里手动删）：{e}")

    # ③ 删快捷方式
    if has_sc:
        try:
            sc.unlink()
            print("  ✅ 已删除桌面快捷方式")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 删除快捷方式失败：{e}")

    # ④ 先删项目内的东西（当前脚本自己占着目录，最后交给临时 bat 删）
    for sub in (".venv", "stormdata", "outputs", "dist"):
        p = ROOT / sub
        if p.exists():
            try:
                shutil.rmtree(p, ignore_errors=True)
                print(f"  ✅ 已删除 {sub}")
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ 删除 {sub} 失败：{e}")
    for f in (".env", ".env.bak"):
        p = ROOT / f
        if p.exists():
            try:
                p.unlink()
                print(f"  ✅ 已删除 {f}（密钥）")
            except Exception:
                pass

    # ⑤ 用临时 bat 删掉整个目录（本进程退出后执行）
    bat = Path(tempfile.gettempdir()) / "stormsurge_uninstall.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "echo 正在删除项目目录……\r\n"
        "timeout /t 3 /nobreak >nul\r\n"
        f'rmdir /s /q "{ROOT}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", "start", "", "/min", str(bat)], shell=False)
    print(f"  ✅ 已安排删除整个项目目录：{ROOT}")

    print("\n" + "=" * 66)
    print("卸载完成。补充说明：")
    if py310.exists():
        print(f"  · 随部署安装的 Python 3.10.11 还在：{py310}")
        print("    不需要的话：设置 → 应用 → 已安装的应用 → Python 3.10.11 → 卸载")
    print("  · 桌面快捷方式若仍在，直接删掉即可")
    print("  · 计划任务可到「任务计划程序」确认 StormSurge-DailyPrewarm 已消失")
    print("  · 想清 pip 缓存：删除 %LOCALAPPDATA%\\pip\\Cache")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
