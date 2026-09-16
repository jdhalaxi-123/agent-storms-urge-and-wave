"""模块⑤ 可视化：生成图表。

按灾种出图：
    - wave 灾种：海浪波高过程曲线（M1/R1 采样，hs）
    - storm_surge：站点风暴潮增水过程曲线（叠加预警阈值线）
文件名与标题带时间窗（如 3天/5天），确保不同窗口生成不同图。
"""
from pathlib import Path
from typing import Any, Dict

from orchestrator.contract import ModuleContext
from orchestrator import paths

# 图片输出目录：统一落在数据根目录下（默认 <项目>\stormdata\figures）
OUT_DIR = paths.FIGURES_DIR

THRESH_LINES = [(30, "蓝色"), (50, "黄色"), (80, "橙色"), (120, "红色")]
WAVE_THRESH = [(2.5, "蓝色"), (4.0, "黄色"), (6.0, "橙色"), (9.0, "红色")]

# 风场读入内存前的裁剪范围（lon_min, lon_max, lat_min, lat_max），
# 每日风场文件约 260 MB，先裁再读可显著省内存
WIND_BOX = (108.0, 136.0, 8.0, 36.0)


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
    # 任意采样点：文件名带上点位，避免不同地点的图互相覆盖
    pt = ctx.request.get("point")
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        try:
            parts.append("P%.2f_%.2f" % (float(pt[0]), float(pt[1])))
        except (TypeError, ValueError):
            pass
    return "_".join(parts) if parts else "全部"


def _draw_ai_field(OUT_DIR: Path, ctx: ModuleContext, tag: str) -> str:
    """场查询：区域内**过程最大增水/浪高**空间分布（课题三投产图样式）。

    - cartopy 底图 + Natural Earth 海岸线 + 灰色陆地
    - `jet` 配色：浪高固定 0~8 m，增水按量级取整
    - 海浪叠加**海况等级线**（小浪…怒涛）；增水标出区域峰值与四色警戒参考
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from . import plotstyle

    plotstyle.setup()

    info = ctx.results.get("ai_field") or {}
    fld = info.get("field")
    st = info.get("stats") or {}
    box = info.get("box")
    if not fld or not st:
        return ""

    lat, lon = np.asarray(fld["lat"]), np.asarray(fld["lon"])
    is_wave = info.get("kind") == "wave"
    arr = fld["hs_m"] if is_wave else fld["surge_cm"]
    if arr.ndim == 2:
        arr = arr[None, ...]
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)   # 陆地掩膜会造出全 NaN 切片
        mx = np.nanmax(arr, axis=0) if arr.ndim == 3 else arr
        LON, LAT = np.meshgrid(lon, lat)
        if box:
            m = (LON >= box[0]) & (LON <= box[1]) & (LAT >= box[2]) & (LAT <= box[3])
            mx_show = np.where(m, mx, np.nan)
        else:
            mx_show = mx

    region = ctx.request.get("region", "")
    unit = "m" if is_wave else "cm"
    label = "过程最大有效波高 (m)" if is_wave else "过程最大风暴增水 (cm)"

    extent = [float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())]
    if box:
        extent = [box[0], box[1], box[2], box[3]]

    finite = mx_show[np.isfinite(mx_show)]
    if not finite.size:
        return ""
    vmax_abs = float(np.nanmax(finite))
    if is_wave:
        vmin, vmax, cmap = 0.0, 8.0, "jet"
        ticks = [0, 2, 4, 6, 8]
    else:
        vmin, vmax, cmap = 0.0, max(plotstyle.nice_vmax(vmax_abs, 5.0), 10.0), "jet"
        ticks = np.linspace(vmin, vmax, 6)

    fig = plt.figure(figsize=(8.8, 6.6))
    ax = plotstyle.map_axes(fig, [0.055, 0.06, 0.78, 0.86], extent)
    pc = ax.pcolormesh(LON, LAT, mx_show, cmap=cmap, vmin=vmin, vmax=vmax,
                       shading="auto", zorder=2)
    if is_wave:
        plotstyle.add_sea_state(ax, LON, LAT, mx_show)
    plotstyle.add_colorbar(fig, ax, pc, label, ticks, shrink=0.85, pad=0.02)

    # 区域峰值
    if st.get("peak_lon") is not None:
        plo, pla = st["peak_lon"], st["peak_lat"]
        pk = st.get("max_m") if is_wave else st.get("max_cm")
        ax.plot([plo], [pla], marker="*", markersize=17, color="#d6001c",
                markeredgecolor="white", markeredgewidth=1.0, zorder=8)
        # 标注框始终朝图内放：峰值在下半部→标注放上面，反之放下面；左右同理
        mid_lon = (extent[0] + extent[1]) / 2
        mid_lat = (extent[2] + extent[3]) / 2
        dx = (extent[1] - extent[0]) * 0.32
        dy = (extent[3] - extent[2]) * 0.16
        tx = plo - dx if plo > mid_lon else plo + dx * 0.25
        ty = pla + dy if pla < mid_lat else pla - dy
        ax.annotate(f"区域峰值 {pk} {unit}\n({plo}°E, {pla}°N)",
                    xy=(plo, pla), xytext=(tx, ty), fontsize=9, color="#d6001c",
                    ha="center", va="center", zorder=9,
                    bbox=dict(fc="white", alpha=0.85, ec="#d6001c", lw=0.8, pad=2.5),
                    arrowprops=dict(arrowstyle="->", color="#d6001c", lw=1.0))

    # 本站位置
    for nm, (slo, sla) in (("厦门", (118.25, 24.50)), ("崇武", (119.00, 25.00)),
                           ("晋江", (118.50, 24.50)), ("东山", (117.50, 23.75))):
        if not (extent[0] <= slo <= extent[1] and extent[2] <= sla <= extent[3]):
            continue
        ax.plot([slo], [sla], marker="o", markersize=3.4, color="#0033cc",
                markeredgecolor="white", markeredgewidth=0.5, zorder=6)

    typh = str(ctx.request.get("typhoon", "") or "")
    title = f"{region} {'过程最大有效波高' if is_wave else '过程最大风暴增水'}空间分布"
    if typh:
        title = f"{typh} 号台风 · " + title
    if fld.get("date"):
        title += f"（起报 {fld.get('date')}）"
    ax.set_title(title, fontsize=13, pad=8)

    sub_txt = (f"区域最大 {st.get('max_m') if is_wave else st.get('max_cm')} {unit}"
               f"　格点 {st.get('n_cells')} 个　时长 {fld.get('n_times')} 小时")
    ax.text(0.012, 0.022, sub_txt, transform=ax.transAxes, fontsize=8.5,
            color="#333333", zorder=8,
            bbox=dict(fc="white", alpha=0.75, ec="#cccccc"))

    rgn_tag = "".join(ch for ch in str(region) if ch.isalnum() or ch in "东南西北海峡")[:10] or "区域"
    out = OUT_DIR / f"field_ai_{('wave' if is_wave else 'surge')}_{rgn_tag}_{tag}.png"
    return plotstyle.save(fig, out, dpi=150)


def _mark_point(ax, ctx: ModuleContext):
    """在空间分布图上标注用户查询的目标点。"""

    pt = ctx.request.get("point")
    if not (isinstance(pt, (list, tuple)) and len(pt) >= 2):
        return
    try:
        lo, la = float(pt[0]), float(pt[1])
    except (TypeError, ValueError):
        return
    name = str(ctx.request.get("point_name", "") or "")
    ax.plot([lo], [la], marker="*", markersize=13, color="#d6001c",
            markeredgecolor="white", markeredgewidth=0.8, zorder=6)
    ax.annotate(f" {name}({lo:.2f}°E,{la:.2f}°N)" if name else f" ({lo:.2f}°E,{la:.2f}°N)",
                (lo, la), textcoords="offset points", xytext=(7, 4),
                fontsize=8, color="#d6001c", zorder=6)



def run(ctx: ModuleContext) -> ModuleContext:
    images = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _setup_cn_font()

        disaster = ctx.request.get("disaster", "storm_surge")
        plot = str(ctx.request.get("plot", "") or "").strip().lower()
        tag = _tag(ctx)
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        def want(kind: str) -> bool:
            """是否需要某类图。

            - 明确指定 plot（wind/surge_station/surge_field/wave/all）→ 只画指定类型
            - 未指定 → 按灾种给“核心图”一张：
                storm_surge → 站点增水/水位曲线
                wave        → 海浪波高曲线
              （全场分布、风场等按需索取，不再默认全给）
            """
            if plot:
                return plot in (kind, "all")
            if kind == "wave":
                return disaster == "wave"
            if kind == "surge_station":
                return disaster != "wave"
            return False

        # ===== 场查询/区域预报：出区域分布图（风暴潮/海浪）=====
        # 注意：用户明确要别的图（如 wind 风场、surge_station 站点曲线）时，
        # 不要抢着画区域增水分布图——「问什么画什么」。
        field_ok = (not plot) or (plot in ("all", "surge_field", "wave"))
        if field_ok and (ctx.request.get("field_query") or ctx.results.get("ai_field")):
            fp = _draw_ai_field(OUT_DIR, ctx, tag)
            if fp:
                images.append(str(fp))

        # ===== 海浪波高曲线 =====
        if want("wave"):
            geo_w = ctx.results.get("geo_stats", {}) or {}
            wsite = [s for s in (geo_w.get("sites") or []) if s.get("series_wave_m")]
            ws = ctx.results.get("wave_stats", {}) or {}
            series = ws.get("series") or []
            if wsite:
                # 站点海浪：直接走站点过程曲线（与增水曲线同一套版式）
                p = _draw_surge(OUT_DIR, wsite, ctx, tag)
                if p:
                    images.append(str(p))
            elif series:
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

        # ===== 站点增水/水位过程曲线 =====
        if want("surge_station"):
            geo = ctx.results.get("geo_stats", {}) or {}
            sites = geo.get("sites") or []
            if sites:
                p = _draw_surge(OUT_DIR, sites, ctx, tag)
                if p:
                    images.append(str(p))

        # ===== 全场增水空间分布图（数值 + AI/融合 + 差异） =====
        # 每日区域查询已经用 AI 当天场画过区域分布图（ai_field），
        # 不要再用本地遗留的个例文件画一遍（曾出现"问福建沿海的场，
        # 画出来的是 2526 台风旧场图"）。
        if want("surge_field") and not ctx.results.get("ai_field"):
            field_imgs = _draw_field_map(OUT_DIR, ctx, tag)
            images.extend(field_imgs)

        # ===== 风场图（风速填色 + 风向箭头） =====
        if want("wind"):
            wind_imgs = _draw_wind_field(OUT_DIR, ctx, tag)
            images.extend(wind_imgs)

        # ===== 风 + 浪 双联图（课题三投产 GIF 的同款排布） =====
        if want("wind_wave"):
            try:
                from . import viz_extra
                images.extend(viz_extra.draw_wind_wave_pair(OUT_DIR, ctx, tag))
            except Exception as e:  # noqa: BLE001
                print(f"[visualize] 风浪双联图失败: {e}")

        # ===== 风 + 浪 动图（明确要"动图/animation"时才做，较慢） =====
        if plot in ("gif", "animation", "动图", "动画"):
            try:
                from . import viz_extra
                images.extend(viz_extra.draw_wind_wave_gif(OUT_DIR, ctx, tag))
            except Exception as e:  # noqa: BLE001
                print(f"[visualize] 动图失败: {e}")

        # ===== 预报 vs 实测 密度散点（台风个例有实测时） =====
        if want("validation"):
            try:
                from . import viz_extra
                images.extend(viz_extra.draw_validation_density(OUT_DIR, ctx, tag))
            except Exception as e:  # noqa: BLE001
                print(f"[visualize] 实测对比图失败: {e}")

        # ===== 兜底：一张图都没出来但手上有数据 → 至少给过程曲线 =====
        # （典型场景：模型给了 plot=surge_field，但站点查询没有场数据，
        #   场图分支空转，曲线分支又被"已指定图类型"跳过 → 结果 0 张图）
        if not images:
            _geo = ctx.results.get("geo_stats", {}) or {}
            _sites = _geo.get("sites") or []
            if _sites:
                try:
                    p = _draw_surge(OUT_DIR, _sites, ctx, tag)
                    if p:
                        images.append(str(p))
                        print("[visualize] 已用站点过程曲线兜底出图")
                except Exception as e:  # noqa: BLE001
                    print(f"[visualize] 兜底曲线失败: {e}")
    except Exception as e:  # noqa: BLE001
        import traceback
        print(f"[visualize] 出图失败（不影响文字）：{e}")
        traceback.print_exc()

    ctx.results["visualize"] = {"images": images}
    return ctx


def _draw_surge(OUT_DIR: Path, sites: list, ctx: ModuleContext, tag: str) -> str:
    """站点增水过程曲线：对齐课题三投产图版式
    （14.8×4.8、dpi150、时间轴 `%m%d %H:%M`、英文月日刻度），
    并保留我们的**四色警戒参考线**（他们业务图里没有，是我们的加分项）。
    """
    import datetime

    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np

    geo = ctx.results.get("geo_stats", {}) or {}
    region = geo.get("region") or ctx.request.get("region") or "目标海域"
    is_wave = str(ctx.request.get("disaster", "")) == "wave"
    path = OUT_DIR / (f"wave_series_{tag}.png" if is_wave else f"surge_series_{tag}.png")

    # 版式完全对齐课题三 ywh.py：
    #   figsize=(14.8,4.8) / 蓝线 'b' linewidth=2.0 / 轴标签 fontsize=14 /
    #   标题 f'{站号}-{起}-{止}' 加粗 / DayLocator + '%m%d %H:%M' / dpi=150
    fig, ax = plt.subplots(figsize=(14.8, 4.8))
    first_x = last_x = None
    for si, s in enumerate(sites[:4]):
        ser = (s.get("series_full") or s.get("series_wave_m")
               or s.get("series_cm") or s.get("series") or [])
        if not ser:
            continue
        st_dt = s.get("start_dt")
        if st_dt:
            x = [st_dt + datetime.timedelta(hours=k) for k in range(len(ser))]
        else:
            x = list(range(len(ser)))
        col = "b" if len(sites) == 1 else ["b", "#2ca02c", "#ff7f0e", "#d62728"][si % 4]
        ax.plot(x, ser, linewidth=2.0, color=col,
                label=("Sig. Wave Height" if is_wave else "Storm Surge"))
        if first_x is None:
            first_x, last_x = x[0], x[-1]
        arr = np.asarray(ser, dtype=float)
        if not np.isfinite(arr).any():
            continue
        vmax = float(np.nanmax(arr))
        kmax = int(np.nanargmax(arr))
        ax.annotate(f"{vmax:.1f}", (x[kmax], vmax), textcoords="offset points",
                    xytext=(5, 6), fontsize=12, color=col,
                    bbox=dict(fc="white", alpha=0.8, ec=col, lw=0.7, pad=1.8))

    # 四色警戒参考线（我们的加分项，画细一点不抢主线）
    ths = plotstyle_wave_thresholds() if is_wave else THRESH_LINES
    for th, lab in ths:
        th_c = {"蓝色": "#1f77b4", "黄色": "#e0b400",
                "橙色": "#ff7f0e", "红色": "#d62728"}.get(lab, "#333333")
        ax.axhline(th, ls="--", lw=0.8, color=th_c, alpha=0.55)
        ax.text(0.998, th, f"{lab} {th}" + ("m" if is_wave else "cm"),
                va="bottom", ha="right", fontsize=9, color=th_c, alpha=0.85,
                transform=ax.get_yaxis_transform())

    s0 = sites[0] if sites else {}
    sname = s0.get("short") or s0.get("name", region)
    st = s0.get("start_dt") or datetime.datetime.now()
    n = len(s0.get("series_full") or s0.get("series_wave_m")
            or s0.get("series_cm") or s0.get("series") or [])
    en = st + datetime.timedelta(hours=max(n - 1, 0)) if n else st
    code = str(s0.get("code") or "") or str(sname)
    if code in ("PT", "BOX", ""):
        code = str(sname)
    is_grid_point = bool(geo.get("grid_point"))          # 模式场最近格点（非浮标单点产品）
    buoy_point = bool(geo.get("buoy_point"))             # 真·海浪单点（浮标站号）
    ax.set_xlabel("Time", fontsize=14)
    ax.set_ylabel("Sig. wave height/m" if is_wave else "Storm surge/cm", fontsize=14)
    if is_grid_point:
        ax.set_title(f"{sname}近岸(模式格点)-{st.strftime('%Y%m%d')}-{en.strftime('%Y%m%d')}",
                     fontsize=14, fontweight="bold")
    else:
        ax.set_title(f"{code}-{st.strftime('%Y%m%d')}-{en.strftime('%Y%m%d')}",
                     fontsize=14, fontweight="bold")
    try:
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m%d %H:%M"))
        fig.autofmt_xdate()
    except Exception:
        pass
    ax.tick_params(axis="x", labelsize=12)
    ax.tick_params(axis="y", labelsize=12)
    for lab in ax.get_xticklabels():
        lab.set_rotation(0)
        lab.set_ha("center")
    if first_x is not None and last_x is not None and hasattr(first_x, "year"):
        try:
            ax.set_xlim(first_x, last_x)
        except Exception:
            pass
    if len(sites) > 1:
        handles, labels = ax.get_legend_handles_labels()
        if labels:
            ax.legend(handles, labels, loc="upper left", fontsize=11, framealpha=0.85)
    fig.savefig(path, dpi=150, bbox_inches="tight")

    # 只有**真实站点产品**才按他们的命名存 TIFF（XMN_起_止.tif）：
    #   - 区域查询里的"区域峰值曲线"不是站点产品，不存；
    #   - 模式场最近格点（如"厦门近岸(模式格点)"）也不是站点产品，不存。
    region_query = bool(geo.get("field_query"))
    real_station = (not region_query) and (not is_grid_point)
    if real_station:
        try:
            tif = OUT_DIR / f"{code}_{st.strftime('%Y%m%d')}_{en.strftime('%Y%m%d')}.tif"
            fig.savefig(tif, dpi=150, format="tiff", bbox_inches="tight")
        except Exception:
            pass
    plt.close(fig)
    return str(path)


def plotstyle_wave_thresholds():
    """浪高四色阈值（蓝2.5/黄4.0/橙6.0/红9.0 m）。"""
    return [(2.5, "蓝色"), (4.0, "黄色"), (6.0, "橙色"), (9.0, "红色")]


def _draw_mesh_surge_map(OUT_DIR: Path, ctx: ModuleContext, path: str, tag: str) -> str:
    """非结构三角网格数据的"过程最大增水"全场分布图（FTP/Ensemble 数据）。

    - 增水 = elev_surge（若有）或 elev_all - elev_tide
    - 用 tri 三角连通 + tripcolor 绘制；分块读取时间维以控制内存
    - 指定日期时只统计该日期内的最大增水
    """
    import numpy as np
    import xarray as xr
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        ds = xr.open_dataset(path, decode_times=True)
    except Exception:
        return ""

    try:
        if "lon" not in ds.variables or "lat" not in ds.variables or "tri" not in ds.variables:
            return ""
        lon = np.asarray(ds["lon"].values).ravel()
        lat = np.asarray(ds["lat"].values).ravel()
        tri = np.asarray(ds["tri"].values, dtype=int)
        if tri.ndim != 2 or tri.shape[1] != 3:
            return ""
        tri = tri - 1  # 1-based -> 0-based

        # 时间维名
        tname = None
        for cand in ("time", "valid_time"):
            if cand in ds.variables:
                tname = cand
                break
        if tname is None:
            return ""
        times = np.asarray(ds[tname].values).ravel()
        n_t = len(times)

        # 时间索引（可被日期过滤）
        idx = np.arange(n_t)
        target_date = _req_date(ctx)
        if target_date is not None:
            dates = _times_to_dates(times, path)
            if dates is not None:
                td = target_date
                if getattr(td, "year", 2000) == 2000:
                    try:
                        td = td.replace(year=int(str(dates[0])[:4]))
                    except Exception:
                        pass
                sel = (dates == np.datetime64(td))
                if not sel.any():
                    return ""
                idx = np.where(sel)[0]

        # 增水来源
        has_surge = "elev_surge" in ds.variables
        has_all = "elev_all" in ds.variables
        has_tide = "elev_tide" in ds.variables
        if not has_surge and not (has_all and has_tide):
            return ""

        # 分块计算逐节点/逐面时间最大值
        best = None
        chunk = 48
        for s in range(0, len(idx), chunk):
            block_idx = idx[s:s + chunk]
            if has_surge:
                block = np.asarray(ds["elev_surge"].values[:, block_idx], dtype=float)
            else:
                block = (np.asarray(ds["elev_all"].values[:, block_idx], dtype=float)
                         - np.asarray(ds["elev_tide"].values[:, block_idx], dtype=float))
            m = np.nanmax(block, axis=1)
            best = m if best is None else np.maximum(best, m)
        if best is None:
            return ""
        # m -> cm
        field = best * 100.0

        # 陆地掩膜：字段长度与节点数一致时按节点 depth 屏蔽；
        # 与三角形数一致（Ensemble 面中心量）时按三角形三节点 depth 屏蔽。
        if "depth" in ds.variables:
            depth = np.asarray(ds["depth"].values).ravel()
            if len(depth) == field.size:
                field = np.where(depth > 0, field, np.nan)
            elif len(depth) == lon.size and field.size == tri.shape[0]:
                wet = depth > 0
                face_wet = wet[tri].all(axis=1)
                field = np.where(face_wet, field, np.nan)
            shading_mode = "gouraud" if field.size == lon.size else "flat"
        else:
            shading_mode = "gouraud" if field.size == lon.size else "flat"

        typh = str(ctx.request.get("typhoon", "") or "")
        date_txt = ""
        if target_date is not None:
            try:
                date_txt = f" {np.datetime64(target_date)}"[:11]
            except Exception:
                date_txt = ""

        import matplotlib.tri as mtri
        triang = mtri.Triangulation(lon, lat, tri)
        finite = field[np.isfinite(field)]
        if finite.size == 0:
            return ""
        # 稳健色标：取 99 分位，避免个别异常节点拉爆色标
        vmax = float(np.nanpercentile(finite, 99))
        vmax = max(vmax, 50.0)
        peak = float(np.nanmax(finite))

        fig, ax = plt.subplots(figsize=(7.4, 4.6), dpi=110)
        tp = ax.tripcolor(triang, field, shading=shading_mode, cmap="YlOrRd", vmin=0, vmax=vmax)
        cb = fig.colorbar(tp, ax=ax, shrink=0.9)
        cb.set_label("过程最大增水 (cm)", fontsize=8)
        ax.set_xlim(114.5, 127.5)
        ax.set_ylim(17.0, 29.5)
        title = f"{typh}台风 全场最大风暴增水分布" if typh else "全场最大风暴增水分布"
        if date_txt:
            title += f"（{date_txt}）"
        title += f"  区域峰值约 {vmax:.0f} cm"
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("经度", fontsize=9)
        ax.set_ylabel("纬度", fontsize=9)
        ax.tick_params(labelsize=8)
        _mark_point(ax, ctx)
        fig.tight_layout(pad=1.0)
        fp = OUT_DIR / f"field_mesh_{tag}.png"
        fig.savefig(fp, bbox_inches="tight")
        plt.close(fig)
        return str(fp)
    except Exception:
        return ""
    finally:
        try:
            ds.close()
        except Exception:
            pass


def _draw_field_map(OUT_DIR: Path, ctx: ModuleContext, tag: str) -> list:
    """全场增水空间分布图。

    A) 结构化网格（2526 的 output_0 数值 + output_4 AI/融合）→ 对比图组
    B) 非结构三角网格（FTP/Ensemble 的 *.nc：elev_all/elev_tide/elev_surge + tri）
       → 过程最大增水分布（tripcolor）
    """
    import numpy as np
    import xarray as xr

    paths = ctx.files.get("surge_files") or []
    num_p = next((p for p in paths if "output_0" in p), None)
    ai_p = next((p for p in paths if "output_4" in p), None)

    # ---- B) 非结构网格兜底 ----
    if not (num_p or ai_p):
        mesh_imgs = []
        for p in paths[:2]:
            img = _draw_mesh_surge_map(OUT_DIR, ctx, p, tag)
            if img:
                mesh_imgs.append(img)
        return mesh_imgs

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
        _mark_point(ax, ctx)
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


def _req_date(ctx: ModuleContext):
    """解析请求中的目标日期 -> datetime.date 或 None。"""
    try:
        from . import geo_stats
        return geo_stats._parse_target_date(ctx.request.get("date", ""))
    except Exception:
        return None


def _times_to_dates(times, src_name: str):
    """把时间数组转成日期数组(datetime64[D])，兼容 datetime64 与小时序号。

    - datetime64：直接降精度到日
    - 数字（小时序号）：从文件名解析起始日期后累加
    """
    import re

    import numpy as np

    arr = np.asarray(times)
    if arr.size == 0:
        return None
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[D]")
    # 数字：从文件名解析起点（如 atm_forecast_20251105.nc / 2025110800.nc）
    m = re.search(r"(\d{4})(\d{2})(\d{2})", str(src_name))
    if not m:
        return None
    try:
        base = np.datetime64(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
        hours = np.asarray(arr, dtype=float).astype("int64")
        return base + hours.astype("timedelta64[h]")
    except Exception:
        return None


def _draw_wind_field(OUT_DIR: Path, ctx: ModuleContext, tag: str) -> list:
    """风场图：风速填色 + 风向箭头。

    时刻选择规则：
      - 指定了日期(date) -> 取“该日期内”风速最强时刻
      - 未指定        -> 取“关注海域(台湾海峡/厦门周边)”风速最强时刻
    兼容结构：标准 ERA5 / MATLAB 转存 / 模式风场(wind_x,wind_y)；多文件自动遍历。
    """
    import numpy as np
    import xarray as xr
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = [p for p in (ctx.files.get("wind_files") or []) if p]
    if not paths:
        return []

    target_date = _req_date(ctx)

    # 关注海域（默认台湾海峡/厦门周边）：优先取"该海域风速最强时刻"，
    # 台风靠近时中心在图内更完整、也更贴合业务关注区。
    FOCUS = (117.0, 123.0, 21.0, 26.5)  # lon_min, lon_max, lat_min, lat_max

    best = None  # 关注海域最强时刻
    best_global = None  # 全域最强（兜底）
    for path in paths[:10]:
        ds = None
        try:
            ds = xr.open_dataset(path, decode_times=True)
            uvar = next((v for v in ("u10", "u10m", "uwnd", "wind_x", "U10")
                         if v in ds.variables), None)
            vvar = next((v for v in ("v10", "v10m", "vwnd", "wind_y", "V10")
                         if v in ds.variables), None)
            if not uvar or not vvar:
                uvar = next((v for v in ds.variables
                             if v.lower() in ("u", "u_component_of_wind")), None)
                vvar = next((v for v in ds.variables
                             if v.lower() in ("v", "v_component_of_wind")), None)
            if not uvar or not vvar:
                continue
            latname = lonname = None
            latv = lonv = None
            for cand in ("latitude", "lat"):
                if cand in ds.variables:
                    latname = cand
                    latv = np.asarray(ds[cand].values).ravel()
                    break
            for cand in ("longitude", "lon"):
                if cand in ds.variables:
                    lonname = cand
                    lonv = np.asarray(ds[cand].values).ravel()
                    break
            if latv is None or lonv is None:
                continue

            # 大文件友好（每日风场约 260 MB）：先按关注区适当外扩裁剪，再读进内存。
            # 兼容两种网格：① lat/lon 本身是维度（常规 NetCDF，可直接 sel）
            #               ② lat/lon 是沿 xi/eta 的辅助坐标（ROMS 风场，需按索引 isel）
            try:
                la = np.asarray(ds[latname].values).ravel()
                lo = np.asarray(ds[lonname].values).ravel()
                if la.size > 4 and lo.size > 4:
                    la0, la1 = float(np.nanmin(la)), float(np.nanmax(la))
                    lo0, lo1 = float(np.nanmin(lo)), float(np.nanmax(lo))
                    if (la0 < WIND_BOX[3] and la1 > WIND_BOX[2]
                            and lo0 < WIND_BOX[1] and lo1 > WIND_BOX[0]):
                        ds2 = None
                        if latname in ds.dims and lonname in ds.dims:
                            lat_slice = slice(max(la0, WIND_BOX[2]), min(la1, WIND_BOX[3]))
                            lon_slice = slice(max(lo0, WIND_BOX[0]), min(lo1, WIND_BOX[1]))
                            if la[0] > la[-1]:
                                lat_slice = slice(lat_slice.stop, lat_slice.start)
                            if lo[0] > lo[-1]:
                                lon_slice = slice(lon_slice.stop, lon_slice.start)
                            ds2 = ds.sel({latname: lat_slice, lonname: lon_slice})
                        else:
                            ldim = ds[latname].dims[0]
                            odim = ds[lonname].dims[0]
                            j = np.where((la >= WIND_BOX[2]) & (la <= WIND_BOX[3]))[0]
                            i = np.where((lo >= WIND_BOX[0]) & (lo <= WIND_BOX[1]))[0]
                            if j.size >= 3 and i.size >= 3:
                                ds2 = ds.isel({ldim: slice(int(j[0]), int(j[-1]) + 1),
                                               odim: slice(int(i[0]), int(i[-1]) + 1)})
                        if ds2 is not None and ds2[latname].size > 2 and ds2[lonname].size > 2:
                            ds = ds2
                latv = np.asarray(ds[latname].values).ravel()
                lonv = np.asarray(ds[lonname].values).ravel()
            except Exception:
                latv = np.asarray(ds[latname].values).ravel()
                lonv = np.asarray(ds[lonname].values).ravel()
            nlat, nlon = len(latv), len(lonv)
            uarr = np.asarray(ds[uvar].values, dtype=float)
            varr = np.asarray(ds[vvar].values, dtype=float)
            shape = uarr.shape

            if len(shape) == 3:
                ax_lat = next((i for i, s in enumerate(shape) if s == nlat), None)
                ax_lon = next((i for i, s in enumerate(shape) if s == nlon), None)
                if ax_lat is None or ax_lon is None:
                    continue
                ax_t = next((i for i in range(3) if i not in (ax_lat, ax_lon)), None)
                if ax_t is None:
                    continue
                spd_all = np.sqrt(uarr ** 2 + varr ** 2)
                # 关注海域掩膜（通用：按轴位置放置 lat/lon 范围）
                lat_ok = (latv >= FOCUS[2]) & (latv <= FOCUS[3])
                lon_ok = (lonv >= FOCUS[0]) & (lonv <= FOCUS[1])
                shp_lat = [1, 1, 1]
                shp_lat[ax_lat] = nlat
                shp_lon = [1, 1, 1]
                shp_lon[ax_lon] = nlon
                mask3 = np.ones(shape, dtype=bool)
                mask3 = mask3 & lat_ok.reshape(shp_lat)
                mask3 = mask3 & lon_ok.reshape(shp_lon)
                spd_masked = np.where(mask3, spd_all, np.nan)
                ts = np.nanmax(spd_masked, axis=(ax_lat, ax_lon))  # 逐时刻(关注海域)
                ts_all = np.nanmax(spd_all, axis=(ax_lat, ax_lon))  # 逐时刻(全域)

                # ---- 目标日期过滤：只允许该日期的时次 ----
                date_ok = None
                tv = None
                for tname in ("valid_time", "time"):
                    if tname in ds.variables:
                        tv = np.asarray(ds[tname].values).ravel()
                        break
                if target_date is not None and tv is not None and len(tv) == shape[ax_t]:
                    dates = _times_to_dates(tv, path)
                    if dates is not None:
                        td = target_date
                        if getattr(td, "year", 2000) == 2000:
                            try:
                                td = td.replace(year=int(str(dates[0])[:4]))
                            except Exception:
                                pass
                        date_ok = (dates == np.datetime64(td))
                        if not date_ok.any():
                            continue  # 本文件不含目标日期
                        ts = np.where(date_ok, ts, np.nan)
                        ts_all = np.where(date_ok, ts_all, np.nan)

                k_focus = None
                m_focus = -1.0
                if np.any(np.isfinite(ts)):
                    k_focus = int(np.nanargmax(ts))
                    m_focus = float(np.nanmax(ts))
                # 全域最强（同受日期约束）
                m_all = float(np.nanmax(ts_all)) if np.any(np.isfinite(ts_all)) else -1.0
                k_all = int(np.nanargmax(ts_all)) if np.any(np.isfinite(ts_all)) else 0

                def _extract(k):
                    sl = [slice(None)] * 3
                    sl[ax_t] = k
                    uu_ = uarr[tuple(sl)]
                    vv_ = varr[tuple(sl)]
                    remaining = [i for i in range(3) if i != ax_t]
                    if remaining != [ax_lat, ax_lon]:
                        uu_ = uu_.T
                        vv_ = vv_.T
                    return uu_, vv_

                tlabel_all = tlabel_focus = ""
                if tv is not None:
                    try:
                        tlabel_all = str(tv[k_all])[:16].replace("T", " ")
                        tlabel_focus = str(tv[k_focus])[:16].replace("T", " ") if k_focus is not None else ""
                    except Exception:
                        tlabel_all = tlabel_focus = ""

                # 关注海域优先（指定日期时该日期即约束）
                if k_focus is not None and m_focus > 0:
                    uu_, vv_ = _extract(k_focus)
                    if uu_.shape == (nlat, nlon) and (best is None or m_focus > best["score"]):
                        best = {"score": m_focus, "max_spd": float(np.nanmax(np.sqrt(uu_ ** 2 + vv_ ** 2))),
                                "uu": uu_, "vv": vv_, "latv": latv, "lonv": lonv,
                                "tlabel": tlabel_focus, "src": path}
                # 全域兜底
                if m_all > 0:
                    uu_, vv_ = _extract(k_all)
                    if uu_.shape == (nlat, nlon) and (best_global is None or m_all > best_global["score"]):
                        best_global = {"score": m_all, "max_spd": float(np.nanmax(np.sqrt(uu_ ** 2 + vv_ ** 2))),
                                       "uu": uu_, "vv": vv_, "latv": latv, "lonv": lonv,
                                       "tlabel": tlabel_all, "src": path}
            elif len(shape) == 2:
                uu, vv = uarr, varr
                if uu.shape == (nlon, nlat):
                    uu, vv = uu.T, vv.T
                if uu.shape == (nlat, nlon):
                    m = float(np.nanmax(np.sqrt(uu ** 2 + vv ** 2)))
                    if best_global is None or m > best_global["score"]:
                        best_global = {"score": m, "max_spd": m, "uu": uu, "vv": vv,
                                       "latv": latv, "lonv": lonv, "tlabel": "", "src": path}
            else:
                continue
        except Exception:
            continue
        finally:
            if ds is not None:
                try:
                    ds.close()
                except Exception:
                    pass

    best = best or best_global
    if best is None:
        return []

    uu, vv = best["uu"], best["vv"]
    latv, lonv = best["latv"], best["lonv"]
    spd = np.sqrt(uu ** 2 + vv ** 2)
    LON, LAT = np.meshgrid(lonv, latv)
    typh = str(ctx.request.get("typhoon", "") or "")
    tlabel = best["tlabel"]

    # ===== 出图：课题三投产图样式（cartopy 底图 + jet + 风级等值线）=====
    import cartopy.crs as ccrs
    from . import plotstyle

    plotstyle.setup()
    extent = [float(np.nanmin(lonv)), float(np.nanmax(lonv)),
              float(np.nanmin(latv)), float(np.nanmax(latv))]
    # 用户点名了区域（如"福建沿海的风场"）→ 按该区域取景（外扩一点），否则用整个模式域
    fb = ctx.request.get("field_box")
    if fb and len(fb) == 4:
        pad_lon = max(0.5, (fb[1] - fb[0]) * 0.10)
        pad_lat = max(0.5, (fb[3] - fb[2]) * 0.10)
        extent = [max(extent[0], fb[0] - pad_lon), min(extent[1], fb[1] + pad_lon),
                  max(extent[2], fb[2] - pad_lat), min(extent[3], fb[3] + pad_lat)]
    extent[0] = max(extent[0], 105.0)
    extent[1] = min(extent[1], 138.0)
    extent[2] = max(extent[2], 8.0)
    extent[3] = min(extent[3], 38.0)
    if extent[1] - extent[0] < 1 or extent[3] - extent[2] < 1:
        extent = [float(np.nanmin(lonv)), float(np.nanmax(lonv)),
                  float(np.nanmin(latv)), float(np.nanmax(latv))]

    fig = plt.figure(figsize=(10.5, 7.8))
    ax = plotstyle.map_axes(fig, [0.05, 0.06, 0.79, 0.86], extent)
    pc = ax.pcolormesh(LON, LAT, spd, cmap="jet", vmin=0, vmax=25,
                       shading="auto", zorder=2, transform=ccrs.PlateCarree())
    plotstyle.add_colorbar(fig, ax, pc, "风速 (m/s)",
                           [0, 5, 10, 15, 20, 25], shrink=0.85, pad=0.02)
    # 风矢密度按"可见范围"算，取景后别只剩几根
    iv = np.where((lonv >= extent[0]) & (lonv <= extent[1]))[0]
    jv = np.where((latv >= extent[2]) & (latv <= extent[3]))[0]
    n_vis = max(len(iv), len(jv), 1)
    step = max(1, int(round(n_vis / 16.0)))
    ax.quiver(LON[::step, ::step], LAT[::step, ::step],
              uu[::step, ::step], vv[::step, ::step],
              color="k", width=0.0022, scale=380, alpha=0.9, zorder=4,
              transform=ccrs.PlateCarree())
    plotstyle.add_wind_levels(ax, LON, LAT, spd, transform=ccrs.PlateCarree())

    title = f"{typh}号台风 风场" if typh else "风场"
    if tlabel:
        title += f"　{tlabel} UTC"
    title += f"　最大风速 {best['max_spd']:.1f} m/s"
    ax.set_title(title, fontsize=13, pad=8)
    _mark_point(ax, ctx)
    fp = OUT_DIR / f"wind_field_{tag}.png"
    return [plotstyle.save(fig, fp, dpi=150)]
