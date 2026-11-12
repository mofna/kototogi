"""ファイル、文字列、標準入力の診断を比較する。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import lint
from text_input import normalize, read_stdin

TEXT = '音響班の報告では雑音を3回検出しました。筆者が再実行した結果ではありません。[S1]\n\nこの設定は地味に効きます。'


class TextInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        (self.cwd / 'article.md').write_text(TEXT, encoding='utf-8')

    def invoke(self, tool, *args, data=None):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / tool), *args],
                              cwd=self.cwd, input=data, capture_output=True, env=env, timeout=30)

    def report(self, *args, data=None):
        p = self.invoke('lint.py', *args, '--json', data=data)
        self.assertEqual(p.returncode, 0, p.stderr.decode('utf-8'))
        return json.loads(p.stdout)

    def check(self, *args, data=None):
        return self.invoke('check.py', 'text', *args, '--json', data=data)

    def test_input_routes_match(self):
        expected = self.report('article.md')
        for args, data in [
            (('--text', TEXT, '--label', 'article.md'), None),
            (('--stdin', '--label', 'article.md'), TEXT.encode('utf-8')),
            (('-', '--label', 'article.md'), TEXT.encode('utf-8')),
        ]:
            with self.subTest(args=args):
                self.assertEqual(expected, self.report(*args, data=data))
        self.assertEqual(expected, lint.analyze(TEXT, source='article.md'))

    def test_utf8_bom_crlf_matches_file(self):
        raw = ('\ufeff' + TEXT.replace('\n', '\r\n')).encode('utf-8')
        self.assertEqual(self.report('article.md'), self.report('--stdin', '--label', 'article.md', data=raw))
        self.assertEqual(self.report('article.md'), self.report('--text', raw.decode('utf-8'), '--label', 'article.md'))

    def test_empty_text_is_valid(self):
        d = self.report('--text', '')
        self.assertEqual(d['metrics']['sentences'], 0)
        self.assertEqual(d['findings'], [])

    def test_empty_stdin_is_valid(self):
        self.assertEqual(self.report('--stdin', data=b'')['metrics']['prose_chars'], 0)

    def test_missing_input_is_error(self):
        self.assertEqual(self.invoke('lint.py').returncode, 2)

    def test_input_conflicts_are_errors(self):
        for args in [('article.md','--text','x'), ('article.md','--stdin'), ('--text','x','--stdin')]:
            with self.subTest(args=args):
                self.assertEqual(self.invoke('lint.py', *args, data=b'x').returncode, 2)

    def test_file_label_conflict(self):
        self.assertEqual(self.invoke('lint.py', 'article.md', '--label', 'a').returncode, 2)

    def test_invalid_labels(self):
        for name in ('', ' ', 'line\nline'):
            self.assertEqual(self.invoke('lint.py', '--text', '本文。', '--label', name).returncode, 2)

    def test_invalid_utf8(self):
        p = self.invoke('lint.py', '--stdin', data=b'\xff')
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(b'Traceback', p.stderr)

    def test_literal_shell_text(self):
        text = '日本語と🍵。$HOME; $(Write-Output hello) & "quoted" `code`'
        self.assertEqual(self.report('--text',text), lint.analyze(text))

    def test_dash_leading_text(self):
        self.assertEqual(self.report('--text=--example')['metrics']['sentences'], 1)

    def test_display_name_is_not_opened(self):
        d = self.report('--text', TEXT, '--label', 'missing/subdir/name.md')
        spans = [o['span'] for f in d['findings'] if f['category']=='structure' for o in f['data']['observations']]
        self.assertTrue(spans)
        self.assertTrue(all(s['source']=='missing/subdir/name.md' for s in spans))
        self.assertFalse((self.cwd/'missing').exists())

    def test_normal_and_self_check_separated(self):
        text = '「地味に効く」という語を説明します。'
        a = self.report('--text',text)
        b = self.report('--text',text,'--self-check')
        self.assertGreater(len(a['findings']),len(b['findings']))

    def test_multiline_spans_match(self):
        d = self.report('--text',TEXT)
        spans = [o['span'] for f in d['findings'] if f['category']=='structure' for o in f['data']['observations']]
        for s in spans:
            self.assertEqual(s['text'], TEXT[s['start']:s['end']])

    def test_history_and_entry_date_text(self):
        text='## 2026-11-10\n\n昨日の処理です。\n\n## 2026-11-11\n\n今日の処理です。'
        (self.cwd/'daily.md').write_text(text,encoding='utf-8')
        extra=('--kind','progress-log','--entry-date','2026-11-11')
        self.assertEqual(self.report('daily.md',*extra),self.report('--text',text,'--label','daily.md',*extra))

    def test_invalid_entry_kind(self):
        self.assertEqual(self.invoke('lint.py','--text','本文。','--entry-date','2026-11-11').returncode,2)

    def test_text_check_required_rewrite(self):
        p=self.check('--text',TEXT)
        self.assertEqual(p.returncode,1)
        d=json.loads(p.stdout)
        self.assertFalse(d['editorial']['ready'])
        self.assertTrue(d['editorial']['required_rewrites'])

    def test_text_check_clean_no_files(self):
        before=set(self.cwd.iterdir())
        p=self.check('--text','公式資料によると、更新は1件ずつ進みます。')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertTrue(json.loads(p.stdout)['editorial']['ready'])
        self.assertEqual(before,set(self.cwd.iterdir()))

    def test_text_check_stdin_parity(self):
        a=json.loads(self.check('--text',TEXT,'--label','answer').stdout)
        b=json.loads(self.check('--stdin','--label','answer',data=TEXT.encode('utf-8')).stdout)
        self.assertEqual(a,b)

    def test_source_comparison_and_material(self):
        p=self.check('--source-text','同社は事例を把握していません。','--text','事例はありません。',
                     '--material-text','同社は事例を把握していません。')
        self.assertEqual(p.returncode,0,p.stderr)
        d=json.loads(p.stdout)
        self.assertTrue(d['comparison']['findings'])
        self.assertIn('事例はありません',d['comparison']['diff'])

    def test_material_requires_source(self):
        self.assertEqual(self.check('--text','本文。','--material-text','資料。').returncode,2)

    def test_text_check_hash(self):
        text='\ufeff本文。\r\n次の段落。'
        d=json.loads(self.check('--text',text).stdout)
        raw=normalize(text).encode('utf-8')
        self.assertEqual(d['input']['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(d['input']['bytes'],len(raw))

    def test_text_check_human_output(self):
        p=self.invoke('check.py','text','--text','筆者は再実行していません。')
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertIn('S08',p.stdout.decode('utf-8'))
        self.assertIn('SHA-256',p.stdout.decode('utf-8'))

    def test_text_check_missing_input(self):
        self.assertEqual(self.invoke('check.py','text').returncode,2)

    def test_long_stdin(self):
        text=''.join('記録を保存します。\n\n' for _ in range(500))
        d=self.report('--stdin',data=text.encode('utf-8'))
        self.assertEqual(d['metrics']['sentences'],500)

    def test_no_tty_wait(self):
        class Console(io.StringIO):
            def isatty(self):
                return True
        with self.assertRaises(ValueError):
            read_stdin(Console())

    def test_read_string_stream(self):
        self.assertEqual(read_stdin(io.StringIO('本文。\r\n次。')),'本文。\n次。')


    def test_polite_modal_signatures(self):
        from meaning import signature
        pairs = [
            ('knowledge_limit','同社は事例を把握していない。','同社は事例を把握していません。'),
            ('possibility','遅くなる場合がある。','遅くなる場合があります。'),
            ('possibility','遅くなるかもしれない。','遅くなるかもしれません。'),
            ('obligation','更新する必要がある。','更新する必要があります。'),
            ('incomplete','研究室は再検出できない。','研究室は再検出できません。'),
            ('incomplete','研究室は達成していない。','研究室は達成していません。'),
            ('absolute','結果を保証する。','結果を保証します。'),
        ]
        for key, a, b in pairs:
            with self.subTest(key=key,a=a):
                self.assertIn(key,signature(a)); self.assertIn(key,signature(b))

    def test_polite_attribution_restatement(self):
        from conditions import repeated_condition
        d = repeated_condition(['同社は事例を把握していません。'],
                               'これは同社の把握状況についての記述です。')
        self.assertIsNotNone(d)

    def test_style_only_keeps_modal_meaning(self):
        from meaning import compare
        d=compare('遅くなる場合がある。','遅くなる場合があります。',source_name='before',final_name='after')
        self.assertFalse(any(f['rule']=='claim_force_or_scope' for f in d['findings']))



    def test_polite_questions_and_suggestions(self):
        text='設定を確認しましょう。これは仕様ですか。記録を見てください。成功しませんでした。変わりませんか。便利ですよね。'
        self.assertEqual(lint.analyze(text)['metrics']['polite_sentence_ratio'],1.0)
        self.assertEqual(lint.analyze('設定を変更する。')['metrics']['polite_sentence_ratio'],0.0)
        for text in ('設定は有効だ。記録も残る。', '設定は有効なんだよね。記録も残るよ。', '設定は有効です。記録も残ります。'):
            with self.subTest(text=text):
                self.assertEqual(lint.analyze(text)['findings'], [])


if __name__=='__main__':
    unittest.main()
