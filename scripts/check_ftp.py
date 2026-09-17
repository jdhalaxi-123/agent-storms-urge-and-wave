# -*- coding: utf-8 -*-
"""FTP 接入自检：一条命令看清"配置对不对、连不连得上、能不能取到数"。

用法：
    .venv\\Scripts\\python.exe scripts\\check_ftp.py
（新电脑部署后跑一次，就知道 FTP 那一环通不通）

检查内容：
    ① 读 .env：FTP_HOST / FTP_PORT / FTP_USER / FTP_PASS 是否齐全（密码只显示后 4 位）
    ② TCP 端口连通性
    ③ 登录（用户名/密码是否正确）
    ④ 列几个关键数据目录，看当期数据到哪天
    ⑤ 打印缓存目录位置与已缓存文件数
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK = "✅"
BAD = "❌"
WARN = "⚠️"


def read_env() -> dict:
    env_file = ROOT / ".env"
    cfg: dict = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    import os
    for k in ("FTP_HOST", "FTP_PORT", "FTP_USER", "FTP_PASS", "STORM_DATA_DIR"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def main() -> int:
    print("=" * 66)
    print("FTP 接入自检")
    print("=" * 66)
    cfg = read_env()
    host = cfg.get("FTP_HOST", "")
    port = cfg.get("FTP_PORT", "21")
    user = cfg.get("FTP_USER", "")
    pwd = cfg.get("FTP_PASS", "")

    print("\n① 配置")
    if not (host and user and pwd):
        print(f"  {BAD} .env 里缺少 FTP 配置（FTP_HOST / FTP_USER / FTP_PASS）")
        print("     解决：复制 .env.example 为 .env，照着填 4 行 FTP 配置")
        print(f"     当前：HOST={host or '(空)'}  PORT={port}  USER={user or '(空)'}  "
              f"PASS={'*' * len(pwd) if pwd else '(空)'}")
        return 1
    print(f"  {OK} FTP_HOST = {host}")
    print(f"  {OK} FTP_PORT = {port}   ← 注意：不是默认的 21")
    print(f"  {OK} FTP_USER = {user}")
    print(f"  {OK} FTP_PASS = {'*' * max(len(pwd) - 4, 0)}{pwd[-4:]}（共 {len(pwd)} 位）")

    print("\n② TCP 端口连通性")
    try:
        with socket.create_connection((host, int(port)), timeout=10):
            print(f"  {OK} {host}:{port} 可连通")
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 连不上 {host}:{port} — {type(e).__name__}: {e}")
        print("     排查：网络是否可用 / 是否被公司防火墙拦了 22210 端口 / 端口有没有填错")
        return 1

    print("\n③ 登录")
    try:
        from orchestrator import ftp_client
        ftp = ftp_client._connect()
        try:
            welcome = getattr(ftp, "welcome", "") or ""
            print(f"  {OK} 登录成功  {welcome.strip()[:80]}")
            print(f"  {OK} 当前目录：{ftp.pwd()}")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD} 登录失败 — {type(e).__name__}: {e}")
        print("     排查：账号/密码是否正确（注意大小写）、端口是否 22210")
        return 1

    print("\n④ 数据目录抽样（看当期数据到哪天）")
    try:
        from orchestrator import ftp_catalog as fc
        from orchestrator import ftp_client as _fc
        import re
        checks = [
            ("每日·风场", "/group3/wind", r"atm_forecast_(\d{8})\.nc"),
            ("每日·AI增水精细场", "/group3/dailyforecast/storm_surge_for_spatiotemporal_2/results_atm",
             r"surge_predicted_(\d{8})\.nc"),
            ("每日·AI海浪场", "/group3/dailyforecast/AutoWave/res_ATM",
             r"(\d{8})_wave_forecast_1h\.nc"),
            ("数值·海浪", "/group1/data", r"WaveFc(\d{10})"),
        ]
        ftp2 = _fc._connect()
        try:
            for label, path, pat in checks:
                try:
                    ent = fc._ls(ftp2, path)
                    dates = sorted({m.group(1) for e in ent if not e["dir"]
                                    for m in [re.search(pat, e["name"])] if m})
                    latest = dates[-1] if dates else "(未找到)"
                    print(f"  {OK} {label:<16} {path}")
                    print(f"       最新一期：{latest}（共 {len(dates)} 期）")
                except Exception as e:  # noqa: BLE001
                    print(f"  {WARN} {label:<16} {path} 列目录失败：{type(e).__name__}: {e}")
        finally:
            try:
                ftp2.quit()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        print(f"  {WARN} 抽样检查跳过：{e}")

    print("\n⑤ 本地缓存")
    try:
        from orchestrator import paths
        paths.ensure_tree()
        files = list(paths.CACHE_DIR.rglob("*"))
        files = [f for f in files if f.is_file()]
        size = sum(f.stat().st_size for f in files) / 1e6
        print(f"  {OK} 数据仓：{paths.DATA_ROOT}")
        print(f"  {OK} 已缓存 {len(files)} 个文件 / {size:.1f} MB")
        print(f"      （提问时会自动从 FTP 下载，落到这里；约 30 MB~260 MB/天）")
    except Exception as e:  # noqa: BLE001
        print(f"  {WARN} 数据仓检查失败：{e}")

    print("\n" + "=" * 66)
    print(f"{OK} FTP 接入正常，可以启动 agent 提问了")
    print("   下一步：2-启动.bat   →   浏览器打开 http://localhost:7860")
    print("   想每天自动下载新数据：4-设置自动下载.bat")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
