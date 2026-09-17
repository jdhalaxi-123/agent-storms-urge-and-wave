# -*- coding: utf-8 -*-
"""手动配置 FTP 的辅助：把 FTP 四行准备好，然后让你在记事本里直接填。

做法（不交互、不猜）：
    1. 没有 .env 就从 .env.example 复制一份
    2. 确保 .env 里有 FTP_HOST / FTP_PORT / FTP_USER / FTP_PASS 四行
       （地址和端口直接写好，账号密码留空等你自己填）
    3. 打印四行内容 + 保存位置，提示用记事本打开编辑

只保证"行存在、地址端口有值"，**绝不覆盖你已填好的账号密码**。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

DEFAULTS = [
    ("FTP_HOST", "120.42.36.229"),
    ("FTP_PORT", "22210"),
    ("FTP_USER", ""),
    ("FTP_PASS", ""),
]


def main() -> int:
    if not ENV.exists():
        if EXAMPLE.exists():
            ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"已从 .env.example 生成 {ENV}")
        else:
            ENV.write_text("", encoding="utf-8")
            print(f"已新建 {ENV}")

    lines = ENV.read_text(encoding="utf-8", errors="ignore").splitlines()
    cur = {}
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            cur[k.strip()] = v.strip()

    changed = False
    for key, preset in DEFAULTS:
        have = cur.get(key, "")
        if not have:
            # 行不存在或为空 → 写入（账号密码留空，等用户填）
            new_lines, done = [], False
            for ln in lines:
                if ln.strip().startswith(f"{key}=") or ln.strip().startswith(f"# {key}="):
                    if not done:
                        new_lines.append(f"{key}={preset}")
                        done = True
                    continue
                new_lines.append(ln)
            if not done:
                new_lines.append(f"{key}={preset}")
            lines = new_lines
            changed = True

    if changed:
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 66)
    print("手动配置 FTP（照下面改 .env 文件）")
    print("=" * 66)
    print(f"\n配置文件：{ENV}\n")
    print("在里面找到/填写这四行（值照抄，密码按你手上的填）：")
    print("-" * 66)
    for key, preset in DEFAULTS:
        val = cur.get(key) or preset
        shown = val if val else "<在这里填>"
        print(f"{key}={shown}")
    print("-" * 66)
    print("\n注意：")
    print("  · 端口是 22210，不是默认的 21")
    print("  · 等号后面**不要加引号、不要在行尾留空格**")
    print("  · 密码以 ! 结尾时，直接复制粘贴，别在 cmd 里手打（会被吞掉）")
    print("  · 保存为 UTF-8（记事本默认即可），然后回到本窗口按回车验证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
