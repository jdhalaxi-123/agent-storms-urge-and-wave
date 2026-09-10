#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""环境自检 —— 部署前先跑这个，生成一份《环境自检报告》。

用途：
    1. 判断这台电脑能不能一键部署 stormsuregent；
    2. 报告可以直接复制给 AI（如另一台电脑上的 DeepSeek 助手），
       让它照着报告告诉你缺什么、下一步做什么。

用法（任意 Python 3.8+ 都能跑，不依赖本项目任何库）：
    python deploy/check_env.py
    python deploy/check_env.py -o 环境自检报告.md

输出：屏幕打印 + 写出 报告文件（默认 环境自检报告.md）
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

OK, WARN, BAD = "[通过]", "[注意]", "[不通过]"

# 本项目需要的第三方包 -> pip 包名
REQUIRED_PKGS = {
    "gradio": "gradio",
    "openai": "openai",
    "yaml": "PyYAML",
    "numpy": "numpy",
    "pandas": "pandas",
    "xarray": "xarray",
    "netCDF4": "netCDF4",
    "matplotlib": "matplotlib",
    "docx": "python-docx",
    "scipy": "scipy",
}

MIN_PY = (3, 9)


def run(cmd, timeout=60):
    """执行命令，返回 (返回码, 输出)。失败不抛异常。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           shell=isinstance(cmd, str))
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} PB"


def dir_size(p: Path) -> int:
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


# --------------------------------------------------------------------------- #
# 各项检查
# --------------------------------------------------------------------------- #
def check_system(lines):
    lines.append("### 1. 操作系统")
    lines.append(f"- 系统：{platform.system()} {platform.release()} (版本 {platform.version()})")
    lines.append(f"- 架构：{platform.machine()}  |  位数：{'64位' if sys.maxsize > 2**32 else '32位'}")
    lines.append(f"- 主机名：{platform.node()}")
    if platform.system() == "Windows":
        ok = sys.maxsize > 2**32
        lines.append(f"- {OK if ok else BAD} 必须是 64 位系统（本项目的 netCDF4 / ctranslate2 只有 64 位包）")
        # 长路径支持
        rc, out = run(["reg", "query",
                       r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem",
                       "/v", "LongPathsEnabled"])
        long_ok = "0x1" in out
        lines.append(f"- {OK if long_ok else WARN} 长路径支持（LongPathsEnabled）"
                     f"{'' if long_ok else '：建议开启，否则部分依赖解压可能失败'}")
        # VC++ 运行库（netCDF4 / ctranslate2 需要）
        vcr = []
        for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            found = False
            for base in (os.environ.get("SystemRoot", r"C:\Windows"),):
                for sub in ("System32",):
                    if (Path(base) / sub / dll).exists():
                        found = True
            vcr.append((dll, found))
        miss = [d for d, f in vcr if not f]
        lines.append(f"- {OK if not miss else BAD} VC++ 2015-2022 运行库"
                     f"{'' if not miss else f'：缺少 {miss}，需装 vc_redist.x64.exe'}")
    lines.append("")


def check_python(lines):
    lines.append("### 2. Python")
    lines.append(f"- 当前运行本脚本的解释器：`{sys.executable}`")
    lines.append(f"- 版本：Python {platform.python_version()}")
    ver_ok = sys.version_info[:2] >= MIN_PY
    lines.append(f"- {OK if ver_ok else BAD} 需要 Python {MIN_PY[0]}.{MIN_PY[1]} 及以上"
                 f"（推荐 3.10，与本项目开发环境一致）")
    lines.append("")

    # 找系统里所有可用的 python
    lines.append("**这台电脑上找到的 Python 解释器：**")
    cands = []
    if platform.system() == "Windows":
        for cmd in (["py", "-0p"], ["py", "-3", "-V"], ["python", "-V"], ["python3", "-V"]):
            rc, out = run(cmd, timeout=30)
            if rc == 0 and out:
                cands.append((" ".join(cmd), out.replace("\n", " | ")))
    else:
        for cmd in (["python3", "-V"], ["python", "-V"]):
            rc, out = run(cmd, timeout=20)
            if rc == 0 and out:
                cands.append((" ".join(cmd), out.replace("\n", " | ")))
    if cands:
        for c, o in cands:
            lines.append(f"- `{c}` -> {o}")
    else:
        lines.append(f"- {BAD} 没有找到可用的 Python（一键部署脚本会尝试自动下载安装）")
    lines.append("")

    lines.append("**pip 情况：**")
    rc, out = run([sys.executable, "-m", "pip", "-V"])
    lines.append(f"- {OK if rc == 0 else WARN} `python -m pip -V` -> {out or '不可用'}")
    lines.append("")


def check_packages(lines):
    lines.append("### 3. 依赖包（如果已经装好环境，这里应全部通过）")
    missing = []
    for mod, pkg in REQUIRED_PKGS.items():
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            lines.append(f"- {OK} {pkg} {v}")
        except Exception:
            missing.append(pkg)
            lines.append(f"- {WARN} {pkg} 未安装")
    lines.append("")
    if missing:
        lines.append(f"> 缺少：{', '.join(missing)}（一键部署脚本会自动安装，属正常）")
    lines.append("")


def check_network(lines):
    lines.append("### 4. 网络（部署需要能访问 pip 源和 DeepSeek）")
    proxy = {k: v for k, v in os.environ.items()
             if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    lines.append(f"- 代理环境变量：{proxy if proxy else '（无）'}")

    targets = [
        ("PyPI 官方源", "pypi.org", 443),
        ("清华镜像", "pypi.tuna.tsinghua.edu.cn", 443),
        ("阿里云镜像", "mirrors.aliyun.com", 443),
        ("DeepSeek API", "api.deepseek.com", 443),
        ("腾讯云 ASR", "asr.tencentcloudapi.com", 443),
    ]
    reachable = []
    for name, host, port in targets:
        t0 = time.time()
        try:
            with socket.create_connection((host, port), timeout=6):
                ms = int((time.time() - t0) * 1000)
                lines.append(f"- {OK} {name} ({host}:{port}) 可连通，{ms} ms")
                reachable.append(host)
        except Exception as e:  # noqa: BLE001
            lines.append(f"- {WARN} {name} ({host}:{port}) 连不上（{type(e).__name__}）")
    lines.append("")
    if "pypi.org" not in reachable and "pypi.tuna.tsinghua.edu.cn" not in reachable \
            and "mirrors.aliyun.com" not in reachable:
        lines.append(f"> {BAD} 三个 pip 源都连不上：无法在线装依赖。"
                     f"请检查网络/代理，或改用离线部署包。")
    if "api.deepseek.com" not in reachable:
        lines.append(f"> {WARN} 连不上 api.deepseek.com：装好后对话功能会不可用"
                     f"（需要能访问 DeepSeek 接口，或配置代理）。")
    lines.append("")


def check_disk(lines):
    lines.append("### 5. 磁盘空间")
    for p in (ROOT, Path.home()):
        try:
            u = shutil.disk_usage(str(p))
            need = 3 * 1024 ** 3
            flag = OK if u.free > need else WARN
            lines.append(f"- {flag} `{p}` 所在盘：可用 {human(u.free)} / 共 {human(u.total)}"
                         f"（建议留 3 GB 以上：依赖约 1.5 GB）")
        except Exception as e:  # noqa: BLE001
            lines.append(f"- {WARN} `{p}` 磁盘信息读取失败：{e}")
    lines.append("")


def check_port(lines):
    lines.append("### 6. 端口 7860（网页界面用的端口）")
    free = True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            free = s.connect_ex(("127.0.0.1", 7860)) != 0
    except Exception:
        free = True
    lines.append(f"- {OK if free else WARN} 7860 "
                 f"{'空闲，可以使用' if free else '已被占用：启动前请先关掉占用它的程序'}")
    lines.append("")


def check_project(lines):
    lines.append("### 7. 项目文件")
    must = ["main.py", "requirements.txt", "orchestrator", "modules"]
    miss = [m for m in must if not (ROOT / m).exists()]
    lines.append(f"- 项目目录：`{ROOT}`")
    lines.append(f"- {OK if not miss else BAD} 必需文件"
                 f"{'齐全' if not miss else f'缺少 {miss}（是不是解压不完整？）'}")
    env_f = ROOT / ".env"
    lines.append(f"- {OK if env_f.exists() else WARN} `.env` 配置文件"
                 f"{'已存在' if env_f.exists() else '还没有（部署脚本会引导你填 DeepSeek 密钥）'}")
    venv = ROOT / ".venv"
    lines.append(f"- {OK if venv.exists() else WARN} 虚拟环境 `.venv`"
                 f"{'已存在' if venv.exists() else '还没有（部署脚本会创建）'}")
    data_dir = Path(os.environ.get("STORM_DATA_DIR") or (ROOT / "data"))
    if data_dir.exists():
        lines.append(f"- {OK} 数据目录 `{data_dir}`，共 {human(dir_size(data_dir))}")
        ncs = list(data_dir.rglob("*.nc"))
        lines.append(f"  - 找到 {len(ncs)} 个 .nc 数据文件")
    else:
        lines.append(f"- {WARN} 数据目录 `{data_dir}` 不存在："
                     f"系统会自动降级为骨架演示（不会崩），但出不了真实预报图。"
                     f"把 NC 数据拷到该目录，或设置环境变量 STORM_DATA_DIR 指向数据位置。")
    lines.append("")


def check_gpu(lines):
    lines.append("### 8. 显卡（只影响语音识别速度，不影响主功能）")
    rc, out = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    if rc == 0 and out:
        lines.append(f"- {OK} 检测到 NVIDIA 显卡：{out.replace(chr(10), ' | ')}")
    else:
        lines.append(f"- {WARN} 没检测到 NVIDIA 显卡（语音识别走 CPU，会慢一些；"
                     f"不填腾讯云密钥时用本地识别）")
    lines.append("")


def collect_facts() -> dict:
    """给 AI 看的机器可读事实。"""
    pythons = []
    cmds = (["py", "-3", "-V"], ["python", "-V"], ["python3", "-V"]) if platform.system() == "Windows" \
        else (["python3", "-V"], ["python", "-V"])
    for c in cmds:
        rc, out = run(c, timeout=20)
        if rc == 0 and out:
            pythons.append({"cmd": " ".join(c), "out": out})

    def port_free(p):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                return s.connect_ex(("127.0.0.1", p)) != 0
        except Exception:
            return True

    def net(host):
        try:
            t0 = time.time()
            with socket.create_connection((host, 443), timeout=6):
                return int((time.time() - t0) * 1000)
        except Exception:
            return None

    disk = {}
    for key, p in (("project", ROOT), ("home", Path.home())):
        try:
            disk[key] = round(shutil.disk_usage(str(p)).free / 1024 ** 3, 1)
        except Exception:
            disk[key] = None

    return {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "is_64bit": sys.maxsize > 2 ** 32,
        "python_found": pythons,
        "running_python": platform.python_version(),
        "proxy_env": {k: v for k, v in os.environ.items() if "proxy" in k.lower()},
        "net_ms": {h: net(h) for h in ("pypi.org", "pypi.tuna.tsinghua.edu.cn",
                                       "mirrors.aliyun.com", "api.deepseek.com",
                                       "asr.tencentcloudapi.com")},
        "disk_free_gb": disk,
        "port_7860_free": port_free(7860),
        "project_dir": str(ROOT),
        "has_env": (ROOT / ".env").exists(),
        "has_venv": (ROOT / ".venv").exists(),
        "data_dir": str(os.environ.get("STORM_DATA_DIR") or (ROOT / "data")),
        "has_data": Path(os.environ.get("STORM_DATA_DIR") or (ROOT / "data")).exists(),
    }


def main():
    ap = argparse.ArgumentParser(description="stormsuregent 环境自检")
    ap.add_argument("-o", "--out", default=str(ROOT / "环境自检报告.md"))
    args = ap.parse_args()

    lines = []
    lines.append("# stormsuregent 部署环境自检报告")
    lines.append("")
    lines.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("> 这份报告可以直接复制给 AI 助手（例如另一台电脑上的 DeepSeek），"
                 "内容是「这台机器能不能一键部署 stormsuregent」。")
    lines.append("")

    check_system(lines)
    check_python(lines)
    check_packages(lines)
    check_network(lines)
    check_disk(lines)
    check_port(lines)
    check_project(lines)
    check_gpu(lines)

    # 结论
    lines.append("### 9. 结论与下一步")
    facts = collect_facts()
    blocking = []
    if not facts["is_64bit"]:
        blocking.append("系统不是 64 位")
    if facts["net_ms"]["pypi.org"] is None and facts["net_ms"]["pypi.tuna.tsinghua.edu.cn"] is None \
            and facts["net_ms"]["mirrors.aliyun.com"] is None:
        blocking.append("连不上任何 pip 源（在线部署不可行）")
    if not facts["has_data"]:
        blocking.append("还没有 data 数据目录（能用，但出不了真实预报）")
    if blocking:
        lines.append("需要先解决的问题：")
        for b in blocking:
            lines.append(f"- {b}")
    else:
        lines.append(f"{OK} 没发现阻塞问题，可以执行 **一键部署**。")
    lines.append("")
    lines.append("**下一步：**")
    lines.append("1. 双击 `1-一键部署-Windows.bat`（Windows）或运行 `bash deploy/setup_linux.sh`（Linux/Mac）")
    lines.append("2. 按提示填入 DeepSeek API Key（https://platform.deepseek.com 获取）")
    lines.append("3. 脚本装完会自动打开浏览器 http://localhost:7860")
    lines.append("4. 把 NC 数据拷到程序目录下的 `data/`（或设置环境变量 `STORM_DATA_DIR`）")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### 附：给 AI 读的机器可读事实（JSON）")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(facts, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    report = "\n".join(lines)
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("utf-8", "replace").decode("utf-8", "replace"))

    try:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n报告已写入：{args.out}")
    except Exception as e:  # noqa: BLE001
        print(f"\n报告写入失败：{e}")


if __name__ == "__main__":
    main()
