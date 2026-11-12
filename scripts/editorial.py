"""出典への帰属と、解釈を否定する結びを点検する。"""
from __future__ import annotations

import re

# The action concerns non-participation, not an unsuccessful experiment.
AUTHOR = re.compile(r'(?:筆者|(?<![の原文])著者(?!ら)|執筆者|私(?:たち|達)?|当方|こちら)(?:自身|自ら)?')
ACTION = re.compile(r'再実行|再検証|追試|実行|検証|実測|測定|実験|確認|再現')
NONPARTICIPATION = re.compile(
    r'(?:結果|報告|検証)(?:ではない|ではありません|でない|ではなく)'
    r'|(?:実行|実施|検証|測定|確認|追試|実験)(?:は|を)?(?:していない|していません|しておらず|せず|しなかった|しませんでした)'
    r'|行って(?:いない|いません|おらず)|行わ(?:ない|なかった)|(?:未実施|未検証|未実行)')
NEGATIVE_CLOSURE = re.compile(
    r'(?:根拠|証拠|証明|保証|確認|代替|結論|判断材料)(?:に|と|を)?は?(?:ならない|なりません|できない|できません)'
    r'|(?:示す|意味する)(?:もの|情報|値)(?:ではない|ではありません)'
    r'|(?:証明|保証|確認|断定)(?:するもの|する情報|できるもの)?(?:ではない|にはならない)'
    r'|(?:成功|安全|無害|完了|解消|解決).{0,15}(?:を意味しない|を意味しません)')
NEGATIVE_END = re.compile(r'(?:ない|ません|未確認|未実施|未検証|未達成|未完了|未解決|不明)[。！？!?]*$')


def author_disclaimer(text: str) -> bool:
    """Identify an author's non-participation aside; leave experimental failures alone."""
    for who in AUTHOR.finditer(text):
        tail = text[who.end():]
        action = ACTION.search(tail)
        if action and NONPARTICIPATION.search(tail[action.start():]):
            return True
    return False


def closure_profile(text: str, source: str = '<input>') -> dict:
    # Deferred import avoids an editorial/structure import cycle.
    from structure import parse_markdown, compact
    doc = parse_markdown(text, source)
    sentences = [s for b in doc.paragraphs for s in b.sentences]
    def spans(rx):
        return [doc.location(s.start, s.end) for s in sentences if rx.search(compact(s.scan))]
    return {
        'method': 'prose-2 / editorial-1',
        'sentences': len(sentences),
        'negative_endings': len([s for s in sentences if NEGATIVE_END.search(compact(s.scan))]),
        'niwa_naranai': len([m for s in sentences for m in re.finditer('にはならない', s.scan)]),
        'negative_closures': spans(NEGATIVE_CLOSURE),
        'author_disclaimers': [doc.location(s.start, s.end) for s in sentences if author_disclaimer(s.scan)],
    }
