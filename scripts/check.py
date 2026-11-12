#!/usr/bin/env python3
"""校正稿のlint、原文との差、提出ファイルの一致を確認する。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True

from meaning import compare
from lint import analyze
from text_input import normalize, read_stdin, label, utf8_output

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'kototogi-check-1'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> tuple[dict, str]:
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': digest(data), 'bytes': len(data)}, data.decode('utf-8-sig')


def save_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    fd, temp = tempfile.mkstemp(prefix='.kototogi-check-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run(args) -> dict:
    method_request = args.author_method_request
    paths = [args.source, args.final] + args.material + args.history + ([method_request] if method_request else [])
    resolved = [p.resolve() for p in paths]
    if resolved[0] == resolved[1]:
        raise ValueError('原文を残し、校正稿を別名で指定してください。')
    if args.record.resolve() in resolved or args.record.resolve() == Path(__file__).resolve():
        raise ValueError('記録先には原文・校正稿・資料と異なるパスを指定してください。')
    if args.final.resolve() in [p.resolve() for p in args.history]:
        raise ValueError('原稿と同じファイルを --history へ指定しています。')
    source_info, source = read(args.source)
    final_info, final = read(args.final)
    material_info, material_text = [], []
    for p in args.material:
        info, text = read(p)
        material_info.append(info); material_text.append((str(p.resolve()), text))
    method_info = None
    if method_request:
        method_info, request_text = read(method_request)
        if not request_text.strip():
            raise ValueError('検証方法の明示を求めた依頼文を指定してください。')
    tool_info = [read(p)[0] for p in sorted((ROOT/'scripts').glob('*.py'))] + [read(ROOT/'references/features.json')[0]]
    if args.record.resolve() in {Path(x['path']) for x in tool_info}:
        raise ValueError('検査ツールと異なる記録先を指定してください。')
    history_info, history_text = [], []
    for p in args.history:
        info, text = read(p)
        history_info.append(info)
        history_text.append((str(p), normalize(text)))
    lint = analyze(normalize(final), source=str(args.final), self_check=args.self_check,
                   kind=args.kind, history=history_text, entry_date=args.entry_date)
    # The full diff is retained even when lint focuses on one daily entry.
    comparison = compare(source, final, source_name=str(args.source.resolve()), final_name=str(args.final.resolve()), materials=material_text)
    inputs = [source_info, final_info] + material_info + history_info + ([method_info] if method_info else [])
    for info in inputs + tool_info:
        if digest(Path(info['path']).read_bytes()) != info['sha256']:
            raise ValueError('検査中にファイルが変わりました: ' + info['path'])
    required = [obs['span'] for f in lint['findings'] if f['category'] == 'structure'
                for obs in f['data'].get('observations', []) if obs['rule'] == 'S08']
    editorial = {'author_method_request': method_info,
                 'required_rewrites': required, 'self_check': args.self_check,
                 'ready': not required or method_info is not None}
    record = {'editorial': editorial, 'format': FORMAT, 'created_at': datetime.now(timezone.utc).isoformat(),
              'source': source_info, 'final': final_info, 'materials': material_info,
              'history': history_info, 'tools': tool_info,
              'lint': lint, 'comparison': comparison}
    save_record(args.record, record)
    return record


def verify(args) -> dict:
    record = json.loads(args.record.read_text(encoding='utf-8'))
    if not isinstance(record, dict) or record.get('format') != FORMAT:
        raise ValueError('この形式の検査記録には対応していません。')
    final_info, active_text = read(args.final)
    mismatches = []
    if final_info['sha256'] != record['final']['sha256']:
        mismatches.append(str(args.final))
    method_info = record.get('editorial', {}).get('author_method_request')
    for info in [record['source']] + record['materials'] + record.get('history', []) + record['tools'] + ([method_info] if method_info else []):
        p = Path(info['path'])
        if not p.is_file() or digest(p.read_bytes()) != info['sha256']:
            mismatches.append(str(p))
    from editorial import author_disclaimer
    from structure import parse_markdown
    active_text = normalize(active_text)
    scope = record.get('lint', {}).get('structure', {}).get('entry_date')
    parsed = parse_markdown(active_text, str(args.final), self_check=record.get('editorial', {}).get('self_check', False))
    # Recompute rather than trusting an editable boolean in the record.
    unresolved = [parsed.location(s.start,s.end) for b in parsed.paragraphs
                  if scope is None or b.entry == scope
                  for s in b.sentences if author_disclaimer(s.scan)]
    editorial_ready = not unresolved or method_info is not None
    return {'editorial_ready': editorial_ready, 'required_rewrites': unresolved,
            'format': FORMAT, 'file_match': not mismatches, 'mismatches': mismatches,
            'final_sha256': final_info['sha256'], 'record': str(args.record.resolve())}


def text_check(args) -> dict:
    """チャット用の本文をメモリ上で点検する。"""
    text = normalize(args.text) if args.text is not None else read_stdin()
    name = label(args.label, "<text>" if args.text is not None else "<stdin>")
    if args.source_text is None and (args.material or args.material_text):
        raise ValueError("資料との比較には --source-text で校正前の本文も指定してください。")
    result = analyze(text, source=name, self_check=args.self_check)
    required = [obs['span'] for f in result['findings'] if f['category'] == 'structure'
                for obs in f['data'].get('observations', []) if obs['rule'] == 'S08']
    materials = [(str(p), p.read_text(encoding='utf-8-sig')) for p in args.material]
    materials.extend((f'<material:{i}>', normalize(value))
                     for i, value in enumerate(args.material_text, 1))
    comparison = None
    if args.source_text is not None:
        comparison = compare(normalize(args.source_text), text,
                             source_name='<source-text>', final_name=name,
                             materials=materials)
    raw = text.encode('utf-8')
    return {'format': 'kototogi-text-check-1',
            'input': {'label': name, 'sha256': digest(raw), 'bytes': len(raw),
                      'characters': len(text), 'normalization': 'UTF-8 / BOM removed / LF'},
            'editorial': {'ready': not required, 'required_rewrites': required},
            'lint': result, 'comparison': comparison}


def print_text_check(result: dict) -> None:
    print('点検: ' + result['input']['label'])
    for f in result['lint']['findings']:
        print(f"\n{f['level']} L{f['line']} {f['category']}: {f['message']}")
        if f['excerpt']:
            print('  ' + f['excerpt'])
        for obs in f.get('data', {}).get('observations', []):
            print(f"  {obs['rule']}: {obs['question']}")
    if not result['lint']['findings']:
        print('再読候補は0件です。')
    if result['comparison'] is not None:
        for f in result['comparison']['findings']:
            print(f"\nREVIEW {f['id']} {f['rule']}: {f['question']}")
            for key in ('before', 'after'):
                if f[key]:
                    print(f"  {key} L{f[key]['line']}: {f[key]['text']}")
        print('\n全文差分:')
        print(result['comparison']['diff'])
    print('\n本文SHA-256: ' + result['input']['sha256'])


def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run', help='lintと原文・資料との比較を保存する。')
    r.add_argument('--source', type=Path, required=True)
    r.add_argument('--final', type=Path, required=True)
    r.add_argument('--material', type=Path, action='append', default=[])
    r.add_argument('--record', type=Path, required=True)
    r.add_argument('--kind', choices=('article', 'progress-log'), default='article')
    r.add_argument('--entry-date')
    r.add_argument('--history', type=Path, action='append', default=[])
    r.add_argument('--self-check', action='store_true')
    r.add_argument('--author-method-request', type=Path, help='筆者自身の検証方法の記載を求めた依頼文。指定時は明示的な方法説明として保存する。')
    r.add_argument('--json', action='store_true')
    v = sub.add_parser('verify', help='原文・資料・校正稿と検査ツールのハッシュを照合する。')
    v.add_argument('--final', type=Path, required=True)
    v.add_argument('--record', type=Path, required=True)
    v.add_argument('--json', action='store_true')
    x = sub.add_parser('text', help='本文の文字列を点検する。結果は標準出力へ返す。')
    xi = x.add_mutually_exclusive_group(required=True)
    xi.add_argument('--text', help='提出する本文。')
    xi.add_argument('--stdin', action='store_true', help='提出する本文をUTF-8の標準入力から読む。')
    x.add_argument('--label', help='結果に付ける表示名。')
    x.add_argument('--source-text', help='校正前の本文。指定時は全文差分と意味の変化候補も返す。')
    x.add_argument('--material-text', action='append', default=[], help='比較用資料の本文。複数指定可。')
    x.add_argument('--material', type=Path, action='append', default=[])
    x.add_argument('--self-check', action='store_true', help='規則文書の点検用。')
    x.add_argument('--json', action='store_true')
    args = ap.parse_args()
    try:
        if args.command == 'text':
            result = text_check(args)
        else:
            result = run(args) if args.command == 'run' else verify(args)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        ap.error(str(exc))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'text':
        print_text_check(result)
    elif args.command == 'run':
        print('検査記録: ' + str(args.record))
        print('差分確認: 主体・対象・条件・時点・数値・肯否・確かさ・文の役割')
        for span in result['editorial']['required_rewrites']:
            print(f"REWRITE S08 L{span['line']}: {span['text']}")
            print('  仕様説明は参照を添え、個別の結果や手順は報告元を示す。')
        for f in result['comparison']['findings']:
            print(f"\nREVIEW {f['id']} {f['rule']}: {f['question']}")
            for key, label in [('before','原文'),('after','校正稿')]:
                if f[key]:
                    print(f"  {label} L{f[key]['line']}: {f[key]['text'][:300]}")
            if f['rule'] == 'protected_values':
                print('  ' + json.dumps(f['data'], ensure_ascii=False))
        print('\n本文の再読候補は記録の lint.findings、全文差分は comparison.diff にあります。')
    else:
        print('検査時のファイルと一致しました。' if result['file_match'] else '変更を検出しました: ' + ', '.join(result['mismatches']))
        if not result['editorial_ready']:
            print('REWRITE S08: 情報に合う出典表示へ整えてからrunを再実行してください。')
    if args.command == 'verify':
        return 1 if not (result['file_match'] and result['editorial_ready']) else 0
    return 1 if not result['editorial']['ready'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
