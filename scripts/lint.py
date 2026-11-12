#!/usr/bin/env python3
"""日本語の文章から再読候補と観測値を表示する。"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys

sys.dont_write_bytecode = True
from pathlib import Path

from structure import analyze_structure, parse_markdown
from text_input import normalize, read_stdin, label, utf8_output

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "references" / "features.json"
CODE_FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
BLOCKQUOTE = re.compile(r"^\s*>+")
TABLE = re.compile(r"^\s*\|")
HORIZONTAL = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")
LIST = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__")
META_MENTION = re.compile(r'「[^」\n]+」|『[^』\n]+』|“[^”\n]+”|\"[^\"\n]+\"')


def load_features(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def feature_line(line: str, self_check: bool) -> str:
    if not self_check:
        return line
    return META_MENTION.sub("", line)


def prose_parts(text: str):
    from markdown_text import project, labels, prose_text
    doc = parse_markdown(text)
    refs = labels(text)
    lines, paragraphs, sentences = [], [], []
    for block in doc.paragraphs:
        start = doc.location(block.start, block.end)["line"]
        projected = project(text[block.start:block.end], reference_labels=refs)
        lines.extend((start + i, prose_text(line)) for i, line in enumerate(projected.splitlines()))
        paragraphs.append((start, prose_text(projected).replace("\n", " ")))
        for sentence in block.sentences:
            value = re.sub(r"\s+", " ", sentence.scan).strip().rstrip('。！？!?」』）)]”"').strip()
            if value:
                sentences.append((doc.location(sentence.start, sentence.end)["line"], value))
    return lines, paragraphs, sentences


def pct(x):
    return f"{x * 100:.1f}%"


def corpus_comparison(metrics, baselines):
    result = []
    for key, base in baselines.items():
        diffs = {}
        for metric, base_value in base.get("metrics", {}).items():
            if metric not in metrics:
                continue
            current = metrics[metric]
            diffs[metric] = {
                "current": current,
                "baseline": base_value,
                "ratio": round(current / base_value, 2) if base_value else None,
                "delta": round(current - base_value, 3),
            }
        result.append({"key": key, "label": base.get("label", key), "article_count": base.get("article_count"), "metrics": diffs})
    return result


def analyze(text: str, *, source: str = "<text>", features: dict | None = None,
            self_check: bool = False, kind: str = "article", history=None,
            entry_date: str | None = None) -> dict:
    """ファイル・文字列で共通の診断を行う。本文は呼出し元から渡す。"""
    if entry_date and kind != "progress-log":
        raise ValueError("--entry-date は --kind progress-log と組み合わせてください。")
    cfg = features if features is not None else load_features(FEATURES)
    original_text = text
    structure_findings, structure_summary = analyze_structure(
        original_text, source=source, self_check=self_check, kind=kind,
        history=list(history or []), entry_date=entry_date)
    text = (parse_markdown(original_text, source).select_entry(entry_date)
            if entry_date else original_text)
    lines, paragraphs, sents = prose_parts(text)
    feature_lines = [(no, feature_line(line, self_check)) for no, line in lines]
    feature_paragraphs = [(no, feature_line(paragraph, self_check)) for no, paragraph in paragraphs]
    prose = "\n".join(x for _, x in lines)
    chars = len(re.sub(r"\s+", "", prose))
    n_sent = max(len(sents), 1)
    commas = prose.count("、")
    all_lines = text.splitlines()
    list_lines = sum(bool(LIST.match(x)) for x in all_lines)
    nonblank = sum(bool(x.strip()) for x in all_lines) or 1
    headings = [(i + 1, x.strip()) for i, x in enumerate(all_lines) if HEADING.match(x)]
    summary_headings = [(no, h) for no, h in headings if re.search(r"まとめ|おわりに|終わりに|最後に", h)]
    bold = len(BOLD.findall(text))
    findings = list(structure_findings)

    def add(level, line, category, message, excerpt="", data=None):
        item = {
            "level": level,
            "line": line,
            "category": category,
            "message": message,
            "excerpt": excerpt.strip(),
        }
        if data is not None:
            item["data"] = data
        findings.append(item)

    # 1) Local lexical observations.
    for item in cfg.get("terms", []):
        rx = re.compile(item["pattern"])
        for no, line in feature_lines:
            for m in rx.finditer(line):
                corpus_note = ""
                if "pre_pct" in item and "recent_pct" in item:
                    corpus_note = f" [Qiita記事出現率 {item['pre_pct']}% → {item['recent_pct']}%]"
                add("REVIEW", no, item["category"], f"「{m.group(0)}」:{corpus_note} {item['note']}", line[:180])

    # 2) Article-local repetition. Useful even when the expression itself is normal Japanese.
    repeat_threshold = max(4, round(chars / 1500) + 2)
    for term in cfg.get("repeat_terms", []):
        loc = []
        for no, line in feature_lines:
            loc.extend([no] * line.count(term))
        if len(loc) >= repeat_threshold:
            unique_lines = list(dict.fromkeys(loc))
            add("REVIEW", loc[0], "repetition", f"「{term}」が{len(loc)}回あります (行: {', '.join(map(str, unique_lines[:12]))}{'…' if len(unique_lines) > 12 else ''})。必要な反復か通読してください。")
    for phrase in cfg.get("repeat_phrases", []):
        loc = []
        for no, line in feature_lines:
            loc.extend([no] * line.count(phrase))
        if len(loc) >= 3:
            add("REVIEW", loc[0], "phrase_repetition", f"「{phrase}」が{len(loc)}回あります。別の言い換えを探す前に、同じ説明構造自体が繰り返されていないか確認してください。", data={"lines": list(dict.fromkeys(loc))[:20]})

    # 3) Syntax and punctuation.
    for no, s in sents:
        c = s.count("、")
        if c >= 3:
            add("REVIEW", no, "punctuation", f"1文に読点が{c}個あります。読点を減らすこと自体ではなく、語順や文構造だけで読みやすくできるか確認してください。", s[:180])

    for item in cfg.get("negative_contrast", []):
        rx = re.compile(item["pattern"])
        for no, line in feature_lines:
            if rx.search(line):
                add("REVIEW", no, "negative_contrast", item["note"], line[:180])

    for item in cfg.get("cooccurrence_patterns", []):
        rx = re.compile(item["pattern"])
        for no, line in feature_lines:
            m = rx.search(line)
            if m:
                add("REVIEW", no, item["category"], item["note"], line[:180])

    # Count adjacent sentences, including endings outside the observed suffix list.
    # Headings and protected Markdown blocks end a run.
    run = []
    last_line = None
    ending_rx = re.compile(r"(?:でした|ました|ません|でしょう|であった|だった|である|です|ます|ない|なる|する|ある|いる|だ)$")
    for no, sentence in sents:
        if last_line is not None:
            gap = all_lines[last_line:no - 1]
            if any(HEADING.match(x) or CODE_FENCE.match(x) or BLOCKQUOTE.match(x)
                   or LIST.match(x) or TABLE.match(x) or HORIZONTAL.match(x) for x in gap):
                run = []
        ending = ending_rx.search(sentence)
        suffix = ending.group(0) if ending else None
        if not suffix:
            run = []
        elif run and run[-1][1] == suffix:
            run.append((no, suffix))
        else:
            run = [(no, suffix)]
        if len(run) == 4:
            add("REVIEW", run[0][0], "ending_run",
                f"同型の文末「{suffix}」が4文続きます。内容に合う流れか通読してください。")
        last_line = no

    # 4) Paragraph-level co-occurrence of different signal categories.
    para_cfg = cfg.get("paragraph_cooccurrence", {})
    min_categories = int(para_cfg.get("min_distinct_categories", 2))
    ignored = set(para_cfg.get("ignore_categories", []))
    for start, paragraph in feature_paragraphs:
        cats = set()
        matched = []
        for item in cfg.get("terms", []):
            m = re.search(item["pattern"], paragraph)
            if m and item["category"] not in ignored:
                cats.add(item["category"])
                matched.append(m.group(0))
        for item in cfg.get("negative_contrast", []):
            if re.search(item["pattern"], paragraph):
                cats.add("negative_contrast")
                matched.append("否定対比")
        for item in cfg.get("cooccurrence_patterns", []):
            m = re.search(item["pattern"], paragraph)
            if m:
                cats.add(item["category"])
                matched.append(m.group(0))
        if len(cats) >= min_categories:
            add(
                "REVIEW",
                start,
                "paragraph_cooccurrence",
                para_cfg.get("note", "異なる種類の特徴が同じ段落に重なっています。"),
                paragraph[:220],
                data={"categories": sorted(cats), "matches": matched[:8]},
            )

    lengths = [len(s) for _, s in sents]
    para_lengths = [len(re.sub(r"\s+", "", p)) for _, p in paragraphs]
    polite = sum(bool(re.search(r"(?:です|ます|でした|ました|ません(?:でした)?|でしょう|ましょう|ください)(?:か|よね|ね|よ|かね)?$", s)) for _, s in sents)
    plain = sum(bool(re.search(r"(?:だ|である|だった|であった)$", s)) for _, s in sents)
    negative = sum(bool(re.search(r"(?:ない|ません|ぬ|ず|ではない|ではありません)(?:$|[。！？!?])", s)) for _, s in sents)
    metrics = {
        "prose_chars": chars,
        "sentences": len(sents),
        "commas_per_sentence": round(commas / n_sent, 2),
        "list_line_ratio": round(list_lines / nonblank, 3),
        "bold_per_1000_chars": round((bold / chars * 1000) if chars else 0, 2),
        "sentence_length_mean": round(statistics.mean(lengths), 1) if lengths else 0,
        "sentence_length_cv": round(statistics.pstdev(lengths) / statistics.mean(lengths), 2) if len(lengths) > 1 and statistics.mean(lengths) else 0,
        "paragraphs": len(paragraphs),
        "paragraph_length_mean": round(statistics.mean(para_lengths), 1) if para_lengths else 0,
        "paragraph_length_cv": round(statistics.pstdev(para_lengths) / statistics.mean(para_lengths), 2) if len(para_lengths) > 1 and statistics.mean(para_lengths) else 0,
        "heading_count": len(headings),
        "headings_per_1000_chars": round((len(headings) / chars * 1000) if chars else 0, 2),
        "summary_heading_count": len(summary_headings),
        "polite_sentence_ratio": round(polite / len(sents), 3) if sents else 0,
        "plain_sentence_ratio": round(plain / len(sents), 3) if sents else 0,
        "mixed_style": bool(polite and plain),
        "negative_sentence_ratio": round(negative / len(sents), 3) if sents else 0,
    }
    comparisons = corpus_comparison(metrics, cfg.get("corpus_baselines", {}))

    if summary_headings:
        add("INFO", summary_headings[0][0], "summary_heading", f"『まとめ』系の見出しが{len(summary_headings)}件あります。役割が本文の再掲だけになっていないか確認してください。", summary_headings[0][1])

    return {"measurement_version": "prose-2", "polite_ending_version": "polite-2", "metrics": metrics,
            "corpus_comparison": comparisons, "structure": structure_summary,
            "findings": findings}


def render_report(result: dict, source: str) -> None:
    metrics = result["metrics"]
    findings = result["findings"]
    comparisons = result["corpus_comparison"]
    structure_findings = [f for f in findings if f["category"] == "structure"]
    chars = metrics["prose_chars"]
    print(f"kototogi-lint: {source}")
    if structure_findings:
        print(f"\n[structure {len(structure_findings)}箇所]")
        for f in structure_findings:
            print(f"\n{f['level']}  {','.join(f['data']['rules'])}  L{f['line']}")
            if f['data']['section']:
                print("  節: " + " / ".join(f['data']['section']))
            for c in f['data']['context'][:1]:
                print(f"  前後 L{c['line']}: {c['text'].strip()[:220]}")
            print(f"  再読: {f['excerpt'].strip()}")
            shown = set()
            for obs in f['data']['observations']:
                if obs['rule'] not in shown:
                    print(f"  {obs['rule']}: {obs['question']}")
                    shown.add(obs['rule'])
                if obs.get('observation'):
                    print(f"  観測: {obs['observation']}")
                related = [f"{Path(x['source']).name}:L{x['line']}" +
                           (f" ({x['date']})" if x.get('date') else "")
                           for x in obs['related']]
                if related:
                    print("  関連: " + ", ".join(related[:8]) +
                          (f" ほか{len(related)-8}箇所" if len(related) > 8 else ""))
    print("\n[INFO article style]")
    print(f"地の文 {chars}字 / 文 {metrics['sentences']} / 段落 {metrics['paragraphs']} / 読点 {metrics['commas_per_sentence']} / 文")
    print(f"箇条書き行率 {pct(metrics['list_line_ratio'])} / 太字 {metrics['bold_per_1000_chars']} / 1000字")
    print(f"平均文長 {metrics['sentence_length_mean']}字 / 文長CV {metrics['sentence_length_cv']}")
    print(f"平均段落長 {metrics['paragraph_length_mean']}字 / 段落長CV {metrics['paragraph_length_cv']}")
    print(f"見出し {metrics['heading_count']}件 ({metrics['headings_per_1000_chars']} / 1000字) / まとめ系 {metrics['summary_heading_count']}件")
    print(f"です・ます終止 {pct(metrics['polite_sentence_ratio'])} / だ・である終止 {pct(metrics['plain_sentence_ratio'])} / 文体混在 {'あり' if metrics['mixed_style'] else 'なし'}")
    print(f"否定終止 {pct(metrics['negative_sentence_ratio'])}")
    print("数値は文体を読み返す際の参考値です。")

    if comparisons:
        print("\n[INFO corpus comparison]")
        print("公開集計との概略比較です。prose-2は引用番号を除外し、段落内の改行をつなぎます。測定条件は references/corpus-analysis.md を参照。")
        metric_labels = {
            "prose_chars": "地の文",
            "commas_per_sentence": "読点/文",
            "bold_per_1000_chars": "太字/1000字",
            "sentence_length_mean": "平均文長",
            "sentence_length_cv": "文長CV",
            "polite_sentence_ratio": "です・ます終止率",
        }
        for base in comparisons:
            suffix = f" / n={base['article_count']}" if base.get("article_count") else ""
            print(f"  {base['label']}{suffix}")
            for metric, data in base["metrics"].items():
                cur, ref, r = data["current"], data["baseline"], data["ratio"]
                if metric == "polite_sentence_ratio":
                    cur_s, ref_s = pct(cur), pct(ref)
                else:
                    cur_s, ref_s = str(cur), str(ref)
                ratio_s = f"{r:.2f}x" if r is not None else "比較対象なし"
                print(f"    {metric_labels.get(metric, metric)}: {cur_s} / 基準 {ref_s} / {ratio_s}")

    review_findings = [f for f in findings if f["level"] == "REVIEW" and f["category"] != "structure"]
    info_findings = [f for f in findings if f["level"] == "INFO"]
    if info_findings:
        print(f"\n[INFO checks {len(info_findings)}件]")
        for f in info_findings:
            print(f"\nINFO  L{f['line']}  {f['category']}\n  {f['message']}")
            if f["excerpt"]:
                print(f"  > {f['excerpt']}")
    if not review_findings:
        if not structure_findings:
            print("\nREVIEW候補は見つかりませんでした。")
    else:
        print(f"\n[REVIEW {len(review_findings)}件]")
        order = {
            "low_information_modifier": 1,
            "vague_effect": 1,
            "repetition": 2,
            "phrase_repetition": 2,
            "punctuation": 3,
            "negative_contrast": 3,
            "ending_run": 3,
            "paragraph_cooccurrence": 4,
        }
        review_findings.sort(key=lambda f: (order.get(f["category"], 1), f["line"], f["category"]))
        for f in review_findings:
            print(f"\n{f['level']}  L{f['line']}  {f['category']}\n  {f['message']}")
            if f["excerpt"]:
                print(f"  > {f['excerpt']}")
            if f.get("data", {}).get("categories"):
                print(f"  categories: {', '.join(f['data']['categories'])}")
                print(f"  matches: {', '.join(f['data'].get('matches', []))}")


def main(argv=None):
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path, nargs="?", help="原稿のパス。- は標準入力。")
    inputs = ap.add_mutually_exclusive_group()
    inputs.add_argument("--text", help="本文そのものを渡す。")
    inputs.add_argument("--stdin", action="store_true", help="UTF-8の標準入力を読む。")
    ap.add_argument("--label", help="文字列入力の表示名。ファイルへのアクセスには使わない。")
    ap.add_argument("--features", type=Path, default=FEATURES)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--self-check", action="store_true",
                    help="規則文書用。引用符内の用語説明を隠して検査する。")
    ap.add_argument("--kind", choices=("article", "progress-log"), default="article")
    ap.add_argument("--history", type=Path, action="append", default=[], metavar="FILE")
    ap.add_argument("--entry-date", metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)
    if sum((args.file is not None, args.text is not None, args.stdin)) != 1:
        ap.error("ファイル、--text、--stdin のいずれか一つを指定してください。")
    is_file = args.file is not None and str(args.file) != "-"
    if args.label is not None and is_file:
        ap.error("--label は --text または標準入力と組み合わせてください。")
    try:
        if is_file:
            text, name = args.file.read_text(encoding="utf-8-sig"), str(args.file)
        elif args.text is not None:
            text, name = normalize(args.text), label(args.label, "<text>")
        else:
            text, name = read_stdin(), label(args.label, "<stdin>")
        history = []
        for path in args.history:
            if is_file and path.resolve() == args.file.resolve():
                raise ValueError("原稿と同じファイルを --history へ指定しています。")
            history.append((str(path), path.read_text(encoding="utf-8-sig")))
        result = analyze(text, source=name, features=load_features(args.features),
                         self_check=args.self_check, kind=args.kind,
                         history=history, entry_date=args.entry_date)
    except (OSError, UnicodeError, ValueError) as exc:
        ap.error(str(exc))
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_report(result, name)


if __name__ == "__main__":
    main()
