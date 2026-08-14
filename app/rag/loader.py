"""06 RAG：文档加载（蓝图 06 loader 段，复用 zhao/rag/loader.py）。

纯文本直读；pdf/docx/pptx/图片走 Docling（重依赖，懒 import，未装时 load_document 抛 ImportError，
上层捕获标 failed）；http 走 Jina Reader。统一输出 Markdown。
"""

from pathlib import Path

import requests

_PLAIN = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".log", ".xml", ".html"}


def load_txt(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_document(path: str) -> str:
    """pdf / docx / pptx / 图片 → Docling 解析 → Markdown。"""
    # ponytail: docling 是重依赖，函数内懒 import；未装时抛 ImportError，由索引侧标记 failed
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(path)
    return result.document.export_to_markdown()


def load_url(url: str) -> str:
    """网页 → Jina Reader → Markdown（https://r.jina.ai/{url}）。"""
    jina_url = f"https://r.jina.ai/{url}"
    resp = requests.get(
        jina_url,
        timeout=60,
        headers={"Accept": "text/markdown", "User-Agent": "Mozilla/5.0 (compatible; RagBot/1.0)"},
    )
    resp.raise_for_status()
    return resp.text


def load(path: str) -> str:
    """统一入口：http 开头走 Jina；纯文本直读；其余走 Docling。"""
    if path.startswith(("http://", "https://")):
        return load_url(path)
    ext = Path(path).suffix.lower()
    if ext in _PLAIN:
        return load_txt(path)
    return load_document(path)
