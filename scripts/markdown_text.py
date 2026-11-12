"""Markdownの表示と出典を分ける。解析用の空白化は文字位置を保つ。"""
from __future__ import annotations

import re

INLINE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
LINK = re.compile(r"!?\[([^\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)")
REFERENCE = re.compile(r"(?m)^ {0,3}\[([^\]\n]+)\]:")
CITE_LABEL = re.compile(r"(?:S\d+|\d+(?:\s*[,、;–-]\s*\d+)*|\^[\w.-]+|出典\d*|参考\d*|文献\d*|source\d*|ref\d*)", re.I)
CITE = re.compile(r"(?<![\\!])\[(S\d+|\d+(?:\s*[,、;–-]\s*\d+)*|\^[\w.-]+)\](?!\()|【\d+】", re.I)
SUP = re.compile(r"<sup\b[^>]*>.*?</sup\s*>", re.I | re.S)
SENTENCE_STOP = re.compile(r'[。！？!?]+[」』）)\]”\"\u2019]*')


def blank(text: str) -> str:
    return re.sub(r"[^\r\n]", " ", text)


def labels(text: str) -> set[str]:
    return {m[1].casefold() for m in REFERENCE.finditer(text)}


def _citation_position(text: str, start: int, end: int) -> bool:
    """Numeric brackets are citations at sentence edges, not array indices."""
    left, right = text[:start].rstrip(), text[end:].lstrip()
    if start and re.search(r'[A-Za-z0-9_]$', text[:start]):
        return False
    return (not left or left[-1:] in '。！？!?」』）)' or
            not right or right[:1] in '。！？!?」』）)' or bool(CITE.match(right)))


def project(text: str, *, mask_code: bool = True, reference_labels: set[str] | None = None) -> str:
    """Project prose to the same offsets; keep ordinary link labels and code if requested."""
    out = re.sub(r"<!--.*?-->", lambda m: blank(m[0]), text, flags=re.S)
    codes = list(INLINE.finditer(out))
    out = INLINE.sub(lambda m: blank(m[0]), out)

    def sup(m):
        body = re.sub(r"<[^>]+>", "", m[0])
        is_note = bool(re.search(r'(?:href|id)=[\"\'][^\"\']*(?:fn|footnote|cite|ref)', m[0], re.I)) or out[:m.start()].rstrip().endswith(('。','！','？','!','?'))
        return blank(m[0]) if is_note and re.fullmatch(r"\s*(?:\d+|\[?\^?[\w.-]+\]?)\s*", body) else m[0]
    out = SUP.sub(sup, out)

    def link(m):
        # Citation links count as source markup only at a sentence edge.
        if CITE_LABEL.fullmatch(m[1]) and _citation_position(out, m.start(), m.end()):
            return blank(m[0])
        a, b = m.start(1) - m.start(), m.end(1) - m.start()
        return blank(m[0][:a]) + m[1] + blank(m[0][b:])
    out = LINK.sub(link, out)
    known = reference_labels or set()
    def ref_link(m):
        label, key = m[1], m[2] or m[1]
        if key.casefold() not in known:
            return m[0]
        if CITE_LABEL.fullmatch(label) and _citation_position(out, m.start(), m.end()):
            return blank(m[0])
        return ' ' + label + blank(m[0][len(label) + 1:])
    out = re.sub(r"(?<![\\!])\[([^\]\n]+)\]\[([^\]\n]*)\]", ref_link, out)
    # Only recognized citations are hidden, not arbitrary bracketed words.
    out = CITE.sub(lambda m: blank(m[0]) if (m[0].startswith(('[S', '[s', '[^', '【')) or
                   _citation_position(out, m.start(), m.end())) else m[0], out)
    out = re.sub(r"https?://[^\s<>]+", lambda m: blank(m[0]), out)
    out = re.sub(r"<[^>\n]+>", lambda m: blank(m[0]), out)
    # Emphasis markup is not prose; backticks remain visible in the code-preserving view.
    out = re.sub(r"\*\*|__", lambda m: blank(m[0]), out)
    if not mask_code:
        chars = list(out)
        for m in codes:
            chars[m.start():m.end()] = m[0]
        out = ''.join(chars)
    return out


def sentence_ranges(raw: str, scan: str, visible: str) -> list[tuple[int, int]]:
    """Keep source references with the preceding sentence, including soft line breaks."""
    cuts = [m.end() for m in SENTENCE_STOP.finditer(scan)] + [len(scan)]
    result: list[tuple[int, int]] = []
    last = 0
    for cut in cuts:
        if cut <= last:
            continue
        while cut < len(scan) and visible[cut].isspace():
            cut += 1
        a, b = last, cut
        while a < b and raw[a].isspace():
            a += 1
        while b > a and raw[b - 1].isspace():
            b -= 1
        if a < b:
            # A suffix consisting only of citations or closing markup stays attached.
            if re.search(r"[\w一-龠ぁ-んァ-ヶ]", visible[a:b]):
                result.append((a, b))
            elif result:
                result[-1] = (result[-1][0], b)
        last = cut
    return result


def prose_text(text: str) -> str:
    """Compact display text for linguistic metrics, not a source-coordinate view."""
    return re.sub(r"[ \t]+", " ", text).strip()
