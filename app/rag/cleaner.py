"""06 RAG：数据清洗（蓝图 06 新增，zhao 无对应）。

loader 输出（txt 直读 / Docling / Jina 都可能带噪音）到分块之间必须清洗，
否则噪音进 embedding 拉低检索精度。
"""

import re


def clean(markdown: str) -> str:
    """去 BOM 与非法字符 → 统一换行 → 去纯链接/导航/版权行 → 折叠连续空行 → 压缩段内连续空白。"""
    text = markdown.replace("﻿", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if re.fullmatch(r"\[.*\]\(https?://[^)]+\)", s):  # [text](url) 链接
            continue
        if re.fullmatch(r"https?://\S+", s):  # 裸 URL
            continue
        if re.fullmatch(r"(©|Copyright).*", s, re.IGNORECASE):
            continue
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)  # 折叠连续空行
    text = re.sub(r"[ \t]{2,}", " ", text)  # 压缩段内连续空白
    return text.strip()


def dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """分块后内容级去重：文本相同/互为子串的块合并，保留首个（避免 RRF 前重复命中）。"""
    seen: list[str] = []
    result: list[dict] = []
    for c in chunks:
        text = c["text"].strip()
        dup = any(text == s or (len(text) > 20 and (text in s or s in text)) for s in seen)
        if not dup:
            seen.append(text)
            result.append(c)
    return result
