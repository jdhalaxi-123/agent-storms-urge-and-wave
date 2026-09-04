"""模块⑤ 可视化：生成图表。

【STUB】骨架阶段尝试用 matplotlib 画占位图；无 matplotlib 时返回空列表（只出文字）。
"""
from pathlib import Path

from orchestrator.contract import ModuleContext

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def run(ctx: ModuleContext) -> ModuleContext:
    images = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

        # 中文字体：Windows 常见字体回退（SimHei / Microsoft YaHei）
        for fam in ("Microsoft YaHei", "SimHei", "KaiTi", "FangSong"):
            if any(f.name == fam for f in font_manager.fontManager.ttflist):
                plt.rcParams["font.sans-serif"] = [fam]
                plt.rcParams["axes.unicode_minus"] = False
                break

        series = ctx.results.get("geo_stats", {}).get("series", [])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "surge_series_stub.png"

        plt.figure(figsize=(6, 3))
        plt.plot(series, marker="o")
        plt.title("增水过程曲线（占位）")
        plt.xlabel("预报时次")
        plt.ylabel("增水(cm)")
        plt.savefig(path, dpi=100)
        plt.close()
        images.append(str(path))
    except Exception:
        pass  # 无 matplotlib 时跳过，只返回文字

    ctx.results["visualize"] = {"images": images}
    return ctx
