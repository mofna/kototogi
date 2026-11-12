"""近接した条件説明を照合する。型と共通の語を再読の根拠にする。"""
from __future__ import annotations

import re

# The evidence is deliberately explicit. These are lexical probes, not entailment tests.
PATTERNS = {
    'environment': re.compile(r'(?:この|その)(?:所要時間|時間|数値|値|結果).{0,65}(?:環境|条件).{0,30}(?:値|結果|時間|もの|限[るりられ])|別の環境.{0,60}(?:意味ではない|保証.{0,10}ない)'),
    'attribution': re.compile(r'(?:これ(?:ら)?|以上|この(?:記述|報告|結果)).{0,85}(?:把握状況|報告に基づ|報告であり|による報告|実験報告|把握.{0,10}記述)'),
    'scope': re.compile(r'(?:この|その)(?:結果|数値|値|記録|成功).{0,65}(?:試験|検証|測定|実験).{0,25}(?:範囲|限[るりられ]|結果|値)'),
}
ATTR = re.compile(r'報告(?:によると|では|は|によれば|した|しました|して(?:いる|います)|で)|(?:説明|記述|記して|把握して)(?:いる|います|いない|いません)|によると|公表')
DATE = re.compile(r'(?:20\d{2}年)?\d{1,2}月\d{1,2}日|20\d{2}-\d{2}-\d{2}')
NUMBER = re.compile(r'(?<![A-Za-z0-9_])\d+(?:[,.:/-]\d+)*(?:分|秒|件|回|ms|%|％)?')
ID = re.compile(r'(?<![A-Za-z0-9_])(?:[A-Z]{2,}\d*|[A-Z][a-z]+(?:[A-Z][a-z]+)*|v\d+(?:\.\d+)*)(?![A-Za-z0-9_])')
SCOPE = re.compile(r'host|GPU|CPU|native|Vulkan|Metal|環境[A-Za-zＡ-Ｚａ-ｚ0-9]+|条件[A-Za-zＡ-Ｚａ-ｚ0-9]+', re.I)
NEW_STATE = re.compile(r'未確認|未実施|失敗|成功|達成|未達|未解決')


def _keys(rx, text):
    return {m[0] for m in rx.finditer(text)}


def repeated_condition(previous: list[str], current: str) -> dict | None:
    """Return explainable overlap evidence for a demonstrative restatement."""
    current = re.sub(r'\s+', '', current)
    before = ''.join(re.sub(r'\s+', '', s) for s in previous)
    if not before or not current:
        return None
    family = next((key for key, rx in PATTERNS.items() if rx.search(current)), None)
    if family is None:
        return None
    # A new subject, date, environment, quantity or test state deserves its own claim.
    for rx in (DATE, NUMBER, ID, SCOPE, NEW_STATE):
        probe = current.replace('成功するという意味ではない', '') if rx is NEW_STATE and family == 'environment' else current
        new = _keys(rx, probe) - _keys(rx, before)
        if new:
            return None
    if re.search(r'別の研究|別の報告|他社|一方|ただし|追加で|変更後|更新後', current):
        return None
    if family == 'environment':
        evidence = re.search(r'(?:環境|条件|概念実証)(?:では|で|において)|環境での', before)
    elif family == 'attribution':
        evidence = ATTR.search(before)
    else:
        scopes = _keys(SCOPE, current) & _keys(SCOPE, before)
        evidence = scopes and re.search(r'(?:試験|検証|測定|実験).{0,30}(?:で|成功|結果)', before)
    if not evidence:
        return None
    return {'family': family, 'shared_scopes': sorted(_keys(SCOPE, current) & _keys(SCOPE, before)),
            'shared_dates': sorted(_keys(DATE, current) & _keys(DATE, before)),
            'evidence': evidence[0]}
