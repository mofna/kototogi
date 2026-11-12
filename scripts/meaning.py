"""原文と校正稿の差を示す。確かさや条件が動いた候補を抽出する。"""
from __future__ import annotations

from difflib import SequenceMatcher, unified_diff
import re

from markdown_text import project
from structure import parse_markdown
from editorial import author_disclaimer, closure_profile
from attribution import exposition_candidate

SIGNALS = {
    'knowledge_limit': r'断定.{0,12}(?:ない|ません)|断定する.{0,12}ではない|(?:把握|確認|検証)して(?:いない|いません|おりません)|(?:確認|判断|断定|保証)でき(?:ない|ません)|未確認|未検証|証拠.{0,10}(?:ない|把握していない)',
    'possibility': r'可能性|かもしれ(?:ない|ません)|(?:場合|こと)が(?:ある|あります)|見込[むまみ]|推測|と(?:みられ|考えられ)(?:る|ます)',
    'permission': r'して(?:も)?よい|含めてよい|許可|任意で',
    'obligation': r'必要(?:が(?:ある|あります)|だ|です|である)|しなければ|義務|必須',
    'recommendation': r'推奨|勧め|望ましい',
    'planned': r'予定|方針|検討中|目指す|計画',
    'incomplete': r'未実施|未達成|未完了|未解決|(?:実行|達成)して(?:いない|いません|おりません)|再検出でき(?:ず|ない|ません)',
    'partial_reduction': r'短縮|削減|削ぎ落と|減ら[すしせ]|低減|軽減|一部',
    'absolute': r'必ず|確実|保証(?:する|します)|すべて|全て|完全|なく(?:した|しました|す|します)|ゼロ',
    'scope': r'時点|だけ|のみ|に限[るらり]|(?:host|GPU|native)(?:試験|検証|で)|環境では|環境での',
    'attribution': r'によると|によれば|と報告|と説明|と記(?:した|して)|報告では',
}
NEGATION = re.compile(r'(?:ではない|ではありません|できない|できません|していない|していません|未確認|未実施|未達成|ない|ません)')
NUMBER = re.compile(r'(?<![A-Za-z0-9_])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)*(?:[eE][+-]?\d+)?(?:[:/~-]\d+(?:\.\d+)*)*(?:%|％|件|回|分|秒|ms|MiB|GB|台|年|月|日)?(?![A-Za-z0-9_])')
IDENTIFIER = re.compile(r'(?<![A-Za-z0-9_])(?:CVE-\d{4}-\d+|PR\d+|[0-9a-f]{8,64}|v\d+(?:\.\d+)+)(?![A-Za-z0-9_])')
URL = re.compile(r'https?://[^\s<>\[\]）]+')
CODE = re.compile(r'(`+)(?!`)(.+?)(?<!`)\1(?!`)', re.S)


def signature(text: str) -> set[str]:
    return {key for key, pattern in SIGNALS.items() if re.search(pattern, text)}


def _normal(text: str) -> str:
    return re.sub(r'[\s、，,。*_`]', '', text)


def _units(text: str, path: str):
    doc = parse_markdown(text, path)
    units = []
    for block in doc.blocks:
        if block.kind == 'prose':
            for sentence in block.sentences:
                units.append({'text': sentence.visible.strip(), 'span': doc.location(sentence.start, sentence.end),
                              'section': list(block.section), 'entry': block.entry})
        elif block.kind in ('heading', 'table', 'list', 'quote'):
            # These carry quantities, attribution and conditions too.
            visible = project(text[block.start:block.end], mask_code=False)
            units.append({'text': visible.strip(), 'span': doc.location(block.start, block.end),
                          'section': list(block.section), 'entry': block.entry})
    return units


def _inventory(text: str) -> dict[str, set[str]]:
    # Source markers and URLs are distinct from quantities in prose.
    visible = project(text, mask_code=False)
    fences = []
    active = None
    buf = []
    for line in text.splitlines():
        m = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if active:
            if re.fullmatch(r' {0,3}' + re.escape(active[0]) + '{' + str(active[1]) + r',}\s*', line):
                fences.append('\n'.join(buf)); active = None; buf = []
            else:
                buf.append(line)
        elif m:
            active = (m[1][0],len(m[1]))
    if active:
        fences.append('\n'.join(buf))
    return {'numbers': {m[0] for m in NUMBER.finditer(visible)},
            'identifiers': {m[0] for m in IDENTIFIER.finditer(visible)},
            'urls': {m[0].rstrip(').,;') for m in URL.finditer(text)},
            'inline_code': {m[2] for m in CODE.finditer(text) if '\n' not in m[2]},
            'code_blocks': set(fences)}


def compare(source: str, final: str, *, source_name: str, final_name: str,
            materials: list[tuple[str, str]] = ()) -> dict:
    old, new = _units(source, source_name), _units(final, final_name)
    material_units = [u for name, text in materials for u in _units(text, name)]
    findings: list[dict] = []

    def add(rule, before, after, question, data=None):
        findings.append({'id': f'M{len(findings)+1:03d}', 'level': 'REVIEW', 'rule': rule,
                         'before': before, 'after': after, 'question': question, 'data': data or {}})

    inventories = [_inventory(source), _inventory(final)]
    mi = [_inventory(text) for _, text in materials]
    for kind, old_values in inventories[0].items():
        new_values = inventories[1][kind]
        removed, added = sorted(old_values - new_values), sorted(new_values - old_values)
        if removed or added:
            add('protected_values', None, None, '数値・識別子・コード・参照先の変更を原文と資料で確認する。',
                {'kind': kind, 'removed': removed, 'added': added,
                 'added_present_in_material': [x for x in added if any(x in inv[kind] for inv in mi)]})

    # Exact unchanged or relocated units need no similarity guess.
    exact = {_normal(u['text']) for u in new}
    aligned = []
    for original in old:
        if _normal(original['text']) in exact:
            continue
        # Prefer the same dated entry, then text overlap. Show a candidate, not an equivalence verdict.
        candidates = [u for u in new if u['entry'] == original['entry']]
        best = max(candidates, key=lambda u: SequenceMatcher(None, _normal(original['text']), _normal(u['text']), autojunk=False).ratio(), default=None)
        similarity = SequenceMatcher(None, _normal(original['text']), _normal(best['text']), autojunk=False).ratio() if best else 0
        match = best if similarity >= .35 else None
        before = original['span']
        after = match['span'] if match else None
        a, b = original['text'], match['text'] if match else ''
        sa, sb = signature(a), signature(b)
        aligned.append({'before': before, 'after': after, 'similarity': round(similarity, 3)})
        if author_disclaimer(a):
            add('attribution_reframe', before, after,
                '仕様説明は参照、個別の結果や手順は報告元を移動先で確認する。条件を保って筆者の断りを削る。',
                {'required_action': 'attribute_source'})
            continue
        if match is None:
            add('removed_claim', before, None, '省いた説明の役割を確認する。移した情報は移動先で確かめる。')
            continue
        changed = sa ^ sb
        polarity = bool(NEGATION.search(a)) != bool(NEGATION.search(b))
        preface = exposition_candidate(a)
        wording_only = (preface is not None and _normal(preface['body']) == _normal(b))
        if wording_only and not polarity:
            add('source_wording_change', before, after,
                '説明用の資料名を省いた候補。資料の根拠、参照の位置、適用条件を確認する。',
                {'source_role': preface, 'requires_material_review': True})
        elif changed or polarity:
            evidence = sorted(material_units, key=lambda u: SequenceMatcher(None, _normal(a), _normal(u['text']), autojunk=False).ratio(), reverse=True)[:2]
            add('claim_force_or_scope', before, after,
                '主体・条件・時点・肯否・確かさ・予定と実績を読み比べる。条件を移した場合はその文も確認する。',
                {'before_signals': sorted(sa), 'after_signals': sorted(sb),
                 'negation_changed': polarity, 'material_candidates': [u['span'] for u in evidence]})

    # New claims or changed units with quantities remain visible even when inventory sets match.
    changed_units = [u for u in new if _normal(u['text']) not in {_normal(x['text']) for x in old}]
    links = {x['after']['start'] for x in aligned if x['after']}
    for unit in changed_units:
        if unit['span']['start'] not in links:
            add('added_claim', None, unit['span'], '追加した説明の出典と主張の強さを確認する。分割した文は原文と続けて読む。')
    source_profile = closure_profile(source, source_name)
    final_profile = closure_profile(final, final_name)
    old_frames = {_normal(x['text']) for x in source_profile['negative_closures']}
    added_frames = [x for x in final_profile['negative_closures'] if _normal(x['text']) not in old_frames]
    if added_frames:
        add('negative_closure_change', None, added_frames[0],
            '加わった否定の結びを原文と比べる。観測結果と対応を直接書けるか確認する。',
            {'before_count': len(source_profile['negative_closures']),
             'after_count': len(final_profile['negative_closures']),
             'added_or_reworded': added_frames})
    return {'style_change': {'source': source_profile, 'final': final_profile}, 'method': 'lexical-diff-4' , 'findings': findings,
            'changed_units': aligned,
            'diff': ''.join(unified_diff(source.splitlines(True), final.splitlines(True), fromfile=source_name, tofile=final_name)),
            'review_axes': ['主体', '対象', '条件', '時点', '数値', '肯否', '確かさ', '文の役割'],
            'meaning_review': 'requires_context_review'}
