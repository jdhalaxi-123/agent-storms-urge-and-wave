# -*- coding: utf-8 -*-
"""安装体检：一条命令查全新电脑上"装了没有、装全了没有、能不能出图"。

用法（项目目录下）：
    .venv\\Scripts\\python.exe scripts\\check_install.py

检查项：
    ① Python 与版本
    ② 运行依赖（分类显示：数据 / 出图 / 界面 / 语音）
    ③ 关键文件是否齐全（缺一个都可能让某类问题失效）
    ④ 地图岸线数据 assets/cartopy 是否就位
    ⑤ **真出图冒烟测试**：用 cartopy 画一张小图（含中文标题），
       能存出 PNG 才算画图链路可用
    ⑥ 配置（.env 是否齐全：DeepSeek / FTP）
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK, BAD, WARN = "✅", "❌", "⚠️"

DEPS = {
    "数据处理": ["numpy", "pandas", "xarray", "netCDF4", "scipy"],
    "出图": ["matplotlib", "cartopy", "shapely", "pyproj"],
    "界面": ["gradio", "openai", "yaml", "docx"],
    "语音（可选）": ["faster_whisper", "tencentcloud"],
}

NEED_FILES = [
    "main.py", "requirements.txt", ".env.example",
    "orchestrator/engine.py", "orchestrator/llm.py", "orchestrator/ftp_catalog.py",
    "orchestrator/paths.py", "orchestrator/geo_domain.py",
    "modules/ai_daily.py", "modules/geo_stats.py", "modules/assess.py",
    "modules/brief.py", "modules/visualize.py", "modules/plotstyle.py",
    "modules/landmask.py", "modules/viz_extra.py", "modules/station_table.py",
    "scripts/check_ftp.py", "scripts/daily_prewarm.py",
]


def main() -> int:
    print("=" * 70)
    print("安装体检：风暴潮与海浪智能预报助手")
    print("=" * 70)
    issues: list = []

    print(f"\n① Python\n  {OK} {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 9):
        issues.append("Python 版本过低（建议 3.10+）")
    # 是否在用项目自带的 .venv（部署包会创建），用系统 Python 容易缺依赖
    venv_py = (ROOT / ".venv" / "Scripts" / "python.exe")
    in_venv = (venv_py.exists() and Path(sys.executable).resolve() == venv_py.resolve()) \
        or ("venv" in sys.prefix.lower())
    if in_venv:
        print(f"  {OK} 运行在项目虚拟环境里（.venv）")
    else:
        print(f"  {WARN} 当前用的是**系统 Python**，不是项目自带的 .venv")
        if not venv_py.exists():
            print("       → 本项目还没建 .venv。推荐用根目录的 1-一键部署.bat 装，")
            print("         它会自动建 .venv 并把全部依赖装进去（互不干扰）")
        else:
            print(f"       → 项目里已有 .venv，请改用：{venv_py}")
        issues.append("没在项目 .venv 里运行（依赖容易缺、也可能与系统 Python 冲突）")

    print("\n② 运行依赖")
    for group, mods in DEPS.items():
        miss = []
        for m in mods:
            try:
                importlib.import_module(m)
            except Exception:  # noqa: BLE001
                miss.append(m)
        if miss:
            tag = WARN if "可选" in group else BAD
            print(f"  {tag} {group}: 缺少 {', '.join(miss)}")
            if "可选" not in group:
                issues.append(f"缺依赖（{group}）：{' '.join(miss)}")
        else:
            print(f"  {OK} {group}: {', '.join(mods)}")

    print("\n③ 关键文件")
    missing_files = [f for f in NEED_FILES if not (ROOT / f).exists()]
    if missing_files:
        for f in missing_files:
            print(f"  {BAD} 缺 {f}")
        issues.append(f"缺 {len(missing_files)} 个关键文件（代码不是最新版，建议用最新部署包）")
    else:
        print(f"  {OK} {len(NEED_FILES)} 个关键文件齐全")

    print("\n④ 地图岸线数据")
    land = ROOT / "assets" / "cartopy" / "shapefiles" / "natural_earth" / "physical" / "ne_10m_land.shp"
    coast = ROOT / "assets" / "cartopy" / "shapefiles" / "natural_earth" / "physical" / "ne_10m_coastline.shp"
    if land.exists() and coast.exists():
        print(f"  {OK} assets/cartopy 就位（陆地 + 海岸线）")
    else:
        print(f"  {WARN} assets/cartopy 不完整 → 首次出图会尝试联网下载（可能很慢或失败）")
        print("       修复：从已装好的机器拷 assets/cartopy 整个目录过来（约 23 MB）")
        issues.append("地图岸线数据缺失（可联网自动下载，但建议本地拷贝）")

    print("\n⑤ 出图冒烟测试（真画一张小图）")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import cartopy.crs as ccrs
        import matplotlib.pyplot as plt

        sys.path.insert(0, str(ROOT))
        from modules import plotstyle
        plotstyle.setup()

        fig = plt.figure(figsize=(6, 4.6))
        ax = plotstyle.map_axes(fig, [0.06, 0.07, 0.86, 0.84], [117, 120, 23, 26])
        ax.set_title("出图测试：闽南近海", fontsize=13)
        out = ROOT / "stormdata" / "figures" / "_selftest.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        p = plotstyle.save(fig, out, dpi=100)
        size = Path(p).stat().st_size
        print(f"  {OK} 出图成功：{Path(p).name}（{size/1024:.0f} KB）")
        print("     这张图能打开、海岸线正常、中文标题不乱码 → 画图链路可用")
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"  {BAD} 出图失败：{type(e).__name__}: {e}")
        traceback.print_exc()
        issues.append("出图链路不可用（见上面的报错）")

    print("\n⑥ 配置")
    env = ROOT / ".env"
    if not env.exists():
        print(f"  {BAD} 没有 .env（DeepSeek 与 FTP 都没配）")
        issues.append("缺 .env 配置")
    else:
        cfg = {}
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
        ds = cfg.get("DEEPSEEK_API_KEY", "")
        ftp = [cfg.get(k, "") for k in ("FTP_HOST", "FTP_USER", "FTP_PASS")]
        if ds.startswith("sk-") and "你的" not in ds:
            print(f"  {OK} DeepSeek Key 已配置（{ds[:5]}…{ds[-4:]}）")
        else:
            print(f"  {BAD} DeepSeek Key 未配置或仍是占位符")
            issues.append("DeepSeek Key 未配置（提问会失败）")
        if all(ftp) and "你的" not in "".join(ftp):
            print(f"  {OK} FTP 已配置（{cfg.get('FTP_HOST')}:{cfg.get('FTP_PORT')} / {cfg.get('FTP_USER')}）")
        else:
            print(f"  {BAD} FTP 未配置或仍是占位符 → 双击 5-配置FTP.bat 填一次")
            issues.append("FTP 未配置（取不到数据）")

    print("\n" + "=" * 70)
    if not issues:
        print(f"{OK} 体检通过：这台电脑可以正常问答、出图、取数")
    else:
        print(f"{WARN} 发现 {len(issues)} 个问题：")
        for i, s in enumerate(issues, 1):
            print(f"   {i}. {s}")
        print("\n按问题对症修复：")
        if any("界面" in s or "数据处理" in s for s in issues):
            print("  ▸ 缺运行依赖（gradio/openai 等）——一次性装齐：")
            print("      <venv>\\Scripts\\python.exe -m pip install -r requirements.txt \\")
            print("          -i https://pypi.tuna.tsinghua.edu.cn/simple")
            print("    （没建 .venv 的话：直接双击根目录的 1-一键部署.bat 最省事）")
        if any("出图" in s for s in issues):
            print("  ▸ 缺画图依赖：")
            print("      <venv>\\Scripts\\python.exe -m pip install cartopy shapely pyproj \\")
            print("          -i https://pypi.tuna.tsinghua.edu.cn/simple")
        if any("venv" in s for s in issues):
            print("  ▸ 建议改用项目虚拟环境（部署包会创建 .venv，依赖互不干扰）")
        if any("地图" in s for s in issues):
            print("  ▸ 地图岸线数据：可以联网自动下载（跑一次⑤的冒烟测试即可），")
            print("    或从已装好的机器拷 assets/cartopy 整个目录（约 23 MB）")
        if any("FTP" in s for s in issues):
            print("  ▸ FTP：双击 5-配置FTP.bat 填一次（或手改 .env 的 FTP_ 四行）")
        if any("Key" in s for s in issues):
            print("  ▸ DeepSeek Key：改 .env 里 DEEPSEEK_API_KEY 一行")
        if any("文件" in s for s in issues):
            print("  ▸ 代码不是最新：用最新的 stormsurge-agent-部署包-*.zip 重新解压覆盖")
        print("\n  改完后重跑本脚本确认")
    print("=" * 70)
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
