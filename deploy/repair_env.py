# -*- coding: utf-8 -*-
"""一键修复 + 自检（在新电脑上跑这个，别手拼命令）。

做四件事，全程在 Python 里完成（参数用列表传，不存在 PowerShell/cmd
"空字符串被丢掉"这类方言坑）：

    ① 清掉代理环境变量（Clash 等没开会让 pip 卡死），并忽略 pip.ini 里的代理
    ② 装依赖：pip --isolated install -r requirements.txt（镜像自动轮询）
    ③ 验证依赖：gradio / openai / cartopy / shapely / pyproj / netCDF4 ...
    ④ 验证数据与出图：真下一个小文件 + 真画一张小图
最后打印一份 ✅/❌ 清单。

用法：
    .venv\\Scripts\\python.exe deploy\\repair_env.py          # 缺什么补什么
    .venv\\Scripts\\python.exe deploy\\repair_env.py --check   # 只看不装
"""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
OK, BAD, WARN = "✅", "❌", "⚠️"

MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
]
NEEDED = ["gradio", "openai", "yaml", "docx", "numpy", "pandas", "xarray",
          "netCDF4", "scipy", "matplotlib", "cartopy", "shapely", "pyproj"]


def clear_proxy() -> list:
    """清掉代理环境变量（本进程 + 子进程都生效）。返回被清掉的项，便于打印。"""
    cleared = []
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        v = os.environ.get(k)
        if v:
            cleared.append(f"{k}={v}")
        os.environ[k] = ""
        os.environ.pop(k, None)
    return cleared


def pip(args: list, verbose: bool = True) -> int:
    """调用 pip：python -m pip --isolated <args...>（参数列表，安全）。"""
    cmd = [str(PY if PY.exists() else sys.executable), "-m", "pip", "--isolated"] + args
    if verbose:
        print("    $ " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    p = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8",
                       errors="ignore", capture_output=True)
    if verbose and p.stdout:
        tail = [ln for ln in p.stdout.splitlines()
                if any(w in ln for w in ("Successfully", "ERROR", "error:", "WARNING: Retrying"))
                or ln.strip().startswith(("Collecting", "Installing", "Downloading"))]
        for ln in tail[-25:]:
            print("      " + ln.strip())
    return p.returncode


def missing() -> list:
    out = []
    for m in NEEDED:
        try:
            importlib.import_module(m)
        except Exception:  # noqa: BLE001
            out.append(m)
    return out


def do_install(check_only: bool) -> bool:
    miss = missing()
    print(f"\n② 依赖：{'全部已安装' if not miss else '缺少 ' + ' '.join(miss)}")
    if not miss or check_only:
        return not miss

    for m in MIRRORS:
        print(f"  用源 {m}")
        rc = pip(["install", "-r", "requirements.txt", "--index-url", m,
                  "--trusted-host", m.split("/")[2], "--timeout", "60", "--retries", "2"])
        if rc == 0 and not missing():
            print(f"  {OK} 依赖装好了")
            return True
        print(f"  {WARN} 该源失败，换下一个")
    # 兜底：只装必需项（语音可选包装不上不影响主功能）
    print(f"  {WARN} 整份 requirements 装不上，尝试只装必需项（跳过语音包）")
    for m in MIRRORS:
        rc = pip(["install", *NEEDED, "--index-url", m,
                  "--trusted-host", m.split("/")[2], "--timeout", "60"])
        if rc == 0 and not missing():
            print(f"  {OK} 必需依赖装好了（语音输入可能不可用）")
            return True
    return False


def check_ftp() -> bool:
    print("\n③ 数据：实测从课题组 FTP 取一个小文件")
    try:
        sys.path.insert(0, str(ROOT))
        from orchestrator import ftp_catalog as fc
        remote = ("/group3/ATM_new/dailyforecast/storm_surge_point_system/nc_file/"
                  "storm_surge_forecast_sp_XMN_20260916-20260922.nc")
        lp = fc.fetch(remote)
        if lp and Path(lp).exists():
            print(f"  {OK} 取数正常：{Path(lp).name}（{Path(lp).stat().st_size} 字节）")
            return True
        print(f"  {BAD} 取不到数据（看上面的 [ftp_catalog] 提示；"
              f"先确认 .env 里 FTP 四项填对，可跑 scripts/check_ftp.py）")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 取数异常：{type(e).__name__}: {e}")
        return False


def check_draw() -> bool:
    print("\n④ 出图：真画一张小图（含中文标题 + 海岸线）")
    try:
        import matplotlib
        matplotlib.use("Agg")
        sys.path.insert(0, str(ROOT))
        from modules import plotstyle
        import matplotlib.pyplot as plt
        plotstyle.setup()
        fig = plt.figure(figsize=(6, 4.6))
        ax = plotstyle.map_axes(fig, [0.06, 0.07, 0.86, 0.84], [117, 120, 23, 26])
        ax.set_title("修复自检：闽南近海", fontsize=13)
        out = ROOT / "stormdata" / "figures" / "_repair_test.png"
        p = plotstyle.save(fig, out, dpi=100)
        print(f"  {OK} 出图正常：{Path(p).name}")
        return True
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"  {BAD} 出图失败：{type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def check_version() -> bool:
    """判断手上这份代码是新是旧（避免用户在旧目录里反复试）。"""
    print("\n⓪ 代码版本")
    ver = "未知"
    vf = ROOT / "VERSION.txt"
    if vf.exists():
        for line in vf.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("版本号"):
                ver = line.split(":", 1)[1].strip()
                break
    print(f"  版本号：{ver}")

    cat = ROOT / "orchestrator" / "ftp_catalog.py"
    fresh = False
    if cat.exists():
        txt = cat.read_text(encoding="utf-8", errors="ignore")
        fresh = "VERSION-MARKER: fetch-fail-fix-v1" in txt
    if fresh:
        print(f"  {OK} 含下载失败修复（新代码）")
    else:
        print(f"  {BAD} **这是旧代码**：缺少'下载失败不再返回假路径'的修复。")
        print("     旧代码会让「下载失败」静默通过，最后报 "
              "FileNotFoundError: ... .nc 不存在，而且看不出原因。")
        print("     → 请到 GitHub 重新下载 ZIP，解压到**新文件夹**，")
        print("       把旧的 .env 拷过去，再双击 1-一键部署.bat 或 7-一键修复.bat")
    # 其他关键修复的探针
    probes = [
        ("orchestrator/llm.py", "默认直接做", "地点+灾种直接出图（不再反问）"),
        ("modules/visualize.py", "visualize_errors", "出图失败显示在对话里"),
        ("requirements.txt", "cartopy", "requirements 含 cartopy"),
        ("deploy/setup_windows.ps1", "--isolated", "部署脚本 pip 参数修正"),
    ]
    for rel, marker, desc in probes:
        p = ROOT / rel
        ok = p.exists() and marker in p.read_text(encoding="utf-8", errors="ignore")
        print(f"  {OK if ok else WARN} {desc}")
    return fresh


def main() -> int:
    ap = argparse.ArgumentParser(description="一键修复并自检")
    ap.add_argument("--check", action="store_true", help="只看不装")
    args = ap.parse_args()

    print("=" * 70)
    print("一键修复 + 自检")
    print("=" * 70)
    print(f"项目目录：{ROOT}")
    print(f"解释器  ：{PY if PY.exists() else sys.executable}")
    if not PY.exists():
        print(f"  {WARN} 没找到 .venv，将用当前解释器继续（建议先跑一键部署）")

    fresh = check_version()

    print("\n① 代理")
    cleared = clear_proxy()
    print(f"  {OK} 已清空代理环境变量" + (f"（原值：{'; '.join(cleared)}）" if cleared else "（本来就没有）"))

    ok_dep = do_install(args.check)
    ok_ftp = check_ftp()
    ok_draw = check_draw()

    print("\n" + "=" * 70)
    print("结果")
    print("=" * 70)
    print(f"  {OK if fresh else BAD} 代码版本")
    print(f"  {OK if ok_dep else BAD} 依赖")
    print(f"  {OK if ok_ftp else BAD} 取数（FTP）")
    print(f"  {OK if ok_draw else BAD} 出图")
    if fresh and ok_dep and ok_ftp and ok_draw:
        print(f"\n{OK} 全部通过：现在双击 2-启动.bat 就能正常问答+出图了")
    elif not fresh:
        print(f"\n{BAD} 先解决代码版本问题（重新下载 ZIP），再回来看其余各项")
    else:
        print(f"\n{WARN} 还有没过的项，请把本页完整输出发给技术支持（含报错行）")
    print("=" * 70)
    return 0 if (fresh and ok_dep and ok_ftp and ok_draw) else 1


if __name__ == "__main__":
    sys.exit(main())
