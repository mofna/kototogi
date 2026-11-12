"""資料名の前置きを再読候補にする。内容の確かさは資料で確認する。"""
from __future__ import annotations

import re

# These probes describe wording, not the truth or universality of a statement.
PREFACE = re.compile(
    r'^\s*(?P<label>[^。！？!?\n、,]{1,100}?)(?:によると|によれば|では)'
    r'\s*[、,]\s*(?P<body>\S.*)$', re.S)
REFERENCE = re.compile(
    r'MDN|web\.dev|ドキュメント|リファレンス|マニュアル|仕様書|技術文書'
    r'|公式資料|解説記事|ブログ|の説明', re.I)
SPECIFIC = {
    'procedure': re.compile(r'手順|案内|紹介|チュートリアル|操作例|設定例|使い方'),
    'observation': re.compile(r'測定|計測|ベンチマーク|実験|研究|追試|調査|観測|検証結果|アンケート|回答者|調べた|確認した|報告'),
    'viewpoint': re.compile(r'推奨|勧め|提案|見解|考え|主張|賛否|解釈|意見|仮説|予測|議論|草案|未確認|未検証|かもしれ|とされ|疑われ|可能性'),
    'time_or_version': re.compile(r'時点|最新版|最新|現在|現行|当時|20\d{2}[年/-]|(?:バージョン|version|Chrome|Firefox|Safari)\s*\d', re.I),
    'measurement': re.compile(r'\d+(?:\.\d+)?\s*(?:ms|ミリ秒|秒|分|%|％|倍|回|件|台)(?![A-Za-z])'),
    'quotation': re.compile(r'[「『“”」』]'),
}
SPECIFIC_CONTEXT = re.compile(r'この実験|同研究|今回の測定|同社の調査|この調査|この報告|当該検証')
TECHNICAL = re.compile(
    r'仕様|実装|構文|イベント|メモリー?|引数|戻り値|プロパティ|データ|ページ'
    r'|関数|HTTP|JavaScript|HTML|DOM|API|キャッシュ|型|演算子|ファイル|配列', re.I)


def exposition_candidate(text: str, *, context: str = '') -> dict | None:
    """Return a conservative wording candidate, or leave source-specific prose alone."""
    matched = PREFACE.match(text.strip())
    if not matched:
        return None
    label, body = matched['label'].strip(), matched['body'].strip()
    if not REFERENCE.search(label):
        return None
    combined = label + ' ' + body
    if any(rx.search(combined) for rx in SPECIFIC.values()):
        return None
    if SPECIFIC_CONTEXT.search(context):
        return None
    if not TECHNICAL.search(body):
        return None
    return {'role': 'exposition_candidate', 'label': label, 'body': body,
            'evidence': '資料名の前置きと技術的な説明文',
            'requires_material_review': True}
