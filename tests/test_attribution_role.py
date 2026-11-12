"""仕様説明と資料に固有の情報の対照を確認する。"""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from structure import analyze_structure
from meaning import compare

FACT_A = '公式仕様書によると、記録ツールは`header`オプションでCSVファイルの列名を設定できます。[S2][S4]'
FACT_B = '公式仕様書の説明によると、記録ツールは読み込んだCSVファイルを配列に変換します。[S1][S4]'
METHOD = '記録ツールの導入マニュアルでは、次の確認手順が案内されています。[S3]'


def s10(text, **kwargs):
    return [f for f in analyze_structure(text, **kwargs)[0] if 'S10' in f['data']['rules']]


class SourceRoleTests(unittest.TestCase):
    def test_exposition_across_registers(self):
        cases = [FACT_A, FACT_B,
                 '公式仕様書によると、関数は配列を返す。',
                 '公式仕様書によると、関数は配列を返します。',
                 '公式仕様書によると、関数は配列を返すんだよね。']
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(len(s10(text)), 1)

    def test_reviewer_only(self):
        found = s10(FACT_A)[0]
        self.assertEqual(found['level'], 'REVIEW')
        self.assertTrue(found['data']['observations'][0]['source_role']['requires_material_review'])

    def test_docs_not_whitelisted(self):
        self.assertTrue(s10('Z言語のリファレンスによれば、引数の型は実行時に検査されます。'))

    def test_blog_exposition(self):
        self.assertTrue(s10('実装解説ブログによると、この関数は配列を返します。'))

    def test_selected_method(self):
        self.assertFalse(s10(METHOD))

    def test_same_doc_other_roles(self):
        for text in [
            '公式マニュアルによると、この手順でデータを更新します。',
            '公式マニュアルによると、この実験では処理が30ms短縮しました。',
            '公式仕様書によると、このAPIの使用を推奨しています。',
            '公式仕様書によると、2026年11月時点でこのAPIは使用できます。',
            '公式仕様書によると、バージョン 2ではこのAPIを使用できます。',
            '公式仕様書によると、このAPIは廃止される可能性があります。',
            '公式マニュアルによると、この実装が望ましいという見解です。',
            '仕様書によると、このAPIの挙動は議論中です。',
            '公式仕様書によると、正式な定義は「データを返す」です。',
        ]:
            with self.subTest(text=text): self.assertFalse(s10(text))

    def test_research_person(self):
        self.assertFalse(s10('A研究室によると、この環境でAPIの処理が成功しました。'))

    def test_report_context(self):
        self.assertFalse(s10('この実験の結果を読みます。\n公式仕様書によると、APIはデータを返します。'))

    def test_direct_statement(self):
        self.assertFalse(s10('記録ツールは`header`オプションでCSVファイルの列名を設定できます。[S2][S4]'))

    def test_protected_blocks(self):
        self.assertFalse(s10('> ' + FACT_A + '\n\n```text\n' + FACT_B + '\n```'))

    def test_selfcheck_mention(self):
        self.assertFalse(s10('「' + FACT_A + '」という用語例を説明する。', self_check=True))

    def test_raw_offsets(self):
        text = '# 題名\r\n\r\n' + FACT_A
        span = s10(text)[0]['data']['observations'][0]['span']
        self.assertEqual(span['line'], 3)
        self.assertEqual(span['text'], text[span['start']:span['end']])

    def test_daily_scope(self):
        text = '## 2026-11-10\n\n' + FACT_A + '\n\n## 2026-11-11\n\n' + METHOD
        self.assertFalse(s10(text, kind='progress-log', entry_date='2026-11-11'))

    def test_two_same_paragraph_grouped(self):
        self.assertEqual(len(s10(FACT_A + '\n' + FACT_B)), 1)

    def test_facts_and_method(self):
        self.assertEqual(len(s10(FACT_A + '\n\n' + FACT_B + '\n\n' + METHOD)), 2)

    def test_diff_preface_only(self):
        final = '記録ツールは`header`オプションでCSVファイルの列名を設定できます。[S2][S4]'
        result = compare(FACT_A, final, source_name='a', final_name='b')
        self.assertTrue(any(f['rule'] == 'source_wording_change' for f in result['findings']))
        self.assertFalse(any(f['rule'] == 'claim_force_or_scope' for f in result['findings']))

    def test_diff_new_certainty_still_flagged(self):
        result = compare('公式仕様書によると、APIはデータを返すことがあります。',
                         'APIは必ずデータを返します。', source_name='a', final_name='b')
        self.assertTrue(any(f['rule'] == 'claim_force_or_scope' for f in result['findings']))

    def test_measurement_scope_guard(self):
        result = compare('A社の公式資料によると、環境XでAPIの処理が30ms短縮しました。',
                         'APIの処理が30ms短縮しました。', source_name='a', final_name='b')
        self.assertTrue(any(f['rule'] == 'claim_force_or_scope' for f in result['findings']))
        self.assertFalse(any(f['rule'] == 'source_wording_change' for f in result['findings']))

    def test_url_loss_guard(self):
        result = compare(FACT_A + '\n\n参考: https://example.org/reference',
                         '記録ツールは`header`オプションでCSVファイルの列名を設定できます。', source_name='a', final_name='b')
        self.assertTrue(any(f['rule'] == 'protected_values' and f['data']['kind'] == 'urls' for f in result['findings']))

    def test_author_disclaimer_stays_required(self):
        fs = analyze_structure('筆者が再実行した結果ではありません。')[0]
        self.assertTrue(any(f['level'] == 'REWRITE' and 'S08' in f['data']['rules'] for f in fs))

    def test_cli_text_stdin_equivalent(self):
        cmd = [sys.executable, '-B', str(ROOT/'scripts/lint.py')]
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        a = subprocess.run(cmd+['--text', FACT_A, '--label', '稿', '--json'], capture_output=True, encoding='utf-8', env=env)
        b = subprocess.run(cmd+['--stdin', '--label', '稿', '--json'], input=FACT_A, capture_output=True, encoding='utf-8', env=env)
        self.assertEqual(a.returncode, 0, a.stderr); self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(json.loads(a.stdout), json.loads(b.stdout))


if __name__ == '__main__':
    unittest.main()
