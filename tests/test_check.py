"""校正による意味の変化候補とファイル照合の試験。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from meaning import compare


def changes(a, b, materials=()):
    return compare(a, b, source_name='original.md', final_name='final.md', materials=list(materials))


class MeaningTests(unittest.TestCase):
    def test_epistemic_to_broad_denial(self):
        fs = changes('この記述は有無を断定する情報ではない。', 'この記述は有無を示すものではない。')['findings']
        self.assertTrue(any(f['rule'] == 'claim_force_or_scope' for f in fs))

    def test_unknown_to_absent(self):
        fs = changes('同社は配送遅延の記録を把握していない。', '配送遅延はない。')['findings']
        self.assertTrue(fs)

    def test_reduce_to_eliminate(self):
        fs = changes('書類の処理時間を短縮した。', '書類の処理時間をなくした。')['findings']
        self.assertTrue(any(f['rule'] == 'claim_force_or_scope' for f in fs))

    def test_permission_to_action(self):
        fs = changes('対象には試験も含めてよい。', '対象には試験も含める。')['findings']
        self.assertTrue(any(f['rule'] == 'claim_force_or_scope' for f in fs))

    def test_planned_to_done(self):
        self.assertTrue(changes('設定を変更する予定だ。', '設定を変更した。')['findings'])

    def test_lost_unconfirmed(self):
        fs = changes('host試験で成功した。GPU試験は未確認。', 'host試験で成功した。')['findings']
        self.assertTrue(any('GPU' in (f['before'] or {}).get('text','') for f in fs))

    def test_same_meaning_comma(self):
        fs = changes('機能は、停止した。', '機能は停止した。')['findings']
        self.assertEqual(fs, [])

    def test_moved_sentences(self):
        self.assertEqual(changes('設定Aは有効だ。\n\n設定Bは未確認。', '設定Bは未確認。\n\n設定Aは有効だ。')['findings'], [])

    def test_citation_only(self):
        fs = changes('結果は未確認。[S1]', '結果は未確認。[S1][S2]')['findings']
        self.assertEqual(fs, [])

    def test_quantities_changed(self):
        fs = changes('試験は30件成功した。', '試験は40件成功した。')['findings']
        self.assertTrue(any(f['rule'] == 'protected_values' and '30件' in f['data']['removed'] for f in fs))

    def test_quantity_subject_swap_shown_in_diff(self):
        d = changes('hostは2件、GPUは3件だった。', 'hostは3件、GPUは2件だった。')
        self.assertTrue(d['changed_units']); self.assertIn('GPUは2件', d['diff'])

    def test_new_material_value_still_reviewed(self):
        fs = changes('試験は30件成功した。', '試験は40件成功した。', [('facts.md','試験は40件だった。')])['findings']
        self.assertTrue(any('40件' in f['data'].get('added_present_in_material', []) for f in fs))

    def test_inline_code_and_url(self):
        fs = changes('`x=1`と[資料](https://example.org/a)を使う。', '`x=2`と[資料](https://example.org/b)を使う。')['findings']
        kinds = {f['data'].get('kind') for f in fs}
        self.assertIn('inline_code',kinds); self.assertIn('urls',kinds)

    def test_code_blocks(self):
        fs = changes('```py\nx = 1\n```', '```py\nx = 2\n```')['findings']
        self.assertTrue(any(f['data'].get('kind') == 'code_blocks' for f in fs))

    def test_all_changed_spans_roundtrip(self):
        a, b = '結果です。\r\nただしGPUは未確認。', 'GPUは成功した。'
        d = changes(a,b)
        for f in d['findings']:
            for key, text in [('before',a),('after',b)]:
                s = f[key]
                if s:
                    self.assertEqual(s['text'], text[s['start']:s['end']])

    def test_output_does_not_claim_semantic_pass(self):
        self.assertEqual(changes('本文。','本文。')['meaning_review'], 'requires_context_review')


class CheckCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.a, self.b, self.m, self.r = (self.path/x for x in ['a.md','b.md','m.md','review.json'])
        self.a.write_text('GPU検証は未確認。',encoding='utf-8')
        self.b.write_text('GPU検証は成功した。',encoding='utf-8')
        self.m.write_text('GPU検証は未確認。',encoding='utf-8')

    def invoke(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/check.py'),*map(str,args)], capture_output=True,text=True,encoding='utf-8')

    def run_check(self):
        return self.invoke('run','--source',self.a,'--final',self.b,'--material',self.m,'--record',self.r,'--json')

    def test_run_and_verify(self):
        a, b = self.a.read_bytes(), self.b.read_bytes()
        result = self.run_check()
        self.assertEqual(result.returncode,0,result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record['final']['sha256'],hashlib.sha256(b).hexdigest())
        self.assertTrue(record['comparison']['findings'])
        v=self.invoke('verify','--final',self.b,'--record',self.r,'--json')
        self.assertEqual(v.returncode,0,v.stderr)
        self.assertTrue(json.loads(v.stdout)['file_match'])
        self.assertEqual(self.a.read_bytes(),a);self.assertEqual(self.b.read_bytes(),b)

    def test_changed_final_detected(self):
        self.run_check();self.b.write_text('変更。',encoding='utf-8')
        self.assertEqual(self.invoke('verify','--final',self.b,'--record',self.r).returncode,1)

    def test_changed_material_detected(self):
        self.run_check();self.m.write_text('変更。',encoding='utf-8')
        self.assertEqual(self.invoke('verify','--final',self.b,'--record',self.r).returncode,1)

    def test_same_source_final_rejected(self):
        r=self.invoke('run','--source',self.a,'--final',self.a,'--record',self.r)
        self.assertEqual(r.returncode,2)

    def test_record_cannot_overwrite_source(self):
        r=self.invoke('run','--source',self.a,'--final',self.b,'--record',self.a)
        self.assertEqual(r.returncode,2)

    def test_crlf_byte_hash(self):
        self.b.write_bytes('第一文。\r\n第二文。\r\n'.encode('utf-8'))
        d=json.loads(self.run_check().stdout)
        self.assertEqual(d['final']['sha256'],hashlib.sha256(self.b.read_bytes()).hexdigest())
        from lint import analyze
        self.assertEqual(d['lint'], analyze(self.b.read_text(encoding='utf-8-sig'), source=str(self.b)))

    def test_invalid_record_handled(self):
        self.r.write_text('{}',encoding='utf-8')
        r=self.invoke('verify','--final',self.b,'--record',self.r)
        self.assertEqual(r.returncode,2);self.assertNotIn('Traceback',r.stderr)

    def test_missing_input_handled(self):
        self.a.unlink();r=self.run_check()
        self.assertEqual(r.returncode,2);self.assertNotIn('Traceback',r.stderr)

    def test_copied_final_allowed_if_bytes_match(self):
        self.run_check()
        copy=self.path/'published.md';copy.write_bytes(self.b.read_bytes())
        self.assertEqual(self.invoke('verify','--final',copy,'--record',self.r).returncode,0)


if __name__ == '__main__':
    unittest.main()
