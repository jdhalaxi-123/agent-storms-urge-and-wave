# -*- coding: utf-8 -*-
"""FTP 数据源工具：列目录 / 下载 / 同步。

用法：
    python -m orchestrator.ftp_client list                # 列出根目录
    python -m orchestrator.ftp_client list /group3        # 列某目录
    python -m orchestrator.ftp_client tree                 # 递归列目录(最多3层)

凭证从 .env 读取：FTP_HOST / FTP_PORT / FTP_USER / FTP_PASS
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 项目根 /.env 加载
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> dict:
    cfg = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def ftp_config() -> dict:
    cfg = _load_env()
    return {
        "host": os.environ.get("FTP_HOST") or cfg.get("FTP_HOST", ""),
        "port": int(os.environ.get("FTP_PORT") or cfg.get("FTP_PORT", "21")),
        "user": os.environ.get("FTP_USER") or cfg.get("FTP_USER", ""),
        "pass": os.environ.get("FTP_PASS") or cfg.get("FTP_PASS", ""),
    }


def _connect():
    from ftplib import FTP

    c = ftp_config()
    ftp = FTP()
    ftp.connect(c["host"], c["port"], timeout=30)
    ftp.login(c["user"], c["pass"])
    ftp.set_pasv(True)  # 被动模式(防火墙友好)
    return ftp


def list_dir(path: str = "/") -> None:
    ftp = _connect()
    try:
        print(f"=== {cwd(ftp)} ===")
        for name, meta in ftp.mlsd(path or "/"):
            kind = "DIR " if meta.get("type") == "dir" else "FILE"
            size = meta.get("size", "")
            print(f"  [{kind}] {name}", f"({size}B)" if size else "")
    except Exception as e:
        print("列目录失败:", e)
    finally:
        ftp.quit()


def cwd(ftp) -> str:
    try:
        return ftp.pwd()
    except Exception:
        return "/"


# --------------------------------------------------------------------------- #
# 对话式查询接口（供 LLM 工具调用）
# --------------------------------------------------------------------------- #
def query(path: str = "/", keyword: str = "", max_items: int = 60) -> dict:
    """查询 FTP 目录，返回结构化结果（供 LLM 整理成自然语言回答）。

    参数:
        path:     要查询的目录，如 "/group3/wind"
        keyword:  可选，按关键字过滤文件名/目录名（如 "2526"、"wave"）
        max_items: 最多返回条目数（防止输出过长）

    返回:
        {"ok": True, "path": ..., "total": n, "dirs": [...], "files": [...],
         "note": ...}
        或 {"ok": False, "error": "..."}
    """
    try:
        ftp = _connect()
    except Exception as e:
        return {"ok": False, "error": f"FTP 连接失败: {e}"}
    try:
        dirs, files = [], []
        for name, meta in ftp.mlsd(path or "/"):
            if name in (".", ".."):
                continue
            if keyword and keyword.lower() not in name.lower():
                continue
            if meta.get("type") == "dir":
                dirs.append(name)
            else:
                try:
                    size_mb = round(int(meta.get("size", 0)) / 1e6, 1)
                except Exception:
                    size_mb = None
                files.append({"name": name, "size_mb": size_mb})
        dirs.sort()
        files.sort(key=lambda x: x["name"])
        total = len(dirs) + len(files)
        note = ""
        if total > max_items:
            note = f"（共 {total} 项，仅显示前 {max_items} 项）"
            dirs = dirs[: max_items // 2]
            files = files[: max_items // 2]
        return {
            "ok": True,
            "path": path,
            "keyword": keyword or None,
            "total": total,
            "dirs": dirs,
            "files": files,
            "note": note,
        }
    except Exception as e:
        return {"ok": False, "error": f"列目录失败（路径可能不存在）: {e}"}
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def search(root: str, keyword: str, max_depth: int = 3, max_hits: int = 40) -> dict:
    """在 FTP 上递归搜索（按关键字匹配 目录名/文件名）。

    返回 {"ok": True, "hits": [{"path":..., "type": "dir"/"file", "size_mb":...}]}
    """
    if not keyword:
        return {"ok": False, "error": "请提供关键字"}
    try:
        ftp = _connect()
    except Exception as e:
        return {"ok": False, "error": f"FTP 连接失败: {e}"}
    hits = []
    try:
        def walk(p, d):
            if d > max_depth or len(hits) >= max_hits:
                return
            try:
                entries = list(ftp.mlsd(p or "/"))
            except Exception:
                return
            for name, meta in entries:
                if name in (".", ".."):
                    continue
                full = p.rstrip("/") + "/" + name
                if keyword.lower() in name.lower():
                    hits.append({
                        "path": full,
                        "type": "dir" if meta.get("type") == "dir" else "file",
                        "size_mb": round(int(meta.get("size", 0)) / 1e6, 1) if meta.get("type") != "dir" else None,
                    })
                if meta.get("type") == "dir":
                    walk(full, d + 1)
        walk(root, 0)
        return {"ok": True, "root": root, "keyword": keyword, "hits": hits[:max_hits], "count": len(hits)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def tree(path: str = "/", depth: int = 0, max_depth: int = 3) -> None:
    if depth > max_depth:
        return
    ftp = _connect()
    def _walk(p, d):
        try:
            items = []
            for name, meta in ftp.mlsd(p or "/"):
                items.append((name, meta.get("type"), meta.get("size", "")))
            items.sort(key=lambda x: (x[1] != "dir", x[0]))
            for name, kind, size in items:
                indent = "  " * d
                if kind == "dir":
                    print(f"{indent}[DIR] {name}/")
                    _walk(p.rstrip('/') + '/' + name, d + 1)
                else:
                    print(f"{indent}{name} ({size}B)")
        except Exception as e:
            print(f"{'  ' * d}<无法列出 {p}: {e}>")
    try:
        _walk(path, 0)
    finally:
        ftp.quit()


def download(remote: str, local: str) -> bool:
    """下载单个文件。"""
    ftp = _connect()
    try:
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        with open(local, "wb") as f:
            ftp.retrbinary(f"RETR {remote}", f.write)
        print(f"下载完成: {remote} -> {local} ({os.path.getsize(local)}B)")
        return True
    except Exception as e:
        print(f"下载失败 {remote}:", e)
        return False
    finally:
        ftp.quit()


def sync_typhoon(typhoon: str, with_wind: bool = True, force: bool = False) -> list:
    """按台风同步：从 FTP 拉取该台风的风暴潮场 + ERA5 风场到本地 data/ftp/。

    - 风暴潮: /group1/storm_surge/{typhoon}.nc
    - ERA5:   /group1/storm_surge/era5/{typhoon}.nc
    已存在且大小一致(非force)则跳过（断点续传/避免重复下载）。

    返回下载的文件列表。
    """
    import shutil

    ftp = _connect()
    base = Path(__file__).resolve().parent.parent / "data" / "ftp"
    downloaded = []
    try:
        # 远程文件清单
        candidates = [
            (f"/group1/storm_surge/{typhoon}.nc", base / typhoon / f"{typhoon}_surge.nc", "风暴潮场"),
            (f"/group1/storm_surge/era5/{typhoon}.nc", base / typhoon / f"{typhoon}_era5.nc", "ERA5风场"),
        ]
        for remote, local, label in candidates:
            if not with_wind and "era5" in remote:
                continue
            # 跳过策略：本地存在且非 force
            if local.exists() and not force:
                print(f"[跳过] {label} 已存在: {local}")
                downloaded.append(str(local))
                continue
            # 下载（先拉倒临时文件防损坏）
            tmp = local.with_suffix(local.suffix + ".part")
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(tmp, "wb") as f:
                    ftp.retrbinary(f"RETR {remote}", f.write)
                shutil.move(str(tmp), str(local))
                print(f"[下载] {label}: {remote} -> {local} ({local.stat().st_size/1e6:.0f}MB)")
                downloaded.append(str(local))
            except Exception as e:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                print(f"[失败] {label}: {remote} -> {e}")
    finally:
        ftp.quit()
    return downloaded


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "list"
    if cmd == "list":
        target = args[1] if len(args) > 1 else "/"
        list_dir(target)
    elif cmd == "tree":
        target = args[1] if len(args) > 1 else "/"
        print(f"FTP 目录树: {target}")
        tree(target)
    elif cmd == "download":
        if len(args) >= 3:
            download(args[1], args[2])
        else:
            print("用法: ... download <远程路径> <本地路径>")
    elif cmd == "sync":
        typhoon = args[1] if len(args) > 1 else "2403"
        force = "--force" in args
        files = sync_typhoon(typhoon, with_wind=True, force=force)
        print(f"\n同步 {typhoon} 完成，涉及 {len(files)} 个文件")
    else:
        print("用法: list [dir] | tree [dir] | download <remote> <local> | sync <台风号> [--force]")


if __name__ == "__main__":
    main()
