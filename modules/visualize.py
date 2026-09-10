"""模块⑤ 可视化：生成图表。

按灾种出图：
    - wave 灾种：海浪波高过程曲线（M1/R1 采样，hs）
    - storm_surge：站点风暴潮增水过程曲线（叠加预警阈值线）
文件名与标题带时间窗（如 3天/5天），确保不同窗口生成不同图。
"""
from pathlib import Path
from typing import Any, Dict

from orchestrator.contract import ModuleContext

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

THRESH_LINES = [(30, "蓝色"), (50, "黄色"), (80, "橙色"), (120, "红色")]
WAVE_THRESH = [(2.5, "蓝色"), (4.0, "黄色"), (6.0, "橙色"), (9.0, "红色")]


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


def _tag(ctx: ModuleContext) -> str:
    """图标签：台风号 + 时间窗 + 日期，确保文件名唯一（不被不同查询覆盖）。"""
    typhoon = str(ctx.request.get("typhoon", "") or "").replace(" ", "")
    d = str(ctx.request.get("date", "") or "").strip()
    tw = str(ctx.request.get("time_window", "") or "")
    parts = []
    if typhoon:
        parts.append(typhoon[:6])
    if d and d not in ("未指定", "无", "全部", "全程"):
        parts.append(d[:10].replace("/", "").replace("-", "").replace("年", "").replace("月", "").replace("日", ""))
    elif "3" in tw and "天" in tw:
        parts.append("3天")
    elif "5" in tw and "天" in tw:
        parts.append("5天")
    elif "7" in tw and "天" in tw:
        parts.append("7天")
    else:
        parts.append("全部")
    return "_".join(parts) if parts else "全部"


def run(ctx: ModuleContext) -> ModuleContext:
    images = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _setup_cn_font()

        disaster = ctx.request.get("disaster", "storm_surge")
        tag = _tag(ctx)
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        if disaster == "wave":
            # ===== 海浪曲线 =====
            ws = ctx.results.get("wave_stats", {}) or {}
            series = ws.get("series") or []
            if series:
                path = OUT_DIR / f"wave_series_{tag}.png"
                fig, ax = plt.subplots(figsize=(6.9, 3.6), dpi=110)
                ax.plot(series, lw=1.6, color="#1f77b4")
                vmax = max(series)
                kmax = int(series.index(vmax))
                ax.annotate(f"{vmax:.2f}m", (kmax, vmax), textcoords="offset points",
                            xytext=(6, 5), fontsize=9, color="#1f77b4")
                for th, lab in WAVE_THRESH:
                    ax.axhline(th, ls="--", lw=0.8, alpha=0.6)
                    ax.text(0.005, th, f"{lab} {th}m", va="bottom", ha="left", fontsize=7,
                            alpha=0.7, transform=ax.get_yaxis_transform())
                rgn = ctx.request.get("region", "目标海域")
                ax.set_title(f"{rgn} 近岸海浪有效波高过程 ({tag})", fontsize=11)
                ax.set_xlabel("过程时次（降采样）", fontsize=9)
                ax.set_ylabel("有效波高 (m)", fontsize=9)
                ax.tick_params(labelsize=8)
                ax.grid(alpha=0.3)
                fig.tight_layout(pad=1.2)
                fig.savefig(path, bbox_inches="tight")
                plt.close(fig)
                images.append(str(path))
            # 海浪也附风暴潮站点图（双图）
            geo = ctx.results.get("geo_stats", {}) or {}
            sites = geo.get("sites") or []
            if sites:
                p2 = _draw_surge(OUT_DIR, sites, ctx, tag)
                if p2:
                    images.append(str(p2))
        else:
            # ===== 风暴潮增水曲线 =====
            geo = ctx.results.get("geo_stats", {}) or {}
            sites = geo.get("sites") or []
            if sites:
                p = _draw_surge(OUT_DIR, sites, ctx, tag)
                if p:
                    images.append(str(p))

        # ===== 全场增水空间分布图（output_0 数值 + output_4 AI/融合 对比） =====
        field_imgs = _draw_field_map(OUT_DIR, ctx, tag)
        images.extend(field_imgs)

        # ===== 风场图（ERA5 / 模式风场：风速填色 + 风向箭头） =====
        wind_imgs = _draw_wind_field(OUT_DIR, ctx, tag)
        images.extend(wind_imgs)
    except Exception:
        pass  # 画图失败不影响文字

    ctx.results["visualize"] = {"images": images}
    return ctx


def _draw_surge(OUT_DIR: Path, sites: list, ctx: ModuleContext, tag: str) -> str:
    """站点风暴潮增水曲线（项目组风格）：扁长图幅、黑色单线、
    站名+时间范围标题、英文日期X轴。一站点一张图"""
    import datetime

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    geo = ctx.results.get("geo_stats", {}) or {}
    region = geo.get("region") or ctx.request.get("region") or "目标海域"
    path = OUT_DIR / f"surge_series_{tag}.png"

    # 一张图: 单站点(若多站, 取重点或分别画到一张? 项目组风格是一站一图)
    # 简单起见: 画出 sites 里每个站折线(黑灰调), 主站黑色; 若单站 => 纯黑
    import numpy as np

    fig, ax = plt.subplots(figsize=(9.0, 2.6), dpi=110)  # 扁长
    colors = ["black", "#666666", "#999999", "#aaaaaa", "#bbbbbb"]
    for si, s in enumerate(sites[:5]):
        ser = s.get("series_full") or s.get("series_cm") or s.get("series") or []
        if not ser:
            continue
        # 构造真实时间轴(起始 start_dt, 每小时)
        st_dt = s.get("start_dt")
        if st_dt:
            import numpy as np
            x = [st_dt + datetime.timedelta(hours=k) for k in range(len(ser))]
        else:
            x = np.arange(len(ser))
        ax.plot(x, ser, lw=0.9, color=colors[si % len(colors)], label=s["name"])
        vmax = max(ser)
        kmax = int(np.argmax(ser))
        ax.annotate(f"{vmax:.0f}cm", (x[kmax], vmax), textcoords="offset points",
                    xytext=(4, 4), fontsize=7, color=colors[si % len(colors)])

    # 四色警戒虚线(蓝/黄/橙/红) —— 项目组水位图顶部风格
    warn_colors = [("blue", "#1f77b4"), ("yellow", "#d62728"), ("orange", "#ff7f0e"), ("red", "#2ca02c")]
    for th, lab in THRESH_LINES:
        th_c = {"蓝色": "#1f77b4", "黄色": "#d62728", "橙色": "#ff7f0e", "红色": "#d62728"}.get(lab, "#333")
        ax.axhline(th, ls="--", lw=0.7, color=th_c, alpha=0.7)

    # 标题: 站名(时间范围) —— 与项目组一致
    s0 = sites[0] if sites else {}
    sname = s0.get("name", region)
    st = s0.get("start_dt") or datetime.datetime.now()
    n = len(s0.get("series_full") or s0.get("series") or [])
    en = st + datetime.timedelta(hours=n) if n else st
    ax.set_title(f"{sname}({st.strftime('%Y%m%d')} 00:00-{en.strftime('%Y%m%d')} 23:00)", fontsize=10)
    ax.set_xlabel("Date", fontsize=9)
    ax.set_ylabel("Storm surge (cm)", fontsize=9)
    ax.tick_params(labelsize=8)
    # 若时间轴是日期对象, 用英文月日格式(Nov.09) 与项目组一致
    try:
        x0 = sites[0].get("start_dt")
        if x0:
            import matplotlib.dates as mdates
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b.%d"))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
            fig.autofmt_xdate(rotation=0)
    except Exception:
        pass
    if len(sites) > 1:
        ax.legend(loc="upper left", fontsize=7, framealpha=0.8)
    ax.grid(False)  # 项目组风格: 无网格
    fig.tight_layout(pad=0.8)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _draw_field_map(OUT_DIR: Path, ctx: ModuleContext, tag: str) -> list:
    """全场增水空间分布图：output_0(数值) + output_4(AI/融合) 过程最大增水对比。

    从 ctx.files['surge_files'] 找 output_0/output_4；数据大，仅取时间最大
    降低内存；无数据或缺变量时返回空。
    """
    import numpy as np
    import xarray as xr

    paths = ctx.files.get("surge_files") or []
    num_p = next((p for p in paths if "output_0" in p), None)
    ai_p = next((p for p in paths if "output_4" in p), None)
    if not (num_p or ai_p):
        return []

    out_imgs = []
    import matplotlib.pyplot as plt

    # 只选厦门周边范围(17~25N/111~119E 有数据; 用整场 lat/lon)
    def max_field(path):
        try:
            ds = xr.open_dataset(path)
            var = "elev" if "elev" in ds.variables else None
            if var is None:
                return None, None, None
            lon = ds["lon"].values if "lon" in ds.coords else None
            lat = ds["lat"].values if "lat" in ds.coords else None
            # 时间最大(逐格)
            m = ds[var].max(dim="time").values
            # 转 2D 网格(若 lon/lat 是 2D)
            if lon.ndim == 2:
                lon2, lat2 = lon, lat
            else:
                lon2, lat2 = np.meshgrid(lon, lat)
            ds.close()
            return m, lon2, lat2
        except Exception:
            return None, None, None

    for path, label, fname in [(num_p, "数值模拟", f"field_map_num_{tag}"),
                               (ai_p, "AI/融合", f"field_map_ai_{tag}")]:
        if not path:
            continue
        m, lon2, lat2 = max_field(path)
        if m is None:
            continue
        # 全场最大增水(用有效范围,陆地置nan)
        m = np.where(np.abs(m) < 1e9, m, np.nan)
        vmax = float(np.nanmax(np.abs(m))) if np.isfinite(np.nanmax(np.abs(m))) else 1.0
        fig, ax = plt.subplots(figsize=(6.9, 4.2), dpi=110)
        pc = ax.pcolormesh(lon2, lat2, m, cmap="RdBu_r", vmin=0, vmax=max(vmax, 0.5), shading="auto")
        cb = fig.colorbar(pc, ax=ax, shrink=0.9)
        cb.set_label("过程最大增水 (m)", fontsize=8)
        ax.set_title(f"2526台风 全场最大增水分布（{label}·{tag}）", fontsize=11)
        ax.set_xlabel("经度", fontsize=9)
        ax.set_ylabel("纬度", fontsize=9)
        ax.tick_params(labelsize=8)
        fig.tight_layout(pad=1.0)
        p = OUT_DIR / f"{fname}.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        out_imgs.append(str(p))

    # 两者差值图
    if num_p and ai_p:
        m0, lon2, lat2 = max_field(num_p)
        m1, _, _ = max_field(ai_p)
        if m0 is not None and m1 is not None:
            fig, ax = plt.subplots(figsize=(6.9, 4.2), dpi=110)
            d = m1 - m0
            pc = ax.pcolormesh(lon2, lat2, d, cmap="coolwarm", vmin=-0.5, vmax=0.5, shading="auto")
            cb = fig.colorbar(pc, ax=ax, shrink=0.9)
            cb.set_label("AI/融合 − 数值 (m)", fontsize=8)
            ax.set_title(f"2526台风 两方案最大增水差异（AI/融合−数值）", fontsize=11)
            ax.set_xlabel("经度", fontsize=9)
            ax.set_ylabel("纬度", fontsize=9)
            ax.tick_params(labelsize=8)
            fig.tight_layout(pad=1.0)
            p = OUT_DIR / f"field_map_diff_{tag}.png"
            fig.savefig(p, bbox_inches="tight")
            plt.close(fig)
            out_imgs.append(str(p))
    return out_imgs


def _draw_wind_field(OUT_DIR: Path, ctx: ModuleContext, tag: str) -> list:
    """风场图：风速填色 + 风向箭头（取风速最大时刻）。

    兼容三种结构：
      - 标准 ERA5：(valid_time, latitude, longitude) + u10/v10
      - MATLAB 转存：u10 维度为 (u10_dim0, u10_dim1, u10_dim2) + 独立 lat/lon/time 变量
      - 2526 output_4 内置：wind_x/wind_y (time, lat, lon)
    """
    import numpy as np
    import xarray as xr
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    wind_path = None
    wf = ctx.files.get("wind_files") or []
    if wf:
        wind_path = wf[0]
    if not wind_path:
        return []
    try:
        ds = xr.open_dataset(wind_path, decode_times=True)
    except Exception:
        return []
    out = []
    try:
        uvar = "u10" if "u10" in ds.variables else ("wind_x" if "wind_x" in ds.variables else None)
        vvar = "v10" if "v10" in ds.variables else ("wind_y" if "wind_y" in ds.variables else None)
        if uvar is None or vvar is None:
            return []
        u = ds[uvar]
        v = ds[vvar]

        # --- 识别时间维 ---
        tdim = None
        for d in u.dims:
            if d in ("valid_time", "time") or d.startswith("time"):
                tdim = d
                break

        # --- 识别经纬度 ---
        latv = lonv = None
        for cand in ("latitude", "lat"):
            if cand in ds.variables:
                latv = np.asarray(ds[cand].values).ravel()
                break
        for cand in ("longitude", "lon"):
            if cand in ds.variables:
                lonv = np.asarray(ds[cand].values).ravel()
                break
        if latv is None or lonv is None:
            return []

        # --- 取风速最大时刻 + 对齐为 (lat, lon) ---
        nlat, nlon = len(latv), len(lonv)
        # 找各轴：哪个轴等于 nlat / nlon，剩下的当作时间轴
        shape = u.shape
        ax_lat = next((i for i, s in enumerate(shape) if s == nlat), None)
        ax_lon = next((i for i, s in enumerate(shape) if s == nlon), None)
        uarr = np.asarray(u.values, dtype=float)
        varr = np.asarray(v.values, dtype=float)

        if ax_lat is not None and ax_lon is not None and len(shape) == 3:
            ax_t = next((i for i in range(3) if i not in (ax_lat, ax_lon)), None)
            # 取风速最大时刻
            if ax_t is not None:
                spd_all = np.sqrt(uarr ** 2 + varr ** 2)
                # 沿 lat/lon 轴取最大 -> 逐时刻序列
                k = int(np.nanargmax(np.nanmax(spd_all, axis=(ax_lat, ax_lon))))
                sl = [slice(None)] * 3
                sl[ax_t] = k
                uu = uarr[tuple(sl)]
                vv = varr[tuple(sl)]
                try:
                    tv = np.asarray(ds["time"].values).ravel()
                    tlabel = str(tv[k])[:16].replace("T", " ")
                except Exception:
                    tlabel = f"第{k}时次"
            else:
                uu, vv = uarr[:, :, 0], varr[:, :, 0]
                tlabel = ""
            # 转成 (lat, lon)
            if (ax_lat, ax_lon) == (0, 1):
                pass
            else:
                uu = uu.T
                vv = vv.T
        elif len(shape) == 2:
            uu, vv = uarr, varr
            if uu.shape == (nlon, nlat):
                uu, vv = uu.T, vv.T
            tlabel = ""
        else:
            return []

        if uu.shape != (nlat, nlon):
            return []

        spd = np.sqrt(uu ** 2 + vv ** 2)
        LON, LAT = np.meshgrid(lonv, latv)
        rgn = ctx.request.get("region", "") or ""
        typh = str(ctx.request.get("typhoon", "") or "")

        fig, ax = plt.subplots(figsize=(7.4, 4.4), dpi=110)
        pc = ax.pcolormesh(LON, LAT, spd, cmap="YlOrRd", shading="auto")
        cb = fig.colorbar(pc, ax=ax, shrink=0.9)
        cb.set_label("风速 (m/s)", fontsize=8)
        step = max(1, LON.shape[0] // 16)
        ax.quiver(LON[::step, ::step], LAT[::step, ::step],
                  uu[::step, ::step], vv[::step, ::step],
                  color="k", width=0.0025, scale=350, alpha=0.85)
        ax.set_title(f"{typh}台风 风场{tlabel and '（' + tlabel + '）'} 最大风速 {np.nanmax(spd):.1f} m/s", fontsize=11)
        ax.set_xlabel("经度", fontsize=9)
        ax.set_ylabel("纬度", fontsize=9)
        ax.tick_params(labelsize=8)
        fig.tight_layout(pad=1.0)
        fp = OUT_DIR / f"wind_field_{tag}.png"
        fig.savefig(fp, bbox_inches="tight")
        plt.close(fig)
        out.append(str(fp))
    except Exception:
        pass
    finally:
        ds.close()
    return out
