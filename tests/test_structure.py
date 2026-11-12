"""構成診断とCLIの回帰テスト。例文は試験用の入力。"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import structure


def rules(text, **kwargs):
    found, _ = structure.analyze_structure(text, **kwargs)
    return {r for f in found for r in f["data"]["rules"]}


def para(text):
    return structure.parse_markdown(text).paragraphs


class ParserTests(unittest.TestCase):
    def test_soft_break_is_not_sentence(self):
        p = para("条件を\n結果に添える。次の文です。")
        self.assertEqual(len(p[0].sentences), 2)
        self.assertIn("\n", p[0].sentences[0].scan)

    def test_crlf_source_offsets(self):
        raw = "# 見出し\r\n\r\n説明です。\r\n次の説明です。\r\n"
        d = structure.parse_markdown(raw)
        s = d.paragraphs[0].sentences[1]
        loc = d.location(s.start, s.end)
        self.assertEqual(loc["line"], 4)
        self.assertEqual(loc["text"], "次の説明です。")

    def test_two_sentences_same_line_columns(self):
        d = structure.parse_markdown("前です。後です。")
        s = d.paragraphs[0].sentences[1]
        self.assertEqual(d.location(s.start, s.end)["column"], 5)

    def test_fence_length(self):
        raw = "````text\n```\n実績とは別に扱う。\n````\n\n本文。"
        self.assertEqual(len(para(raw)), 1)
        self.assertEqual(para(raw)[0].sentences[0].scan, "本文。")

    def test_fence_type(self):
        raw = "~~~text\n```\n実績とは別に扱う。\n~~~\n\n本文。"
        self.assertNotIn("S02", rules(raw))

    def test_unclosed_fence(self):
        self.assertEqual(para("```text\n実績とは別に扱う。"), [])

    def test_indented_code(self):
        self.assertEqual(para("    実績とは別に扱う。\n\n本文。")[0].sentences[0].scan, "本文。")

    def test_quote_not_rewritten(self):
        self.assertEqual(rules("> 実績とは別に扱う。\n\n本文。"), set())

    def test_list_and_table_are_context(self):
        d = structure.parse_markdown("| 項目 | 件数 |\n|---|---|\n| PR | 2 |\n\n統合件数は機能数へ換算しない。")
        self.assertEqual(d.blocks[0].kind, "table")
        f, _ = structure.analyze_structure(d.text)
        self.assertIn("| 項目 |", f[0]["data"]["context"][0]["text"])

    def test_list_not_prose(self):
        self.assertEqual(rules("- 実績とは別に扱う。\n- 別の項目。"), set())

    def test_setext_heading(self):
        d = structure.parse_markdown("名称\n===\n\n本文。")
        self.assertEqual(d.paragraphs[0].section, ("名称",))

    def test_frontmatter(self):
        self.assertEqual(rules("---\ndescription: 実績とは別に扱う。\n---\n本文。"), set())

    def test_comment(self):
        self.assertEqual(rules("<!--\n実績とは別に扱う。\n-->\n本文。"), set())

    def test_inline_comment(self):
        self.assertEqual(rules("内容。<!-- 実績とは別に扱う。 -->"), set())

    def test_html_pre(self):
        self.assertEqual(rules("<pre>\n実績とは別に扱う。\n</pre>\n本文。"), set())

    def test_inline_code_protected(self):
        self.assertEqual(rules("`実績とは別に扱う。`という文字列。"), set())

    def test_inline_identifier_kept_in_context(self):
        f, _ = structure.analyze_structure("`PR123`の件数は機能数へ換算しない。")
        self.assertIn("`PR123`", f[0]["excerpt"])
        self.assertIn("PR123", f[0]["data"]["observations"][0]["span"]["text"])

    def test_url_masked_offsets_preserved(self):
        raw = "[記録](https://example.org/実績とは別に扱う)を見る。"
        self.assertEqual(len(structure.view(raw)), len(raw))
        self.assertNotIn("S02", rules(raw))

    def test_json_spans_roundtrip(self):
        raw = "# 節\n\n`PR1`の成果です。\n機能数へ換算しない。\n"
        fs, _ = structure.analyze_structure(raw)
        for f in fs:
            for o in f["data"]["observations"]:
                s = o["span"]
                self.assertEqual(s["text"], raw[s["start"]:s["end"]])

    def test_terminal_flags(self):
        d = structure.parse_markdown("## 節1\n\n第一文。第二文。\n\n## 節2\n\n第三文。")
        a, b = d.paragraphs
        self.assertFalse(a.sentences[0].terminal)
        self.assertTrue(a.sentences[1].section_terminal)
        self.assertFalse(a.sentences[1].document_terminal)
        self.assertTrue(b.sentences[-1].document_terminal)

    def test_empty(self):
        self.assertEqual(rules(""), set())


class EntryTests(unittest.TestCase):
    text = "# 記録\n\n## 2026年11月7日\n\n本文A。\n\n## 2026-11-06\n\n本文B。"

    def test_entry_formats(self):
        d = structure.parse_markdown(self.text)
        self.assertEqual(set(d.entries), {"2026-11-07", "2026-11-06"})

    def test_slash_date(self):
        self.assertIn("2026-11-07", structure.parse_markdown("## 2026/11/7\n本文。").entries)

    def test_selection_preserves_lines(self):
        d = structure.parse_markdown(self.text)
        t = d.select_entry("2026-11-06")
        self.assertEqual(len(t), len(self.text))
        self.assertEqual(t.count("\n"), self.text.count("\n"))
        self.assertIn("本文B", t)
        self.assertNotIn("本文A", t)

    def test_duplicate_date_rejected(self):
        d = structure.parse_markdown("## 2026-11-07\n本文。\n## 2026-11-07\n本文。")
        with self.assertRaises(ValueError):
            d.select_entry("2026-11-07")

    def test_missing_date_rejected(self):
        with self.assertRaises(ValueError):
            structure.parse_markdown(self.text).select_entry("2026-11-08")

    def test_impossible_date(self):
        self.assertFalse(structure.parse_markdown("## 2026-02-30\n本文。").entries)

    def test_prose_date_not_entry(self):
        self.assertFalse(structure.parse_markdown("2026-11-07の検証結果。\n").entries)

    def test_section_keeps_entry(self):
        d = structure.parse_markdown("## 2026-11-07\n\n### 検証\n\n本文。")
        self.assertEqual(d.paragraphs[0].entry, "2026-11-07")

    def test_higher_heading_ends_entry(self):
        d = structure.parse_markdown("## 2026-11-07\n\n本文。\n\n# 共通\n\n共通説明。")
        self.assertIsNone(d.paragraphs[1].entry)


class RuleTests(unittest.TestCase):
    def test_S02_status(self):
        self.assertIn("S02", rules("並行化の提案はqueuedで、実採用とは分ける。"))

    def test_S02_count_unit(self):
        self.assertIn("S02", rules("統合件数は機能数へ換算しない。"))

    def test_S02_separate_treatment(self):
        self.assertIn("S02", rules("成果の統合と起動経路の適合は別に扱う。"))

    def test_S02_technical_discrimination_preserved(self):
        self.assertNotIn("S02", rules("商品コードの大文字と小文字を区別している。"))

    def test_S02_data_partition_preserved(self):
        self.assertNotIn("S02", rules("入力データを二つに分ける。"))

    def test_S01_three_in_five(self):
        text = "host試験は成功した。GPU検証は未確認。\n\n描画を追加した。native比較は未実施。\n\n読取りに対応した。全形式の確認は必要である。"
        self.assertIn("S01", rules(text))

    def test_S01_only_two(self):
        self.assertNotIn("S01", rules("試験は成功した。GPUは未確認。\n\n実装を追加した。native比較は未実施。"))

    def test_S01_single_sentence_paragraphs(self):
        self.assertNotIn("S01", rules("GPUは未確認。\n\nnative比較は未実施。\n\n全体は未完。"))

    def test_S01_one_group_for_overlapping_windows(self):
        text = "\n\n".join(f"項目{i}を追加した。GPU試験は未確認。" for i in range(7))
        f, _ = structure.analyze_structure(text)
        self.assertEqual(sum("S01" in x['data']['rules'] for x in f), 1)

    def test_S01_no_cross_date_default(self):
        text = "\n\n".join(f"## 2026-11-0{i}\n\n実装を追加した。GPUは未確認。" for i in range(1, 4))
        self.assertNotIn("S01", rules(text))

    def test_S03_near_duplicate(self):
        self.assertIn("S03", rules("GPU検証は未確認である。\n\n実装した。\n\nGPU検証は未確認である。"))

    def test_S03_different_numbers(self):
        self.assertNotIn("S03", rules("PR1のGPU検証は未確認である。\n\nPR2のGPU検証は未確認である。"))

    def test_S03_different_scopes(self):
        self.assertNotIn("S03", rules("host検証は未確認である。\n\nGPU検証は未確認である。"))

    def test_S03_cross_dates_opt_in(self):
        t = "## 2026-11-07\n日次集計のための追加テストは行っていない。\n\n## 2026-11-06\n日次集計のための追加テストは行っていない。"
        self.assertNotIn("S03", rules(t))
        self.assertIn("S03", rules(t, kind="progress-log"))

    def test_S03_history_explicit(self):
        t = "日次集計のための追加テストは行っていない。"
        self.assertIn("S03", rules(t, history=[("old.md", t)]))

    def test_S03_preserve_daily_test_status(self):
        t = "## 2026-11-07\nGPU試験は未確認。\n\n## 2026-11-06\nGPU試験は未確認。"
        self.assertNotIn("S03", rules(t, kind="progress-log"))

    def test_S04_editorial(self):
        self.assertIn("S04", rules("DAILY-PROGRESS.mdだけを更新し、活動中のsourceへの追加伝達を作らない。"))

    def test_S04_additional_tests(self):
        self.assertIn("S04", rules("日次集計のための追加テストは行っていない。"))

    def test_S04_test_failure_is_substantive(self):
        self.assertNotIn("S04", rules("GPU試験はassertionで失敗した。"))

    def test_S04_tutorial(self):
        self.assertNotIn("S04", rules("README.mdを更新する手順を示します。"))

    def test_S05_repeated_frames(self):
        t = "単なる短縮ではなく圧縮です。\n\nこれは削除ではなく再配置です。\n\n改善というより整理です。"
        self.assertIn("S05", rules(t))

    def test_S05_single_correction(self):
        self.assertNotIn("S05", rules("これは削除ではなく再配置です。"))

    def test_S06_repeated_section_closes(self):
        t = "## 一\n実装した。非常に重要です。\n\n## 二\n測定した。これは大きな一歩です。"
        self.assertIn("S06", rules(t))

    def test_S06_single_important(self):
        self.assertNotIn("S06", rules("この順序が重要です。"))

    def test_S06_measurement(self):
        self.assertNotIn("S06", rules("## 一\n最も速い設定は20msだった。\n\n## 二\n最も遅い設定は50msだった。"))

    def test_S02_S04_grouped_by_paragraph(self):
        f, _ = structure.analyze_structure("統合件数は機能数へ換算しない。日次集計のための追加テストは行っていない。")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]['data']['rules'], ["S02", "S04"])

    def test_self_check_only_masks_mentions(self):
        t = "「実績とは別に扱う」という文を点検する。"
        self.assertIn("S02", rules(t))
        self.assertNotIn("S02", rules(t, self_check=True))

    def test_self_check_does_not_disable_structure(self):
        self.assertIn("S02", rules("統合件数は機能数へ換算しない。", self_check=True))

class CliTests(unittest.TestCase):
    def run_cli(self, text, *args):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.md"
            p.write_text(text, encoding="utf-8")
            before = hashlib.sha256(p.read_bytes()).hexdigest()
            r = subprocess.run([sys.executable, str(ROOT/'scripts/lint.py'), str(p), *args],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(before, hashlib.sha256(p.read_bytes()).hexdigest())
            return r

    def test_json(self):
        r = self.run_cli("統合件数は機能数へ換算しない。", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['structure']['rule_counts']['S02'], 1)

    def test_normal_text(self):
        r = self.run_cli("統合件数は機能数へ換算しない。")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("REVIEW  S02", r.stdout)

    def test_utf8_bom(self):
        r = self.run_cli("\ufeff# 見出し\n\n本文。", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / 'missing.md')
            r = subprocess.run([sys.executable, str(ROOT/'scripts/lint.py'), missing], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_entry_requires_progress(self):
        r = self.run_cli("本文。", "--entry-date", "2026-11-07")
        self.assertEqual(r.returncode, 2)

    def test_selected_entry_only(self):
        text = "## 2026-11-07\n本文。\n\n## 2026-11-06\n地味に効く。"
        r = self.run_cli(text, "--kind", "progress-log", "--entry-date", "2026-11-07", "--json")
        d = json.loads(r.stdout)
        self.assertEqual(d['metrics']['sentences'], 1)
        self.assertFalse(d['findings'])

    def test_wrong_entry_is_error(self):
        r = self.run_cli("## 2026-11-07\n本文。", "--kind", "progress-log", "--entry-date", "2026-11-08")
        self.assertEqual(r.returncode, 2)

    def test_unknown_history_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli("本文。", "--history", str(Path(tmp) / "missing.md"))
        self.assertEqual(r.returncode, 2)

    def test_endings_do_not_skip_other_sentences(self):
        r = self.run_cli("登録する。ここで待つ。確認する。結果を見る。保存する。先へ進む。終了する。", "--json")
        self.assertNotIn("ending_run", {f['category'] for f in json.loads(r.stdout)['findings']})

    def test_adjacent_endings_are_detected(self):
        r = self.run_cli("登録します。確認します。保存します。終了します。", "--json")
        self.assertIn("ending_run", {f['category'] for f in json.loads(r.stdout)['findings']})

    def test_heading_breaks_ending_run(self):
        r = self.run_cli("## 一\n登録します。確認します。\n\n## 二\n保存します。終了します。", "--json")
        self.assertNotIn("ending_run", {f['category'] for f in json.loads(r.stdout)['findings']})

    def test_legacy_terms_remain(self):
        r = self.run_cli("地味に効く。", "--json")
        categories = {f['category'] for f in json.loads(r.stdout)['findings']}
        self.assertIn("low_information_modifier", categories)
        self.assertIn("vague_effect", categories)


if __name__ == '__main__':
    unittest.main()
