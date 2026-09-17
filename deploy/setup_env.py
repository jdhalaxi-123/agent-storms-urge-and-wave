# -*- coding: utf-8 -*-
"""一键部署（Windows）——纯 Python 实现，替代原 setup_windows.ps1。

为什么改成 Python：
    原来的 setup_windows.ps1 在中文 Windows 上很脆弱——只要文件丢了 UTF-8 BOM，
    PowerShell 5.1 就会按 GBK 解码，中文注释里的字节错位会让**注释块提前结束**，
    于是脚本一开头就报一堆"意外的标记"。反复踩了三次，索性不用 PowerShell。

本脚本做这些事（全程 Python，源码本身按 UTF-8 解析，无编码坑）：
    ① 找 Python（本机版本 ≥3.9 就直接用；否则下载官方安装包装到用户目录）
    ② 创建虚拟环境 <项目>/.venv
    ③ 用国内镜像装依赖（pip --isolated，自动清代理）
    ④ 生成 .env 并引导填 DeepSeek API Key
    ⑤ 建数据仓目录 + 桌面快捷方式（复制一个启动用的 .bat）
    ⑥ 打印下一步（填 FTP、自检、启动）

用法：
    python deploy/setup_env.py              # 完整安装
    python deploy/setup_env.py --check      # 只看环境、不装
    python deploy/setup_env.py --key sk-xxx # 顺带写入 DeepSeek Key，不交互
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
ENV_FILE = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
OK, BAD, WARN = "✅", "❌", "⚠️"

PY_URLS = [
    "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe",
    "https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-amd64.exe",
]
MIRRORS = [
    ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
    ("https://mirrors.aliyun.com/pypi/simple", "mirrors.aliyun.com"),
    ("https://pypi.org/simple", "pypi.org"),
]


def clear_proxy() -> list:
    """清空代理环境变量（失效代理会让 pip 卡死）。"""
    hit = []
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        if os.environ.get(k):
            hit.append(k)
        os.environ.pop(k, None)
    return hit


def find_python() -> str:
    """返回可用的 Python 解释器路径（优先系统里 ≥3.9 的）。"""
    cands = []
    if sys.version_info >= (3, 9):
        cands.append(sys.executable)
    for p in [
        shutil.which("python"),
        shutil.which("python3"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe"),
        r"C:\Python310\python.exe", r"C:\Python311\python.exe",
    ]:
        if p:
            cands.append(p)
    for c in cands:
        if not c or not Path(c).exists():
            continue
        try:
            out = subprocess.run([c, "-c",
                                  "import sys;print('%d.%d'%sys.version_info[:2])"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
            if out and tuple(int(x) for x in out.split(".")) >= (3, 9):
                print(f"  {OK} 使用 Python {out} → {c}")
                return c
        except Exception:
            continue
    return ""


def install_python() -> str:
    """下载官方安装包并静默装到用户目录（无需管理员）。"""
    tmp = Path(os.environ.get("TEMP", ".")) / "python-3.10.11-amd64.exe"
    for url in PY_URLS:
        try:
            print(f"  下载 Python 安装包：{url}")
            urllib.request.urlretrieve(url, tmp)
            break
        except Exception as e:  # noqa: BLE001
            print(f"  {WARN} 下载失败（{type(e).__name__}），换下一个源")
    if not tmp.exists():
        print(f"  {BAD} Python 安装包下载失败，请手动安装 Python 3.10 后重跑")
        return ""
    target = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310"
    print(f"  静默安装到：{target}")
    try:
        subprocess.run([str(tmp), "/quiet", "InstallAllUsers=0", "PrependPath=1",
                        f"TargetDir={target}"], timeout=900)
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 安装失败：{e}")
        return ""
    py = target / "python.exe"
    if py.exists():
        print(f"  {OK} Python 已安装：{py}")
        return str(py)
    print(f"  {BAD} 没找到安装后的 python.exe")
    return ""


def make_venv(base_py: str) -> str:
    if VENV_PY.exists():
        print(f"  {OK} 虚拟环境已存在：{VENV}")
        return str(VENV_PY)
    print(f"  创建虚拟环境：{VENV}")
    r = subprocess.run([base_py, "-m", "venv", str(VENV)], capture_output=True,
                       text=True, encoding="utf-8", errors="ignore")
    if not VENV_PY.exists():
        print(f"  {BAD} 创建失败：{r.stderr or r.stdout}")
        return ""
    print(f"  {OK} 虚拟环境就绪")
    return str(VENV_PY)


def install_deps(py: str) -> bool:
    req = ROOT / "requirements.txt"
    if not req.exists():
        print(f"  {BAD} 缺少 requirements.txt")
        return False
    subprocess.run([py, "-m", "pip", "--isolated", "install", "--upgrade",
                    "pip", "setuptools", "wheel", "--quiet"],
                   capture_output=True, text=True, encoding="utf-8", errors="ignore")
    for url, host in MIRRORS:
        print(f"  安装依赖（源：{host}）……")
        r = subprocess.run([py, "-m", "pip", "--isolated", "install", "-r", str(req),
                            "--index-url", url, "--trusted-host", host,
                            "--timeout", "60", "--retries", "2"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore")
        if r.returncode == 0:
            print(f"  {OK} 依赖安装完成")
            return True
        print(f"  {WARN} 该源失败，换下一个")
    print(f"  {BAD} 依赖安装失败，请把下面的输出发给技术支持：")
    print((r.stdout or "")[-1500:])
    print((r.stderr or "")[-800:])
    return False


def write_env(key: str) -> None:
    if not ENV_FILE.exists():
        ENV_FILE.write_text(EXAMPLE.read_text(encoding="utf-8") if EXAMPLE.exists() else "",
                            encoding="utf-8")
        print(f"  {OK} 已从 .env.example 生成 .env")
    if not key:
        return
    lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    out, done = [], False
    for ln in lines:
        if ln.strip().startswith("DEEPSEEK_API_KEY="):
            out.append(f"DEEPSEEK_API_KEY={key}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"DEEPSEEK_API_KEY={key}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  {OK} 已写入 DEEPSEEK_API_KEY（{key[:5]}…{key[-4:]}）")


def make_shortcut() -> None:
    """桌面放一个启动用的 bat（不用 PowerShell 建 .lnk，避免编码问题）。"""
    try:
        desktop = Path(os.path.expanduser("~")) / "Desktop"
        if not desktop.exists():
            return
        target = desktop / "风暴潮智能预报助手.bat"
        target.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            f'cd /d "{ROOT}"\r\n'
            f'start "" "{VENV_PY}" "{ROOT / "main.py"}"\r\n',
            encoding="utf-8")
        print(f"  {OK} 桌面快捷方式：{target.name}")
    except Exception as e:  # noqa: BLE001
        print(f"  {WARN} 桌面快捷方式创建失败（不影响使用）：{e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="一键部署（纯 Python 版）")
    ap.add_argument("--check", action="store_true", help="只检查不安装")
    ap.add_argument("--key", default="", help="DeepSeek API Key（可选，省去交互）")
    args = ap.parse_args()

    print("=" * 70)
    print("  风暴潮与海浪智能预报助手　一键部署（Python 版安装器）")
    print("=" * 70)
    print(f"项目目录：{ROOT}")

    print("\n① 代理")
    cleared = clear_proxy()
    print(f"  {OK} 已清空代理环境变量" + (f"（{', '.join(cleared)}）" if cleared else "（本来就没有）"))

    print("\n② Python")
    base = find_python()
    if not base and not args.check:
        print("  未找到可用的 Python，尝试自动安装……")
        base = install_python()
    if not base:
        print(f"  {BAD} 没有可用的 Python（≥3.9）。请先安装 Python 3.10 后重跑本脚本。")
        return 1

    print("\n③ 虚拟环境")
    py = str(VENV_PY) if VENV_PY.exists() else ("" if args.check else make_venv(base))
    if not py:
        print(f"  {BAD} 虚拟环境不可用")
        return 1

    print("\n④ 依赖")
    ok_dep = True
    if not args.check:
        ok_dep = install_deps(py)
    else:
        print("  （--check 模式，跳过安装）")

    print("\n⑤ 配置 .env")
    write_env(args.key)

    print("\n⑥ 数据仓与快捷方式")
    try:
        sys.path.insert(0, str(ROOT))
        from orchestrator import paths
        paths.ensure_tree()
        print(f"  {OK} 数据仓：{paths.DATA_ROOT}")
    except Exception as e:  # noqa: BLE001
        print(f"  {WARN} 数据仓初始化稍后由程序自动完成：{e}")
    if not args.check:
        make_shortcut()

    print("\n" + "=" * 70)
    print("下一步：")
    print("  1. 双击 `5-配置FTP.bat` 填课题组 FTP（账号/密码），自动测连接")
    print("  2. 双击 `7-一键修复.bat` 做一次自检（依赖 / 取数 / 出图）")
    print("  3. 双击 `2-启动.bat`，浏览器打开 http://localhost:7860")
    print("  4. 想让数据每天自动更新：双击 `4-设置自动下载.bat`")
    print("=" * 70)
    return 0 if ok_dep else 1


if __name__ == "__main__":
    sys.exit(main())
