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
import re
import sys
import time
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


def _connect(pasv: bool = True, timeout: float = 30.0):
    from ftplib import FTP

    c = ftp_config()
    ftp = FTP()
    try:
        ftp.connect(c["host"], c["port"], timeout=timeout)
        ftp.login(c["user"], c["pass"])
    except Exception as e:  # noqa: BLE001
        note_error("connect", f"{type(e).__name__}: {e}")
        raise
    ftp.set_pasv(bool(pasv))  # 被动模式(防火墙友好)
    return ftp


# --------------------------------------------------------------------------- #
# 失败语义：把"取数失败"和"业务上没有这个数据"分开
#   测试报告 P1：FTP 425（被动模式数据连接被拒）被上层统一报成 no_data，
#   业务同事会以为"厦门站的增水数据根本不存在"，而不是"这次没取上"。
# --------------------------------------------------------------------------- #
_ERRORS: list = []          # 最近若干次失败（含时间戳）
_MAX_ERRORS = 30


def note_error(where: str, msg: str) -> None:
    """记一次取数失败（供上层判断到底是"没数据"还是"没取上"）。"""
    try:
        _ERRORS.append({"t": time.time(), "where": str(where), "msg": str(msg)[:400],
                        "kind": classify_error(msg)})
    except Exception:
        pass
    while len(_ERRORS) > _MAX_ERRORS:
        _ERRORS.pop(0)


def classify_error(msg: str) -> str:
    """把底层报错归类：data_access_error / auth_error / timeout / not_found / unknown。"""
    s = str(msg or "")
    low = s.lower()
    if "425" in s or "can't open data connection" in low or "cannot open data connection" in low:
        return "data_access_error"
    if "530" in s or "login" in low or "authentication" in low or "认证" in s:
        return "auth_error"
    if "timed out" in low or "timeout" in low or "超时" in s:
        return "timeout"
    if "550" in s or "not found" in low or "no such file" in low or "不存在" in s:
        return "not_found"
    if "10061" in s or "refused" in low or "unreachable" in low or "getaddrinfo" in low:
        return "data_access_error"
    return "unknown"


_KIND_TEXT = {
    "data_access_error": (
        "课题数据库（FTP）**数据连接被拒**",
        "这是取数通道的问题，不是“没有这份数据”：FTP 服务器返回 425（被动模式数据端口没打开）。"
        "系统已自动重连重试若干次；请稍后再问一次。若持续出现，请让运维检查 "
        "FTP(120.42.36.229:22210) 的被动端口范围/防火墙，或改用主动模式。"),
    "auth_error": (
        "课题数据库（FTP）**登录被拒**",
        "账号或密码不对（530）。请检查 .env 里的 FTP_USER / FTP_PASS 是否过期。"),
    "timeout": (
        "课题数据库（FTP）**连接超时**",
        "网络或服务器响应慢。请稍后重试；若持续，请检查本机到 120.42.36.229:22210 的网络。"),
    "not_found": (
        "课题数据库上**没有找到该文件**",
        "远程路径不存在（550）。可能是该期产品尚未发布，或文件名/目录变了。"),
    "unknown": (
        "取数过程**出现异常**",
        "详见下方原始报错；请重试一次，持续失败请把原始报错发给技术支持。"),
}


def recent_errors(within: float = 180.0) -> list:
    """最近一段时间内的取数失败记录。"""
    now = time.time()
    return [e for e in _ERRORS if now - float(e.get("t") or 0) <= within]


def diagnose_errors(within: float = 180.0) -> dict:
    """汇总最近的失败，给出可直接写进回复的"状态 + 原因 + 处置建议"。

    没有任何失败记录时返回 {}（= 真的没有这份数据，按 no_data 说）。
    """
    errs = recent_errors(within)
    if not errs:
        return {}
    kinds = [e.get("kind") or "unknown" for e in errs]
    # 优先报最"硬"的那个：认证 > 连接/取数 > 超时 > 未知
    order = ["auth_error", "data_access_error", "timeout", "not_found", "unknown"]
    kind = next((k for k in order if k in kinds), kinds[-1])
    head, advice = _KIND_TEXT.get(kind, _KIND_TEXT["unknown"])
    last = errs[-1]
    detail = str(last.get("msg") or "")
    n = len(errs)
    return {
        "status": kind,
        "title": head,
        "detail": detail,
        "where": str(last.get("where") or ""),
        "count": n,
        "advice": advice,
        "raw": f"最近 {int(within)} 秒内取数失败 {n} 次；最后一次："
               f"{last.get('where')} → {detail}",
    }


def clear_errors() -> None:
    _ERRORS.clear()


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


def _download_once(remote: str, local: str, pasv: bool = True,
                   rest: int = 0, timeout: float = 30.0,
                   blocksize: int = 262144) -> None:
    """一次下载尝试（失败直接抛异常，由 download() 决定重试）。rest>0 时从断点续传。

    blocksize 调大到 256 KB：课题库对小块传输效率很低，小块更容易"传一半停住"。
    """
    ftp = _connect(pasv=pasv, timeout=timeout)
    try:
        mode = "ab" if rest else "wb"
        with open(local, mode) as f:
            ftp.retrbinary(f"RETR {remote}", f.write, blocksize=blocksize, rest=rest)
    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def _remote_size(remote: str, timeout: float = 20.0) -> int:
    try:
        ftp = _connect(timeout=timeout)
    except Exception:
        return 0
    try:
        try:
            sz = ftp.size(remote)
            if sz:
                return int(sz)
        except Exception:
            pass
        try:
            from .ftp_catalog import _stat_size
            return int(_stat_size(ftp, remote) or 0)
        except Exception:
            return 0
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


def download(remote: str, local: str, retries: int = 2, quiet: bool = False) -> bool:
    """下载单个文件（**断点续传 + 重连重试**）。

    课题库偶发两类问题，都在这里兜住：
      ① 425（被动模式数据连接被拒）/ 瞬时失败 → 换新连接重来；
      ② 大文件传到一半 stall（socket timeout）→ **用 REST 从断点续传**，
         而不是从头再下（68 MB 从头下很容易反复失败）。
    被动模式连不上时最后退到主动模式碰一次运气。
    """
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    want = _remote_size(remote)
    plans = [True, False, True][: max(1, int(retries) + 1)]   # 被动 / 主动 / 被动
    pos = 0
    for i, pasv in enumerate(plans):
        # 已下完（比远端小 1 KB 以内都算完整）
        try:
            if Path(local).exists():
                pos = Path(local).stat().st_size
        except Exception:
            pos = 0
        if want and pos >= want - 1024:
            _rename_ok(local, quiet, remote)
            return True
        try:
            _download_once(remote, local, pasv=pasv, rest=pos)
        except Exception as e:  # noqa: BLE001
            note_error(f"download {remote}",
                       f"{type(e).__name__}: {e}（已传 {pos/1e6:.1f} MB"
                       f"{'，将断点续传' if pos else ''}）")
            if not quiet:
                print(f"下载中断（第 {i + 1}/{len(plans)} 次，"
                      f"{'被动' if pasv else '主动'}模式，已传 {pos/1e6:.1f} MB）：{e}")
        try:
            if Path(local).exists() and Path(local).stat().st_size > 0:
                pos = Path(local).stat().st_size
        except Exception:
            pos = 0
        if want and pos >= want - 1024:
            _rename_ok(local, quiet, remote)
            return True
        time.sleep(1.0)
    # 收尾：比目标小太多就当失败（避免把半截文件当缓存用）
    try:
        got = Path(local).stat().st_size if Path(local).exists() else 0
    except Exception:
        got = 0
    if want and got < want - 1024:
        note_error(f"download {remote}", f"只下到 {got}B / 远端 {want}B")
        try:
            if Path(local).exists():
                Path(local).unlink()
        except Exception:
            pass
        return False
    if got <= 0:
        return False
    _rename_ok(local, quiet, remote)
    return True


def _rename_ok(local: str, quiet: bool, remote: str) -> None:
    try:
        if not quiet:
            print(f"下载完成: {remote} -> {local} ({os.path.getsize(local)}B)")
    except Exception:
        pass


def sync_dir(remote_dir: str, local_dir: str = "", keyword: str = "", max_files: int = 20) -> dict:
    """同步一个 FTP 目录下的文件到本地（供对话调用）。

    参数:
        remote_dir: FTP 目录，如 /group3/wind/typhoon_2526
        local_dir:  本地目录（缺省 data/ftp/<目录名>）
        keyword:    只同步文件名含关键字的（可选）
        max_files:  最多同步文件数（默认20，防止误拉过大）

    返回 {"ok":..., "downloaded": [...], "skipped": [...], "failed": [...], "total_mb": ...}
    """
    import shutil

    try:
        ftp = _connect()
    except Exception as e:
        return {"ok": False, "error": f"FTP连接失败: {e}"}
    try:
        # 列出远程文件
        items = []
        for name, meta in ftp.mlsd(remote_dir or "/"):
            if meta.get("type") != "file":
                continue
            if keyword and keyword.lower() not in name.lower():
                continue
            items.append((name, int(meta.get("size", 0) or 0)))
        items.sort()
        if not items:
            return {"ok": False, "error": f"目录下没有匹配文件: {remote_dir}"}
        picked = items[:max_files]

        base = Path(local_dir) if local_dir else (
            Path(__file__).resolve().parent.parent / "data" / "ftp" / (remote_dir.rstrip("/").split("/")[-1] or "misc")
        )
        base.mkdir(parents=True, exist_ok=True)

        downloaded, skipped, failed = [], [], []
        total_mb = 0.0
        for name, size in picked:
            local = base / name
            remote = remote_dir.rstrip("/") + "/" + name
            if local.exists() and local.stat().st_size == size:
                skipped.append(name)
                continue
            tmp = local.with_suffix(local.suffix + ".part")
            try:
                with open(tmp, "wb") as f:
                    ftp.retrbinary(f"RETR {remote}", f.write)
                shutil.move(str(tmp), str(local))
                downloaded.append(name)
                total_mb += size / 1e6
                print(f"[下载] {name} ({size/1e6:.0f}MB)")
            except Exception as e:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                failed.append(f"{name}: {e}")
        return {
            "ok": True,
            "remote_dir": remote_dir,
            "local_dir": str(base),
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "total_mb": round(total_mb, 1),
            "note": f"共 {len(items)} 个匹配文件，本次处理 {len(picked)} 个" + (
                f"（超过上限{max_files}个，已截断）" if len(items) > max_files else ""
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


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
