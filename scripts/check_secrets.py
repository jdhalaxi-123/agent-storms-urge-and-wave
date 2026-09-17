# -*- coding: utf-8 -*-
"""密钥泄露体检：检查仓库当前文件 + 全部提交历史里是否出现过真实密钥。

只打印"命中位置"和脱敏后的片段，绝不输出完整密钥。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(args, cwd=ROOT, timeout=300):
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def load_secrets() -> dict:
    """从 .env 读出真实密钥（只用于比对，不打印）。"""
    out = {}
    env = ROOT / ".env"
    if not env.exists():
        return out
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v and len(v) >= 6:
            out[k.strip()] = v
    return out


def mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}…{s[-2:]}（{len(s)} 位）"


def main():
    secrets = load_secrets()
    watch = {k: v for k, v in secrets.items()
             if re.search(r"KEY|PASS|SECRET|TOKEN", k, re.I)}
    print("=" * 74)
    print("密钥泄露体检")
    print("=" * 74)
    print(f".env 里待比对的项目：{[(k, mask(v)) for k, v in watch.items()]}")

    cnt = sh(["git", "rev-list", "--all", "--count"])[1].strip()
    print(f"仓库提交总数（全部分支）：{cnt}")

    print("\n① 当前工作区**被 git 跟踪**的文件里是否有真实密钥")
    hit = False
    for k, v in watch.items():
        rc, out, _ = sh(["git", "grep", "-n", "-I", "-F", v, "HEAD"])
        if rc == 0 and out.strip():
            hit = True
            print(f"  ❌ {k} 出现在：")
            for line in out.strip().splitlines()[:5]:
                print("     " + line.replace(v, mask(v)))
    if not hit:
        print("  ✅ 没有（跟踪的文件里不含任何真实密钥）")

    print("\n② 全部提交历史里是否出现过（逐密钥精确比对）")
    for k, v in watch.items():
        rc, out, _ = sh(["git", "log", "--all", "--oneline", "-S", v])
        if out.strip():
            print(f"  ❌ {k}：历史提交里出现过 ——")
            for line in out.strip().splitlines()[:5]:
                print("     " + line)
        else:
            print(f"  ✅ {k}：历史里从未出现")

    print("\n③ 通用密钥形态扫描（sk- 开头 16 位以上 / AKID 等）")
    rc, out, _ = sh(["git", "grep", "-I", "-n", "-E",
                     r"sk-[A-Za-z0-9]{16,}|AKID[A-Za-z0-9]{10,}"])
    if out.strip():
        for line in out.strip().splitlines()[:20]:
            safe = re.sub(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9]+", r"\1****", line)
            safe = re.sub(r"(AKID[A-Za-z0-9]{4})[A-Za-z0-9]+", r"\1****", safe)
            print("  ⚠️ " + safe)
    else:
        print("  ✅ 跟踪的文件里没有 sk-/AKID 形态的密钥")

    print("\n④ 未被跟踪的文件（未上传，但留意别误提交）")
    rc, out, _ = sh(["git", "status", "--porcelain", "--untracked-files=all"])
    untracked = [l[3:].strip() for l in out.splitlines() if l.startswith("??")]
    if untracked:
        for f in untracked[:20]:
            p = ROOT / f
            flag = ""
            if p.exists() and p.is_file():
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                    for k, v in watch.items():
                        if v in txt:
                            flag = f"  ⚠️ 含 {k}"
                            break
                except Exception:
                    pass
            print(f"  · {f}{flag}")
    else:
        print("  （没有未跟踪文件）")

    print("\n⑤ .gitignore 是否挡住了敏感文件")
    rc, out, _ = sh(["git", "check-ignore", "-v", ".env"])
    print("  " + (out.strip() if out.strip() else "⚠️ .env 没被忽略！"))

    print("\n" + "=" * 74)
    print("结论：若②③全部 ✅ 且 .env 被忽略，则 GitHub 上没有你的密钥。")
    print("=" * 74)


if __name__ == "__main__":
    sys.exit(main())
