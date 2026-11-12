"""出典付き文末と条件の言い直しを検査する回帰例。"""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import structure
import lint
from markdown_text import project


def rule_ids(text, **kwargs):
    fs, _ = structure.analyze_structure(text, **kwargs)
    return {r for f in fs for r in f['data']['rules']}


class CitationTests(unittest.TestCase):
    text = 'host試験は成功した。GPU検証は未確認。\n\n描画を追加した。native比較は未実施。\n\n読取りに対応した。全形式の確認は必要である。'

    def test_suffixes_keep_metrics_and_terminal(self):
        suffixes = ('[S1]', '[S1][S2]', '[1]', '[1, 2]', '[^note]', '【1】',
                    '[出典](https://example.org/?q=1)', '<sup>1</sup>',
                    '<sup><a href="#fn1">1</a></sup>')
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                text = self.text.replace('。\n', '。'+suffix+'\n') + suffix
                self.assertEqual(len(lint.prose_parts(text)[2]), 6)
                self.assertIn('S01', rule_ids(text))
                doc = structure.parse_markdown(text)
                self.assertEqual(sum(len(b.sentences) for b in doc.paragraphs), 6)
                for b in doc.paragraphs:
                    self.assertTrue(b.sentences[-1].terminal)
                    s = b.sentences[-1]
                    self.assertEqual(doc.location(s.start, s.end)['text'], text[s.start:s.end])
                self.assertEqual(sum(x.count('、') for _, x in lint.prose_parts(text)[0]), 0)

    def test_citation_before_stop(self):
        self.assertEqual(len(lint.prose_parts('本文[S1]。次です[^n]。')[2]), 2)

    def test_single_citation_not_sentence(self):
        self.assertEqual(lint.prose_parts('[S1]')[2], [])

    def test_code_brackets_preserved(self):
        raw = '`a[1]` の値。[S1]'
        self.assertIn('a[1]', project(raw, mask_code=False))
        self.assertNotIn('S1', project(raw, mask_code=False))

    def test_array_index_in_prose_kept(self):
        self.assertIn('array[1]の', project('array[1]の値を読む。'))

    def test_regular_link_label_kept(self):
        self.assertIn('検証は未確認', project('[検証は未確認](https://example.org)'))

    def test_reference_style_link(self):
        doc = structure.parse_markdown('本文。[出典][a]\n\n[a]: https://example.org\n')
        self.assertEqual(len(doc.paragraphs), 1)
        self.assertEqual(len(doc.paragraphs[0].sentences), 1)

    def test_soft_break_one_sentence_metrics(self):
        self.assertEqual(len(lint.prose_parts('条件を\n結果に添える。')[2]), 1)

    def test_quote_tail(self):
        self.assertEqual(len(lint.prose_parts('「本文。」[S1]')[2]), 1)

    def test_fenced_citations_ignored(self):
        self.assertEqual(lint.prose_parts('````\n```\n本文。[S1]\n````\n実文。')[2], [(5,'実文')])

    def test_frontmatter_not_prose(self):
        self.assertEqual(lint.prose_parts('---\ndescription: これは説明。\n---\n本文。')[2], [(4,'本文')])

    def test_reference_def_not_prose(self):
        self.assertEqual(lint.prose_parts('本文。[^n]\n\n[^n]: 注釈文。\n    注釈の続き。')[2], [(1,'本文')])


class RepetitionTests(unittest.TestCase):
    def test_positive_environment(self):
        self.assertIn('S07', rule_ids('配送班の試験環境では仕分けに23分を要した。この所要時間は配送班が報告した環境での値だ。'))

    def test_negative_environment(self):
        self.assertIn('S07', rule_ids('配送班の試験環境では仕分けに23分を要した。別の環境でも同じ時間で成功するという意味ではない。'))

    def test_source_attribution(self):
        self.assertIn('S07', rule_ids('同社は11月10日時点で配送遅延の記録を把握していないと報告した。これは同社の把握状況についての記述だ。'))

    def test_author_activity(self):
        self.assertIn('S07', rule_ids('音響班の実験報告では雑音を3回検出した。これは研究者自身の実験報告であり、筆者が再実行した結果ではない。'))

    def test_new_subject(self):
        self.assertNotIn('S07', rule_ids('Alphaの実証環境では23分を要した。この所要時間はBetaの環境での値だ。'))

    def test_new_environment(self):
        self.assertNotIn('S07', rule_ids('環境Aでは20msを要した。この結果は環境Bでの値だ。'))

    def test_new_quantity(self):
        self.assertNotIn('S07', rule_ids('配送班の試験環境では仕分けに23分を要した。この結果はGPUを2台使った環境での値だ。'))

    def test_new_date(self):
        self.assertNotIn('S07', rule_ids('同社は11月2日時点で把握していないと報告した。これは11月11日の把握状況だ。'))

    def test_new_state(self):
        self.assertNotIn('S07', rule_ids('host試験は成功した。この結果ではGPU検証は未確認だ。'))

    def test_first_scope_information(self):
        self.assertNotIn('S07', rule_ids('23分を要した。この所要時間は配送班が報告した環境での値だ。'))

    def test_no_cross_paragraph_inference(self):
        self.assertNotIn('S07', rule_ids('配送班の試験環境では仕分けに23分を要した。\n\nこの所要時間は配送班の環境での値だ。'))

    def test_selfcheck_mentions(self):
        text = '「配送班の試験環境では仕分けに23分を要した。この所要時間は配送班が報告した環境での値だ。」を例にする。'
        self.assertNotIn('S07', rule_ids(text, self_check=True))

    def test_not_negative_blacklist(self):
        self.assertNotIn('S07', rule_ids('GPU検証は未実施。未知の入力は受け入れない。次の課題は残る。'))


if __name__ == '__main__':
    unittest.main()
