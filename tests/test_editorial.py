"""帰属の書き換えと否定結びの回帰を確認する。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from editorial import author_disclaimer, closure_profile
from structure import analyze_structure
from meaning import compare

class EditorialTests(unittest.TestCase):
    def test_detect_variants(self):
        for text in ['これは筆者が再実行した結果ではない。','筆者による追試結果ではない。',
                     '私自身では検証していません。','こちらでは測定していない。',
                     '著者は追試を行っていない。','当方による実測は未実施。']:
            with self.subTest(text=text): self.assertTrue(author_disclaimer(text))
    def test_keep_observations(self):
        for text in ['筆者の追試ではエラーを再現できなかった。','筆者は検証を行った。',
                     '筆者の実験では結果が一致しない。','GPU検証は未確認。',
                     '論文の著者は追試を行っていない。','同社は証拠を把握していない。']:
            with self.subTest(text=text): self.assertFalse(author_disclaimer(text))
    def test_single_sentence_is_required(self):
        fs,_=analyze_structure('これは筆者が再実行した結果ではない。[S1]')
        f=next(f for f in fs if 'S08' in f['data']['rules'])
        self.assertEqual(f['level'],'REWRITE')
    def test_quote_code_protected(self):
        text='> 筆者は検証していない。\n\n```text\n筆者は検証していない。\n```'
        self.assertFalse(analyze_structure(text)[0])
    def test_selfcheck_explicit(self):
        t='「筆者が再実行した結果ではない」を説明する。'
        self.assertTrue(analyze_structure(t)[0])
        self.assertFalse(analyze_structure(t,self_check=True)[0])
    def test_dates_filter(self):
        t='## 2026-11-10\n\n筆者は検証していない。\n\n## 2026-11-11\n\nAの報告によると成功した。'
        self.assertFalse(analyze_structure(t,entry_date='2026-11-11')[0])
    def test_source_offsets(self):
        t='Aの報告を紹介する。\r\nこれは筆者が再実行した結果ではない。[S1]'
        f=next(f for f in analyze_structure(t)[0] if 'S08' in f['data']['rules'])
        sp=next(x['span'] for x in f['data']['observations'] if x['rule']=='S08')
        self.assertEqual(sp['line'],2);self.assertEqual(sp['text'],t[sp['start']:sp['end']])
    def test_repetition_negative(self):
        fs,_=analyze_structure('この値は安全の根拠にはならない。[S1]\n\nこの試験は成功の確認にはならない。[S2]')
        self.assertTrue(any('S09' in f['data']['rules'] for f in fs))
    def test_negative_state_no_frame(self):
        fs,_=analyze_structure('GPUは未確認。\n\nCPU検証は失敗した。')
        self.assertFalse(any('S09' in f['data']['rules'] for f in fs))
    def test_single_constraint_no_repetition(self):
        self.assertFalse(any('S09' in f['data']['rules'] for f in analyze_structure('この設定は認証の代替にはならない。')[0]))
    def test_new_negative_closure_review(self):
        d=compare('Aの報告では検出1回だった。','Aの報告では検出1回だった。成功の証明にはならない。',source_name='a',final_name='b')
        self.assertTrue(any(f['rule']=='negative_closure_change' for f in d['findings']))
    def test_attribution_removal_not_restore(self):
        d=compare('Aの報告では検出1回だった。筆者が再実行した結果ではない。','Aの報告によると検出1回だった。',source_name='a',final_name='b')
        fs=[f for f in d['findings'] if f.get('before') and '筆者' in f['before']['text']]
        self.assertTrue(fs);self.assertEqual({f['rule'] for f in fs},{'attribution_reframe'})
    def test_profile_citations(self):
        a=closure_profile('値は根拠にはならない。');b=closure_profile('値は根拠にはならない。[S1]')
        self.assertEqual(a['negative_endings'],b['negative_endings']);self.assertEqual(a['sentences'],b['sentences'])

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.a,self.b,self.r=[self.root/x for x in ('a.md','b.md','record.json')]
        self.a.write_text('Aの報告では検出1回だった。筆者が再実行した結果ではない。',encoding='utf-8')
        self.b.write_bytes(self.a.read_bytes())
    def cli(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/check.py'),*map(str,args)],capture_output=True,text=True,encoding='utf-8')
    def run_check(self,*args):
        return self.cli('run','--source',self.a,'--final',self.b,'--record',self.r,'--json',*args)
    def verify(self):return self.cli('verify','--final',self.b,'--record',self.r,'--json')
    def test_unresolved_blocks_both(self):
        run=self.run_check();self.assertEqual(run.returncode,1,run.stderr)
        self.assertTrue(self.r.exists());v=self.verify();self.assertEqual(v.returncode,1)
        self.assertTrue(json.loads(v.stdout)['file_match']);self.assertFalse(json.loads(v.stdout)['editorial_ready'])
    def test_source_reframe_passes(self):
        self.b.write_text('Aの報告によると検出1回だった。',encoding='utf-8')
        self.assertEqual(self.run_check().returncode,0);self.assertEqual(self.verify().returncode,0)
    def test_failure_result_passes(self):
        self.b.write_text('筆者の追試ではエラーを再現できなかった。',encoding='utf-8')
        self.assertEqual(self.run_check().returncode,0)
    def test_requested_methods_with_record(self):
        req=self.root/'request.md';req.write_text('筆者自身が実施した試験と未実施の試験を明記してください。',encoding='utf-8')
        self.assertEqual(self.run_check('--author-method-request',req).returncode,0)
        self.assertEqual(self.verify().returncode,0)
        req.write_text('変更',encoding='utf-8');self.assertEqual(self.verify().returncode,1)
    def test_empty_request_rejected(self):
        req=self.root/'request.md';req.write_text('',encoding='utf-8')
        self.assertEqual(self.run_check('--author-method-request',req).returncode,2)
    def test_tamper_ready_recomputed(self):
        self.run_check();d=json.loads(self.r.read_text(encoding='utf-8'));d['editorial']['ready']=True
        self.r.write_text(json.dumps(d),encoding='utf-8');self.assertEqual(self.verify().returncode,1)
    def test_selfcheck_scope_consistent(self):
        self.b.write_text('「筆者が再実行した結果ではない」を説明する。',encoding='utf-8')
        self.assertEqual(self.run_check('--self-check').returncode,0);self.assertEqual(self.verify().returncode,0)
    def test_original_preserved(self):
        old=self.a.read_bytes();self.run_check();self.assertEqual(old,self.a.read_bytes())

if __name__=='__main__':unittest.main()
