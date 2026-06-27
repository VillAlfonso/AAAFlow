"""Sentence-aware text chunking for long scripts.

Qwen3-TTS generates one clip per call, bounded by max_new_tokens. For long
YouTube scripts we split the text into sentence-sized chunks (never cutting a
sentence mid-way) so each clip is short, reliable, and well-paced. Paragraph
boundaries are tracked so the audio stage can insert longer pauses there.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Sentence terminators for Latin + CJK, keeping trailing quotes/brackets.
_SENT_END = re.compile(r'([\.!\?。！？…]+["\'”’\)\]]*)(\s+|$)')
# Clause separators used only when a single sentence is too long.
_CLAUSE = re.compile(r'([,;:、，；：]|\s[—-]\s)')


def split_paragraphs(text: str) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_sentences(paragraph: str) -> List[str]:
    p = re.sub(r"\s+", " ", paragraph).strip()
    if not p:
        return []
    sentences: List[str] = []
    last = 0
    for m in _SENT_END.finditer(p):
        end = m.end()
        seg = p[last:end].strip()
        if seg:
            sentences.append(seg)
        last = end
    if last < len(p):
        tail = p[last:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def _hard_wrap(sentence: str, max_chars: int) -> List[str]:
    """Break an over-long sentence on clause punctuation, then on whitespace."""
    tokens = _CLAUSE.split(sentence)
    pieces: List[str] = []
    buf = ""
    for tok in tokens:
        if buf and len(buf) + len(tok) > max_chars:
            pieces.append(buf.strip())
            buf = tok
        else:
            buf += tok
    if buf.strip():
        pieces.append(buf.strip())

    out: List[str] = []
    for piece in pieces:
        if len(piece) <= max_chars or " " not in piece:
            out.append(piece)
            continue
        cur = ""
        for word in piece.split(" "):
            if cur and len(cur) + 1 + len(word) > max_chars:
                out.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        if cur:
            out.append(cur)
    return [p for p in out if p]


def chunk_text(text: str, max_chars: int = 240) -> List[Dict]:
    """Split text into [{text, paragraph}] chunks, packing whole sentences."""
    chunks: List[Dict] = []
    for pi, para in enumerate(split_paragraphs(text)):
        buf = ""
        for sent in split_sentences(para):
            if len(sent) > max_chars:
                if buf:
                    chunks.append({"text": buf.strip(), "paragraph": pi})
                    buf = ""
                for piece in _hard_wrap(sent, max_chars):
                    chunks.append({"text": piece, "paragraph": pi})
                continue
            if buf and len(buf) + 1 + len(sent) > max_chars:
                chunks.append({"text": buf.strip(), "paragraph": pi})
                buf = sent
            else:
                buf = f"{buf} {sent}".strip()
        if buf.strip():
            chunks.append({"text": buf.strip(), "paragraph": pi})
    return [c for c in chunks if c["text"]]


def count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))
