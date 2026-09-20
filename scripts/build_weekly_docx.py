# -*- coding: utf-8 -*-
"""按「历次周报」的固定版式生成 Word 周报。

与通用公文转换器（scripts/md_to_docx.py）的区别：
    通用转换器是"公文版式"（15pt、大边距），而历次周报用的是：
        · 标题：Heading 1 样式（22pt 加粗）居中
        · 正文：宋体 12pt、行距 1.5、首行缩进 24pt（2 字符）
        · "一、 本周工作总结" 与 "周一：…" 都是**普通正文**，不加粗
        · A4 纸，页边距 上下 2.5cm、左右 3.2cm
        · 全文无表格

用法：
    python scripts/build_weekly_docx.py <源.md> [-o 输出.docx]
源文件约定：
    # 每周工作报告（09.14-09.18）      → 标题
    ## 一、 本周工作总结                → 正文段落（标题级别不体现为样式）
    周一：<主题> <正文>                 → 正文段落
    1. <不足>：<说明>                   → 正文段落
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

SONG = "宋体"


def body_paragraph(doc: Document, text: str):
    """正文段落：宋体 12pt、1.5 倍行距、首行缩进 24pt。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.first_line_indent = Pt(24)
    pf.line_spacing = 1.5
    r = p.add_run(text)
    r.font.name = SONG
    r.font.size = Pt(12)
    r._element.rPr.rFonts.set(qn("w:eastAsia"), SONG)
    return p


def clean(line: str) -> str:
    """去掉 Markdown 强调标记（周报正文是纯文本，不加粗）。"""
    s = line.strip()
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)      # **粗体** → 纯文本
    s = re.sub(r"`(.+?)`", r"\1", s)            # `代码`  → 纯文本
    return s


def build(src: Path, out: Path) -> Path:
    lines = src.read_text(encoding="utf-8").splitlines()
    doc = Document()

    # 页面：A4 + 历次周报的页边距
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.top_margin = s.bottom_margin = Cm(2.5)
        s.left_margin = s.right_margin = Cm(3.2)

    # 默认样式：宋体 10.5pt（与参考文件一致）
    st = doc.styles["Normal"]
    st.font.name = SONG
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), SONG)

    title_done = False
    for raw in lines:
        s = raw.strip()
        if not s or s in ("---", "***"):
            continue
        if s.startswith("# ") and not title_done:
            p = doc.add_paragraph(clean(s[2:]), style="Heading 1")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            title_done = True
            continue
        if s.startswith("## "):
            body_paragraph(doc, clean(s[3:]))       # 小标题也是正文
            continue
        body_paragraph(doc, clean(s))

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成固定版式的周报 Word")
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args()
    src = Path(args.src)
    out = Path(args.out) if args.out else src.with_suffix(".docx")
    p = build(src, out)
    print(f"已生成：{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
