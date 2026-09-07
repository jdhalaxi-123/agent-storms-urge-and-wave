"""模块⑤ 可视化：生成图表。

真实实现：按 geo_stats 的站点统计画「多站点增水过程曲线」，
叠加预警阈值线(30/50/80/120cm)与峰值标注；无数据时降级返回空。
"""
from pathlib import Path
from typing import Any, Dict

from orchestrator.contract import ModuleContext

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

THRESH_LINES = [(30, "蓝色"), (50, "黄色"), (80, "橙色"), (120, "红色")]


def _setup_cn_font() -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

        for fam in ("Microsoft YaHei", "SimHei", "KaiTi", "FangSong"):
            if any(f.name == fam for f in font_manager.fontManager.ttflist):
                plt.rcParams["font.sans-serif"] = [fam]
                plt.rcParams["axes.unicode_minus"] = False
                break
    except Exception:
        pass


def run(ctx: ModuleContext) -> ModuleContext:
    images = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _setup_cn_font()

        geo = ctx.results.get("geo_stats", {}) or {}
        sites = geo.get("sites") or []
        region = geo.get("region") or "目标海域"
        src = geo.get("source", "")

        if not sites:
            ctx.results["visualize"] = {"images": images}
            return ctx

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "surge_series_real.png"

        fig, ax = plt.subplots(figsize=(10, 4.8), dpi=110)
        colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e"]
        for si, s in enumerate(sites[:5]):
            series = s.get("series", [])
            if not series:
                continue
            ax.plot(series, lw=1.5, label=s["name"], color=colors[si % len(colors)])
            vmax = max(series)
            kmax = int(series.index(vmax))
            ax.annotate(f"{vmax:.0f}cm", (kmax, vmax),
                        textcoords="offset points", xytext=(6, 5), fontsize=8,
                        color=colors[si % len(colors)])

        # 阈值线
        for th, lab in THRESH_LINES:
            ax.axhline(th, ls="--", lw=0.8, alpha=0.6)
            ax.text(0.005, th, f"{lab} {th}cm", va="bottom", ha="left", fontsize=7, alpha=0.7, transform=ax.get_yaxis_transform())

        src_label = {"station": "站点观测数据", "grid": "网格数据", "none": ""}.get(src, "")
        ax.set_title(f"{region} 站点风暴潮增水过程曲线（{src_label or '数据'}）")
        ax.set_xlabel("过程时次（降采样）")
        ax.set_ylabel("增水 (cm)")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        images.append(str(path))
    except Exception:
        pass  # 画图失败不影响文字

    ctx.results["visualize"] = {"images": images}
    return ctx
