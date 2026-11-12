"""保持すべき表記と文の位置を確認する補助試験。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from markdown_text import project
import structure
from conditions import repeated_condition
from meaning import compare


class EdgeTests(unittest.TestCase):
    def test_math_sup_kept(self):
        self.assertIn('2', project('x<sup>2</sup>'))

    def test_terminal_array_kept(self):
        self.assertIn('[1]', project('array[1]'))

    def test_unknown_brackets_kept(self):
        self.assertIn('[GPU]', project('結果。[GPU]'))

    def test_citation_mid_paragraph_stays_with_prior(self):
        raw = '第一文。[S1]第二文。'
        d=structure.parse_markdown(raw)
        self.assertEqual(d.paragraphs[0].sentences[0].end,raw.index('第二'))
        self.assertEqual(d.paragraphs[0].sentences[1].start,raw.index('第二'))

    def test_crlf_citation_source(self):
        raw='一文。\r\n未確認。[S1]\r\n'
        d=structure.parse_markdown(raw)
        s=d.paragraphs[0].sentences[-1]
        self.assertEqual(d.location(s.start,s.end)['line'],2)
        self.assertEqual(raw[s.start:s.end],'未確認。[S1]')

    def test_projection_length(self):
        for raw in ['実文。[S1][S2]','説明。[出典](https://example.org/a)','式はx<sup>2</sup>。','`x[1]`の値。[^n]']:
            self.assertEqual(len(raw),len(project(raw)))
            self.assertEqual(len(raw),len(project(raw,mask_code=False)))

    def test_code_reference_is_not_citation(self):
        self.assertIn('[S1]',project('`[S1]`という文字列。',mask_code=False))

    def test_same_sentence_attribution(self):
        text='配送会社は公告を公開した。同社は証拠を把握していないとしているが、これは配送会社の把握状況についての記述だ。'
        f,_=structure.analyze_structure(text)
        self.assertTrue(any('S07' in x['data']['rules'] for x in f))

    def test_condition_without_prior(self):
        self.assertIsNone(repeated_condition([], 'この時間は配送班の環境での値だ。'))

    def test_different_scope(self):
        self.assertIsNone(repeated_condition(['host試験では成功した。'], 'この結果はGPU試験の結果だ。'))

    def test_code_does_not_trigger_conditions(self):
        f,_=structure.analyze_structure('配送班の試験環境では仕分けに23分を要した。`この所要時間は配送班の環境での値だ。`を表示する。')
        self.assertFalse(any('S07' in x['data']['rules'] for x in f))

    def test_quote_example_not_structural(self):
        f,_=structure.analyze_structure('> 配送班の試験環境では仕分けに23分を要した。この所要時間は配送班の環境での値だ。')
        self.assertEqual(f,[])

    def test_meaning_preserves_noop(self):
        raw='host試験は成功した。GPU試験は未確認。[S1]'
        self.assertEqual(compare(raw,raw,source_name='a',final_name='b')['findings'],[])

    def test_json_serializable(self):
        f=compare('入力は失敗する場合がある。','入力は失敗する。',source_name='a',final_name='b')
        self.assertTrue(json.dumps(f,ensure_ascii=False))

    def test_source_reference_changed_not_linguistic_claim(self):
        d=compare('これは結果。[S1]','これは結果。[S2]',source_name='a',final_name='b')
        self.assertEqual(d['findings'],[])
        self.assertNotEqual(d['diff'],'')


if __name__=='__main__':
    unittest.main()
