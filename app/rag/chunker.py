"""06 RAG：文本分块（蓝图 06 chunker 段，复用 zhao/rag/chunker.py）。

三法：chunk_by_token / chunk_by_semantic / chunk_parent_child。
相对 zhao 的改动（蓝图 06 明确）：
- group_id 改文档内自增（0 起），不再是全局 g1/g2
- _split_unit 补 seq_in_group（组内顺序号，0 起）
- 代码块/表格保护（_protect）照搬
"""

import re
import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")

_CODE_RE = re.compile(r"```[\s\S]*?```")
_TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
_FUNC_SPLIT = re.compile(r"\n(?=(?:def |class |async def |fn |function |func |pub fn ))")
_HEADING_RE = re.compile(r"\n(?=#{1,6} )")


def _protect(text: str) -> tuple[str, dict[str, str]]:
    """代码块→函数粒度切分；表格→连续行整体保留。"""
    ph: dict[str, str] = {}

    def _replace_code(match):
        parts = _FUNC_SPLIT.split(match.group(0))
        keys = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            key = f"[CODE_{len(ph)}]"
            ph[key] = p
            keys.append(key)
        return "\n\n".join(keys)

    text = _CODE_RE.sub(_replace_code, text)

    lines = text.split("\n")
    buf, i = [], 0
    while i < len(lines):
        if _TABLE_RE.match(lines[i]):
            rows = [lines[i]]
            i += 1
            while i < len(lines) and _TABLE_RE.match(lines[i]):
                rows.append(lines[i])
                i += 1
            key = f"[TABLE_{len(ph)}]"
            ph[key] = "\n".join(rows)
            buf.append(key)
        else:
            buf.append(lines[i])
            i += 1
    return "\n".join(buf), ph


def _restore(text: str, ph: dict[str, str]) -> str:
    for k, v in ph.items():
        text = text.replace(k, v)
    return text


def _tok(text: str) -> int:
    return len(_ENC.encode(text))


def _split_unit(text: str, size: int, gid: str) -> list[dict]:
    """一个自然单元切成 ≤ size token 的块：同组共享 gid，seq_in_group 组内递增。"""
    def _mk(seg: str, seq: int) -> dict:
        return {"text": seg, "tokens": _tok(seg), "group_id": gid, "seq_in_group": seq}

    if _tok(text) <= size:
        return [_mk(text, 0)]

    sentences = re.split(r"(?<=[。！？；])\s*", text)
    chunks, current = [], ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        candidate = s if not current else current + s
        if _tok(candidate) > size and current:
            chunks.append(current)
            current = s
        else:
            current = candidate
    if current:
        chunks.append(current)

    result, seq = [], 0
    for c in chunks:
        if _tok(c) <= size:
            result.append(_mk(c, seq))
            seq += 1
        else:
            tokens = _ENC.encode(c)
            for j in range(0, len(tokens), size):
                result.append(_mk(_ENC.decode(tokens[j:j + size]), seq))
                seq += 1
    return result


def _apply_overlap(chunks: list[dict], overlap: int) -> list[dict]:
    """chunk[i] 末尾 overlap token → chunk[i+1] 前缀。"""
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_text = result[i - 1]["text"]
        prev_tokens = _ENC.encode(prev_text)
        prefix = _ENC.decode(prev_tokens[-overlap:]) if len(prev_tokens) > overlap else prev_text
        new_text = prefix + "\n" + chunks[i]["text"]
        result.append({
            "text": new_text, "tokens": _tok(new_text),
            "group_id": chunks[i]["group_id"], "seq_in_group": chunks[i]["seq_in_group"],
        })
    return result


def chunk_by_token(text: str, size: int = 200, overlap: int = 30) -> list[dict]:
    """段落为自然单元 → token 窗口切分 → 同源共 group_id。"""
    text, ph = _protect(text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    merged, buf, buf_tok = [], [], 0
    for p in paragraphs:
        t = _tok(p)
        if buf_tok + t > size and buf:
            merged.append("\n\n".join(buf))
            buf, buf_tok = [p], t
        else:
            buf.append(p)
            buf_tok += t
    if buf:
        merged.append("\n\n".join(buf))

    result, gid = [], 0
    for unit in merged:
        result.extend(_split_unit(unit, size, str(gid)))
        gid += 1

    result = _apply_overlap(result, overlap)
    return [
        {"text": _restore(c["text"], ph), "tokens": c["tokens"],
         "group_id": c["group_id"], "seq_in_group": c["seq_in_group"]}
        for c in result
    ]


def chunk_by_semantic(text: str, size: int = 200) -> list[dict]:
    """标题→段落→句子逐级降级，每个章节的块共享 group_id。"""
    text, ph = _protect(text)
    sections = _HEADING_RE.split(text)
    sections = [s.strip() for s in sections if s.strip()] or [text.strip()]

    result, gid = [], 0
    for sec in sections:
        result.extend(_split_unit(sec, size, str(gid)))
        gid += 1
    return [
        {"text": _restore(c["text"], ph), "tokens": c["tokens"],
         "group_id": c["group_id"], "seq_in_group": c["seq_in_group"]}
        for c in result
    ]


def chunk_parent_child(text: str, child_size: int = 200,
                       parent_size: int = 800, overlap: int = 30) -> list[dict]:
    """child 小块做 embedding 检索，命中后返回 parent 大块给 LLM。

    返回 [{parent, parent_tokens, children:[{text, tokens, index}]}, ...]。
    完整存储链路（parent_id 列）待接入，本轮索引用 token/semantic 策略。
    """
    text, ph = _protect(text)
    sections = _HEADING_RE.split(text)
    sections = [s.strip() for s in sections if s.strip()] or [text.strip()]

    parents, buf, buf_tok = [], [], 0
    for sec in sections:
        t = _tok(sec)
        if buf_tok + t > parent_size and buf:
            parents.append("\n\n".join(buf))
            buf, buf_tok = [sec], t
        else:
            buf.append(sec)
            buf_tok += t
    if buf:
        parents.append("\n\n".join(buf))

    results, child_idx = [], 0
    for p_text in parents:
        p_text = _restore(p_text, ph)
        child_chunks = chunk_by_token(p_text, child_size, overlap)
        children = [
            {"text": c["text"], "tokens": c["tokens"], "index": child_idx + i}
            for i, c in enumerate(child_chunks)
        ]
        child_idx += len(children)
        results.append({"parent": p_text, "parent_tokens": _tok(p_text), "children": children})
    return results
