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
    # 任意采样点：文件名带上点位，避免不同地点的图互相覆盖
    pt = ctx.request.get("point")
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        try:
            parts.append("P%.2f_%.2f" % (float(pt[0]), float(pt[1])))
        except (TypeError, ValueError):
            pass
    return "_".join(parts) if parts else "全部"


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

        # ===== 海浪波高曲线 =====
        if want("wave"):
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

        # ===== 站点增水/水位过程曲线 =====
        if want("surge_station"):
            geo = ctx.results.get("geo_stats", {}) or {}
            sites = geo.get("sites") or []
            if sites:
                p = _draw_surge(OUT_DIR, sites, ctx, tag)
                if p:
                    images.append(str(p))

        # ===== 全场增水空间分布图（数值 + AI/融合 + 差异） =====
        if want("surge_field"):
            field_imgs = _draw_field_map(OUT_DIR, ctx, tag)
            images.extend(field_imgs)

        # ===== 风场图（风速填色 + 风向箭头） =====
        if want("wind"):
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
    import numpy as np

    geo = ctx.results.get("geo_stats", {}) or {}
    region = geo.get("region") or ctx.request.get("region") or "目标海域"
    path = OUT_DIR / f"surge_series_{tag}.png"

    # 一张图: 单站点(若多站, 取重点或分别画到一张? 项目组风格是一站一图)
    # 简单起见: 画出 sites 里每个站折线(黑灰调), 主站黑色; 若单站 => 纯黑
    fig, ax = plt.subplots(figsize=(9.0, 2.6), dpi=110)  # 扁长
    colors = ["black", "#666666", "#999999", "#aaaaaa", "#bbbbbb"]
    for si, s in enumerate(sites[:5]):
        ser = s.get("series_full") or s.get("series_cm") or s.get("series") or []
        if not ser:
            continue
        # 构造真实时间轴(起始 start_dt, 每小时)
        st_dt = s.get("start_dt")
        if st_dt:
            x = [st_dt + datetime.timedelta(hours=k) for k in range(len(ser))]
        else:
            x = np.arange(len(ser))
        ax.plot(x, ser, lw=0.9, color=colors[si % len(colors)], label=s["name"])
        arr = np.asarray(ser, dtype=float)
        if not np.isfinite(arr).any():
            continue
        vmax = float(np.nanmax(arr))
        kmax = int(np.nanargmax(arr))
        ax.annotate(f"{vmax:.0f}cm", (x[kmax], vmax), textcoords="offset points",
                    xytext=(4, 4), fontsize=7, color=colors[si % len(colors)])

    # 四色警戒虚线(蓝/黄/橙/红) —— 项目组水位图顶部风格
    warn_colors = [("blue", "#1f77b4"), ("yellow", "#d62728"), ("orange", "#ff7f0e"), ("red", "#2ca02c")]
    for th, lab in THRESH_LINES:
        th_c = {"蓝色": "#1f77b4", "黄色": "#d62728", "橙色": "#ff7f0e", "红色": "#d62728"}.get(lab, "#333")
        ax.axhline(th, ls="--", lw=0.7, color=th_c, alpha=0.7)

    # 标题: 站名(时间范围) —— 与项目组一致
    s0 = sites[0] if sites else {}
    sname = s0.get("short") or s0.get("name", region)
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
            uvar = "u10" if "u10" in ds.variables else ("wind_x" if "wind_x" in ds.variables else None)
            vvar = "v10" if "v10" in ds.variables else ("wind_y" if "wind_y" in ds.variables else None)
            if not uvar or not vvar:
                continue
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
                continue
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

    fig, ax = plt.subplots(figsize=(7.4, 4.4), dpi=110)
    pc = ax.pcolormesh(LON, LAT, spd, cmap="YlOrRd", shading="auto")
    cb = fig.colorbar(pc, ax=ax, shrink=0.9)
    cb.set_label("风速 (m/s)", fontsize=8)
    step = max(1, LON.shape[0] // 16)
    ax.quiver(LON[::step, ::step], LAT[::step, ::step],
              uu[::step, ::step], vv[::step, ::step],
              color="k", width=0.0025, scale=350, alpha=0.85)
    title = f"{typh}台风 风场" if typh else "风场"
    if tlabel:
        title += f"（{tlabel}）"
    title += f" 最大风速 {best['max_spd']:.1f} m/s"
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("经度", fontsize=9)
    ax.set_ylabel("纬度", fontsize=9)
    ax.tick_params(labelsize=8)
    _mark_point(ax, ctx)
    fig.tight_layout(pad=1.0)
    fp = OUT_DIR / f"wind_field_{tag}.png"
    fig.savefig(fp, bbox_inches="tight")
    plt.close(fig)
    return [str(fp)]
