"""日本語の段落構成から再読候補を抽出する。入力は読取り専用。"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
import re
from typing import Iterable

from markdown_text import blank, project, labels, sentence_ranges
from conditions import repeated_condition
from editorial import author_disclaimer, NEGATIVE_CLOSURE
from attribution import exposition_candidate

VERSION = "structure-4"
RULES = {
    "S10": ("source-name-preface", "資料で確認した仕様や動作なら参照を保って内容から述べる。個別の結果・見解・紹介する手順は発信元を示す。"),
    "S08": ("author-nonparticipation", "情報に合う出典表示へ整えて筆者の断りを削る。仕様説明は参照を添え、個別の結果や手順は報告元を示す。"),
    "S09": ("negative-interpretation-run", "否定の結びが重なっています。観測結果・対象範囲・必要な対応から直接書けるか確認する。"),
    "S01": ("terminal-qualification-run", "段落末の注意が続いています。条件を該当する主張へ添えられるか確認する。"),
    "S02": ("abstract-boundary", "対象名・集計単位・現在の状態で直接説明できるか確認する。"),
    "S03": ("repeated-qualification", "同じ注意の候補です。共通の説明と当日の条件を確認する。"),
    "S04": ("editorial-process-in-body", "編集作業の報告か、読者に必要な検証方法かを確認する。"),
    "S05": ("corrective-frame-run", "対比が続いています。訂正する必要のある誤解や選択肢があるか確認する。"),
    "S07": ("restated-condition", "直前にある条件や出典で伝わるか。新しい情報があればその部分を残す。"),
    "S06": ("ornamental-close", "評価や展望で閉じる文が重なっています。直前の説明で終えられるか確認する。"),
}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
DATE = re.compile(r"(?<!\d)(20\d{2})(?:年|[-/])(\d{1,2})(?:月|[-/])(\d{1,2})(?:日)?(?!\d)")
INLINE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
MENTION = re.compile(r'「[^」]*」|『[^』]*』|“[^”]*”|"[^"\n]*"')
SCOPE = re.compile(r"集計|件数|機能数|完成率|速度|倍率|実績|成果|実採用|検証|試験|成功|未完|未実装|未着手|公開|統合|確認|検出|再現|受け止め|報告|範囲|全体|母数|合計|対象外|対象数|GPU実行|host実行|読[むみ]|解釈|捉え|みな[すし]|見な[すし]")
BOUNDARY = re.compile(
    r"(?:区別|区分)(?:する|すべき|して(?:いる|読む|扱う|考える|受け止め(?:たい|る)))"
    r"|分け(?:る|て(?:考える|読む|記録する|保持する|扱う|追う|いる))"
    r"|別(?:に|の(?:範囲|対象|事象)として|枠で)(?:扱[うい]|評価|追[うい])"
    r"|(?:換算|加算)(?:しない|しません|できない|できません)"
    r"|(?:置き換え|数え|含め)(?:ない|ません)"
    r"|とは(?:別(?:である|です)|しない)|として(?:数えない|扱わない)"
)
QUALIFIED_END = re.compile(
    r"(?:未確認|未実施|未完|未確定|未算出|不明|対象外|範囲外|検証待ち|確認待ち)"
    r"(?:である|です|だ|だった|となる|となった|とする|のまま|としている|として残す)?[。！？!?]*$"
    r"|(?:検証|確認|受入れ|比較|対応|範囲|課題|残件|不具合|制約).{0,45}(?:残る|残っている|必要(?:だ|です|である|になる|がある)?)[。！？!?]*$"
    r"|(?:全.{0,12}(?:対応|完了)|全体完成率).{0,20}(?:ではない|とはしない)[。！？!?]*$"
)
NO_EXTRA = re.compile(
    r"(?:日次集計|集計用|集計のため|今回の集計|日報).{0,100}"
    r"(?:追加.{0,12}(?:テスト|試験|test|build)|テストを追加実行|試験を追加実行)"
    r".{0,30}(?:ない|ません|0件|ゼロ)", re.I
)
EDITORIAL = re.compile(
    r"(?:今回|集計|日報|この記事|本稿|本記事).{0,120}"
    r"(?:[\w./-]+\.mdだけ.{0,12}(?:更新|変更)|追加伝達|返答待ち|担当への割込み)"
    r"|[\w./-]+\.mdだけ.{0,12}(?:更新|変更).{0,80}(?:追加伝達|活動中|source|担当)"
    r"|(?:追加伝達|活動中のsource|開発担当への割込み).{0,45}(?:作らない|変更しない|追加しない)", re.I
)
CORRECTION = re.compile(r"単なる[^。！？!?]{1,70}(?:ではなく|でなく)|というより|(?:ではなく|ではありませんが)")
ORNAMENT = re.compile(
    r"(?:非常に|極めて|圧倒的に|本質的に|決定的に|最も).{0,20}(?:重要|効果的|画期的)"
    r"|(?:大きな一歩|重要な一歩|新たな可能性|可能性が広が|さらなる発展|今後の発展|未来を切り開|真価を発揮)"
    r"|(?:ぜひ|是非).{0,35}(?:試し|活用|挑戦|取り入れ)"
    r"|(?:鍵となる|鍵です|期待が高ま|期待されます)[。！？!?]*$"
)


def view(text: str, *, self_check: bool = False, mask_code: bool = True) -> str:
    out = project(text, mask_code=mask_code)
    if self_check:
        out = MENTION.sub(lambda m: blank(m[0]), out)
    return out


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).strip("`*_ ")


@dataclass
class Sentence:
    start: int
    end: int
    scan: str
    visible: str
    paragraph: int
    index: int
    terminal: bool = False
    section_terminal: bool = False
    entry_terminal: bool = False
    document_terminal: bool = False


@dataclass
class Block:
    kind: str
    start: int
    end: int
    section: tuple[str, ...]
    entry: str | None
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class Document:
    text: str
    source: str
    blocks: list[Block]
    line_starts: list[int]
    entries: dict[str, list[tuple[int, int]]]

    @property
    def paragraphs(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "prose"]

    def location(self, start: int, end: int) -> dict:
        line_index = bisect_right(self.line_starts, start) - 1
        end_index = bisect_right(self.line_starts, max(start, end - 1)) - 1
        return {"source": self.source, "start": start, "end": end,
                "line": line_index + 1, "end_line": end_index + 1,
                "column": start - self.line_starts[line_index] + 1,
                "text": self.text[start:end]}

    def select_entry(self, selected: str) -> str:
        spans = self.entries.get(selected, [])
        if len(spans) != 1:
            raise ValueError(f"日付見出し {selected} は一意に選べません（{len(spans)}件）。")
        start, end = spans[0]
        return blank(self.text[:start]) + self.text[start:end] + blank(self.text[end:])


def parse_markdown(text: str, source: str = "<input>", *, self_check: bool = False) -> Document:
    """Read prose with source offsets. Soft line breaks stay inside a sentence."""
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    rows = []
    pos = 0
    for line in text.splitlines(keepends=True):
        rows.append((pos, pos + len(line), line.rstrip("\r\n")))
        pos += len(line)
    blocks: list[Block] = []
    headings: list[tuple[int, str]] = []
    entry = None
    entry_level = None
    entry_start = 0
    entries: dict[str, list[tuple[int, int]]] = defaultdict(list)
    current = None
    fence = None
    html_block = None
    comment = False
    i = 0

    def flush():
        nonlocal current
        if current is not None:
            blocks.append(current)
            current = None

    def append(kind, start, end):
        nonlocal current
        if current is not None and current.kind == kind:
            current.end = end
        else:
            flush()
            current = Block(kind, start, end, tuple(h[1] for h in headings), entry)

    while i < len(rows):
        start, end, raw = rows[i]
        clean = raw.strip()
        # YAML front matter belongs to the document's metadata.
        if i == 0 and clean == "---":
            close = next((j for j in range(1, len(rows)) if rows[j][2].strip() in ("---", "...")), None)
            if close is not None:
                i = close + 1
                continue
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", raw):
                fence = None
            i += 1
            continue
        match = FENCE.match(raw)
        if match:
            flush()
            fence = (match[1][0], len(match[1]))
            i += 1
            continue
        if html_block:
            if re.search(r"</" + html_block + r"\s*>", raw, re.I):
                html_block = None
            i += 1
            continue
        match = re.match(r"\s*<(pre|script|style)\b", raw, re.I)
        if match:
            flush()
            if not re.search(r"</" + match[1] + r"\s*>", raw, re.I):
                html_block = match[1]
            i += 1
            continue
        if comment:
            if "-->" in raw:
                comment = False
            i += 1
            continue
        if clean.startswith("<!--"):
            flush()
            comment = "-->" not in raw
            i += 1
            continue
        if not clean:
            flush()
            i += 1
            continue
        hm = ATX.match(raw)
        setext = i + 1 < len(rows) and bool(SETEXT.match(rows[i + 1][2])) and not re.match(r"\s*(?:>|\||[-*+]\s)", raw)
        if hm or setext:
            flush()
            if hm:
                level, title = len(hm[1]), hm[2]
            else:
                level, title = (1 if rows[i + 1][2].lstrip().startswith("=") else 2), clean
                end = rows[i + 1][1]
            if entry is not None and entry_level is not None and level <= entry_level:
                entries[entry].append((entry_start, start))
                entry, entry_level = None, None
            dm = DATE.search(title)
            if dm:
                try:
                    new_entry = date(*(int(x) for x in dm.groups())).isoformat()
                except ValueError:
                    new_entry = None
                if new_entry:
                    if entry is not None:
                        entries[entry].append((entry_start, start))
                    entry, entry_level, entry_start = new_entry, level, start
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            blocks.append(Block("heading", start, end, tuple(h[1] for h in headings), entry))
            i += 2 if not hm else 1
            continue
        if re.match(r"^(?: {4}|\t)", raw):
            flush()
            i += 1
            continue
        if re.match(r"\s*(?:[-*_]\s*){3,}$", raw) or clean.startswith(":::"):
            flush()
            i += 1
            continue
        if re.match(r"\s*>+", raw):
            kind = "quote"
        elif re.match(r"\s*\|", raw) or ("|" in raw and i + 1 < len(rows) and re.match(r"\s*\|?\s*:?-{3,}.*\|", rows[i + 1][2])):
            kind = "table"
        elif current is not None and current.kind == "table" and "|" in raw:
            kind = "table"
        elif re.match(r"\s*(?:[-*+]\s+|\d+[.)]\s+)", raw):
            kind = "list"
        elif re.match(r"\s*\[[^]]+\]:\s*\S", raw):
            flush()
            i += 1
            continue
        else:
            kind = "prose"
        append(kind, start, end)
        i += 1
    flush()
    if entry is not None:
        entries[entry].append((entry_start, len(text)))
    doc = Document(text, source, blocks, line_starts, dict(entries))
    refs = labels(text)
    for bi, block in enumerate(blocks):
        if block.kind != "prose":
            continue
        raw = text[block.start:block.end]
        scan = project(raw, reference_labels=refs)
        if self_check:
            scan = MENTION.sub(lambda m: blank(m[0]), scan)
        visible = project(raw, mask_code=False, reference_labels=refs)
        for a, b in sentence_ranges(raw, scan, visible):
            block.sentences.append(Sentence(block.start + a, block.start + b,
                scan[a:b], visible[a:b], bi, len(block.sentences)))
        if block.sentences:
            block.sentences[-1].terminal = True
    prose = [b for b in blocks if b.kind == "prose" and b.sentences]
    for j, b in enumerate(prose):
        nxt = prose[j + 1] if j + 1 < len(prose) else None
        b.sentences[-1].section_terminal = nxt is None or nxt.section != b.section or nxt.entry != b.entry
        b.sentences[-1].entry_terminal = nxt is None or nxt.entry != b.entry
    if prose:
        prose[-1].sentences[-1].document_terminal = True
    return doc


def is_boundary(s: Sentence) -> bool:
    return bool(BOUNDARY.search(compact(s.scan)) and SCOPE.search(compact(s.visible)))


def is_editorial(s: Sentence) -> bool:
    return bool(NO_EXTRA.search(compact(s.scan)) or EDITORIAL.search(compact(s.scan)))


def is_qualified(s: Sentence) -> bool:
    t = compact(s.scan).rstrip('」』）)]”"')
    meta = (re.search(r"結果|所要時間|状況|情報|範囲|影響|根拠|観測|成功|解決|欠陥|検出|実行", t)
            and re.search(r"(?:意味ではない|結果ではない|情報ではない|ものではない|にはならない|同じではない|についての記述だ)[。！？!?]*$", t))
    return is_boundary(s) or bool(QUALIFIED_END.search(t)) or bool(NO_EXTRA.search(t)) or bool(meta)


def common_family(s: Sentence) -> str | None:
    t = compact(s.scan)
    if NO_EXTRA.search(t):
        return "集計用の追加実行"
    if re.search(r"(?:件数|統合数|PR数|統合件数)", t) and re.search(r"機能数|完成率|速度倍率|新機能|新規実装数", t) and is_qualified(s):
        return "統合件数の単位"
    if re.search(r"全体.{0,12}(?:母数|完成率)|全体完成率", t) and re.search(r"不明|未確定|未算出|算出.{0,10}(?:ない|ません)", t):
        return "全体完成率の母数"
    return None


def _normalize(s: Sentence) -> str:
    return re.sub(r"[\s。、，,「」『』`*_]", "", s.visible)


def _same_notice(a: Sentence, b: Sentence) -> bool:
    x, y = _normalize(a), _normalize(b)
    if x == y:
        return True
    # Preserve numeric IDs, versions, quantities and explicit test scopes.
    if re.findall(r"[A-Za-z]+\d+|\d+(?:\.\d+)*", x) != re.findall(r"[A-Za-z]+\d+|\d+(?:\.\d+)*", y):
        return False
    for key in ("GPU", "host", "native", "Metal", "Vulkan", "失敗", "成功"):
        if (key in x) != (key in y):
            return False
    return min(len(x), len(y)) >= 12 and SequenceMatcher(None, x, y, autojunk=False).ratio() >= .90


def analyze_structure(text: str, *, source: str = "<input>", self_check: bool = False,
                      kind: str = "article", history: Iterable[tuple[str, str]] = (),
                      entry_date: str | None = None) -> tuple[list[dict], dict]:
    doc = parse_markdown(text, source, self_check=self_check)
    if entry_date:
        doc.select_entry(entry_date)  # Validate uniqueness before any findings.
    active = [(i, b) for i, b in enumerate(doc.blocks)
              if b.kind == "prose" and b.sentences and (entry_date is None or b.entry == entry_date)]
    grouped: dict[int, dict] = {}

    def evidence(d: Document, s: Sentence) -> dict:
        b = d.blocks[s.paragraph]
        pos = d.location(s.start, s.end)
        pos.update({"date": b.entry, "section": list(b.section),
                    "paragraph_index": s.paragraph, "sentence_index": s.index,
                    "paragraph_terminal": s.terminal, "section_terminal": s.section_terminal,
                    "entry_terminal": s.entry_terminal, "document_terminal": s.document_terminal})
        return pos

    def emit(rule: str, s: Sentence, related: list[tuple[Document, Sentence]], note: str = ""):
        b = doc.blocks[s.paragraph]
        if s.paragraph not in grouped:
            loc = doc.location(s.start, s.end)
            contexts = []
            if s.index:
                contexts.append(evidence(doc, b.sentences[s.index - 1]))
            else:
                for prev in reversed(doc.blocks[:s.paragraph]):
                    if prev.entry != b.entry:
                        break
                    if prev.kind in ("prose", "table", "list", "heading"):
                        contexts.append(doc.location(prev.start, prev.end))
                    if len(contexts) >= 2:
                        break
            grouped[s.paragraph] = {"level": "REVIEW", "line": loc["line"],
                "category": "structure", "message": "", "excerpt": loc["text"],
                "data": {"rules": [], "date": b.entry, "section": list(b.section),
                         "paragraph": doc.location(b.start, b.end), "context": contexts,
                         "observations": []}}
        f = grouped[s.paragraph]
        if rule not in f["data"]["rules"]:
            f["data"]["rules"].append(rule)
        obs = {"rule": rule, "name": RULES[rule][0], "question": RULES[rule][1],
               "span": evidence(doc, s), "related": [evidence(d, x) for d, x in related]}
        if note:
            obs["observation"] = note
        f["data"]["observations"].append(obs)
        f["message"] = " / ".join(RULES[r][1] for r in sorted(f["data"]["rules"]))

    # S08 has an editing action, not a discretionary style hint.
    for _, b in active:
        for s in b.sentences:
            if author_disclaimer(s.scan):
                emit("S08", s, [(doc, x) for x in b.sentences[:s.index][-3:]])
                f = grouped[s.paragraph]
                f["level"] = "REWRITE"
                f["data"]["required_action"] = "attribute_source"

    # S10 offers a wording review; it does not decide whether a claim is true.
    for _, b in active:
        context = ' '.join(s.scan for s in b.sentences)
        for s in b.sentences:
            candidate = exposition_candidate(s.scan, context=context)
            if candidate:
                emit("S10", s, [], "説明用の資料名: " + candidate['label'])
                grouped[s.paragraph]['data']['observations'][-1]['source_role'] = candidate

    # S07: compare a restatement with the preceding three sentences in the same paragraph.
    for _, b in active:
        for idx, s in enumerate(b.sentences):
            previous = b.sentences[max(0, idx - 3):idx]
            scans = [x.scan for x in previous]
            current = s.scan
            clause = re.search(r"、(?=(?:これ(?:ら)?|この(?:所要時間|時間|数値|値|結果))は)", current)
            if clause:
                scans.append(current[:clause.end()])
                current = current[clause.end():]
            match = repeated_condition(scans, current)
            if match:
                emit("S07", s, [(doc, x) for x in previous],
                     "条件の言い直し候補: " + match['family'] + " / 根拠: " + match['evidence'])
                grouped[s.paragraph]['data']['observations'][-1]['condition_overlap'] = match

    # S02/S04: lexical triggers plus a reporting/editorial context.
    for _, b in active:
        for s in b.sentences:
            if is_boundary(s):
                emit("S02", s, [])
            if is_editorial(s):
                emit("S04", s, [])

    def clusters(items, minimum: int, max_span: int = 5):
        """Merge overlapping qualifying windows; emit each run once."""
        runs = []
        for j, (pi, s) in enumerate(items):
            window = [(k, t) for k, t in items[j:] if k - pi < max_span]
            if len(window) < minimum:
                continue
            indices = {(x.start, x.end) for _, x in window}
            if runs and indices & {(x.start, x.end) for _, x in runs[-1]}:
                known = {(x.start, x.end) for _, x in runs[-1]}
                runs[-1].extend((k, t) for k, t in window if (t.start, t.end) not in known)
            else:
                runs.append(window)
        return runs

    by_entry = defaultdict(list)
    for bi, b in active:
        by_entry[b.entry].append((bi, b))
    for _, pars in by_entry.items():
        negative_frames = [(pi, s) for pi, (_, b) in enumerate(pars) for s in b.sentences
                           if NEGATIVE_CLOSURE.search(compact(s.scan))]
        for run in clusters(negative_frames, 2):
            emit("S09", run[0][1], [(doc, s) for _, s in run[1:]],
                 "近接5段落に解釈を否定する結びが2文以上。各文が加える情報を読む。")
        terminals = [(pi, b.sentences[-1]) for pi, (_, b) in enumerate(pars)
                     if len(b.sentences) >= 2 and is_qualified(b.sentences[-1])]
        for run in clusters(terminals, 3):
            emit("S01", run[0][1], [(doc, s) for _, s in run[1:]],
                 "近接5段落中3段落以上の末尾に注意の候補")
        corrections = [(pi, s) for pi, (_, b) in enumerate(pars) for s in b.sentences
                       if CORRECTION.search(compact(s.scan))]
        for run in clusters(corrections, 3):
            emit("S05", run[0][1], [(doc, s) for _, s in run[1:]])
        ornaments = [(pi, b.sentences[-1]) for pi, (_, b) in enumerate(pars)
                     if ORNAMENT.search(compact(b.sentences[-1].scan))]
        for run in clusters(ornaments, 2):
            ends = [s for _, s in run if s.section_terminal]
            sections = {doc.blocks[s.paragraph].section for s in ends}
            if len(sections) >= 2 or len(run) >= 3:
                emit("S06", run[0][1], [(doc, s) for _, s in run[1:]])
        # S03 within an entry: conservative textual similarity, bounded context.
        notices = [(pi, s) for pi, (_, b) in enumerate(pars) for s in b.sentences if is_qualified(s)]
        covered = set()
        for j, (pi, s) in enumerate(notices):
            if s.start in covered:
                continue
            others = [t for qi, t in notices[j + 1:] if qi - pi <= 8 and _same_notice(s, t)]
            if others:
                covered.update(t.start for t in others)
                emit("S03", s, [(doc, t) for t in others], "近接した注意の表現が類似")

    # The ordinary article route never loads or compares previous entries.
    history_comparisons = 0
    if kind == "progress-log" or history:
        prior_docs = [parse_markdown(t, name, self_check=self_check) for name, t in history]
        pools = [doc] + prior_docs
        common = defaultdict(list)
        for d in pools:
            for b in d.paragraphs:
                for s in b.sentences:
                    family = common_family(s)
                    if family:
                        common[family].append((d, s))
        for family, members in common.items():
            current = [(d, s) for d, s in members if d is doc and
                       (entry_date is None or d.blocks[s.paragraph].entry == entry_date)]
            if not current:
                continue
            d0, anchor = current[0]
            entry0 = doc.blocks[anchor.paragraph].entry
            related = [(d, s) for d, s in members if
                       d.source != source or d.blocks[s.paragraph].entry != entry0]
            if related:
                history_comparisons += 1
                emit("S03", anchor, related, f"日付・履歴をまたぐ共通説明の候補: {family}")

    findings = sorted(grouped.values(), key=lambda f: f["line"])
    for f in findings:
        f["data"]["rules"].sort()
    summary = {"version": VERSION, "kind": kind, "entry_date": entry_date,
               "paragraphs_checked": len(active), "groups": len(findings),
               "history_groups": history_comparisons,
               "rule_counts": {r: sum(r in f["data"]["rules"] for f in findings) for r in RULES}}
    return findings, summary
