# -*- coding: utf-8 -*-
"""注册"每 30 分钟自动下载新数据"的计划任务（用 Python，避免 .bat 里拼中文路径）。

由 `4-设置自动下载.bat` 调用。做两件事：
    1. 先跑一次预下载（立刻把当前最新一期数据拉下来）
    2. 注册计划任务 StormSurge-DailyPrewarm（每 30 分钟）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "StormSurge-DailyPrewarm"
WRAPPER = ROOT / "deploy" / "run_prewarm.bat"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    print("=" * 66)
    print("设置每日自动下载")
    print("=" * 66)

    # ① 生成/修正调度用的批处理（内部只用 ASCII，路径由 Python 写入）
    WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        f'cd /d "{ROOT}"\r\n'
        f'"{PY}" "{ROOT / "scripts" / "daily_prewarm.py"}" >> "{ROOT / "stormdata" / "logs" / "prewarm.log"}" 2>&1\r\n',
        encoding="utf-8",
    )
    print(f"[OK] 调度脚本：{WRAPPER}")

    # ② 先跑一次，确认能取数
    print("\n[1/2] 先跑一次预下载……")
    try:
        r = subprocess.run([str(PY), str(ROOT / "scripts" / "daily_prewarm.py")],
                           cwd=str(ROOT), timeout=3600)
        print(f"      完成（退出码 {r.returncode}）")
    except Exception as e:  # noqa: BLE001
        print(f"      [警告] 预下载失败：{type(e).__name__}: {e}")

    # ③ 注册计划任务
    print("\n[2/2] 注册计划任务……")
    cmd = ["schtasks", "/Create", "/TN", TASK, "/TR", f'"{WRAPPER}"',
           "/SC", "MINUTE", "/MO", "30", "/F"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=120)
        if r.returncode == 0:
            print(f"[OK] 已注册：{TASK}（每 30 分钟检查一次）")
            print("     查看：任务计划程序 → 任务计划程序库 → " + TASK)
        else:
            print(f"[失败] {r.stdout.strip() or r.stderr.strip()}")
            print("       请以管理员身份重新运行本按钮，或手动在任务计划程序里创建。")
    except Exception as e:  # noqa: BLE001
        print(f"[失败] {type(e).__name__}: {e}")

    print("\n" + "=" * 66)
    print("完成。今后每 30 分钟自动检查课题组数据库，有新一期就下载到 stormdata/")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
