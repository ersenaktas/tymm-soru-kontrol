"""Structural validation helpers for the V7 four-section report contract."""
from __future__ import annotations

import re
import unicodedata


REPORT_TITLE = "# TYMM SORU KONTROL RAPORU"
MAIN_HEADINGS = (
    "## A — TYMM UYGUNLUĞU",
    "## B — BAĞLAM",
    "## C — SORU BAZLI DEĞERLENDİRME",
    "## D — SET DÜZEYİ DEĞERLENDİRME",
)
METADATA_LABELS = (
    "Ders / Sınıf",
    "Öğrenme Çıktısı",
    "Süreç Bileşeni / Beceri Kodu",
    "Kapsanan Sorular",
    "Genel Sonuç",
)
NEGATIVE_FIELDS = (
    "Kapsam",
    "Sonuç",
    "Hata",
    "Hata Açıklaması/Gerekçesi",
    "Kanıt",
    "Düzeltme (Revizyon) Önerisi",
)
UNREVIEWABLE_FIELDS = ("Kapsam", "Sonuç", "Sınırlılık", "Gerekli Bilgi")
FINDING_HEADING = re.compile(
    r"(?m)^####\s+(?P<code>[ABCD]\.(?:\d+(?:\.\d+)?|SET-\d+))\s+—\s+(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
QUESTION_HEADING = re.compile(r"(?mi)^###\s+Soru\s+(\d+)\s*$")
ANY_HEADING = re.compile(r"(?m)^#{1,6}\s+.+$")
LIST_PREFIX = r"(?:[-*+][ \t]+|\d+[.)][ \t]+)?"
EMPHASIS = r"(?:\*\*|__)"


def normalize(value: str) -> str:
    value = value.casefold().replace("\ufe0f", "").translate(str.maketrans("çğıöşü", "cgiosu"))
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def _label_value_match(value: str, label: str) -> re.Match[str] | None:
    """Read a V7 field even when NotebookLM adds a Markdown list marker.

    NotebookLM commonly emits ``- **Sonuç:** ...`` or ``**Sonuç**: ...``.
    Those are presentation-only variations and must not turn a completed
    assessment into a structural failure.
    """
    pattern = (
        rf"(?mi)^[ \t]*{LIST_PREFIX}(?:{EMPHASIS})?{re.escape(label)}[ \t]*"
        rf"(?:(?:{EMPHASIS})[ \t]*:|:[ \t]*(?:{EMPHASIS})?)[ \t]*(?P<value>\S.*?)[ \t]*$"
    )
    return re.search(pattern, value)


def _label_line_match(value: str, label: str) -> re.Match[str] | None:
    """Return a field line even when its value is intentionally blank."""
    pattern = (
        rf"(?mi)^[ \t]*{LIST_PREFIX}(?:{EMPHASIS})?{re.escape(label)}[ \t]*"
        rf"(?:(?:{EMPHASIS})[ \t]*:|:[ \t]*(?:{EMPHASIS})?)[ \t]*(?P<value>.*?)[ \t]*$"
    )
    return re.search(pattern, value)


def _fold_process_code_metadata(text: str) -> str:
    """Keep per-question process codes inside their single metadata row.

    NotebookLM sometimes writes an empty ``Süreç Bileşeni`` field followed by
    one bullet per question.  That is semantically useful but leaves the Word
    metadata cell empty and places the codes in an unlabeled block.  Folding
    only clearly numbered preamble bullets is a presentation-only change.
    """
    lines = text.splitlines()
    first_main = next(
        (index for index, line in enumerate(lines) if re.match(r"^[ \t]*#{1,6}[ \t]+A[ \t]*[—-]", line, re.IGNORECASE)),
        len(lines),
    )
    process_index = next(
        (
            index
            for index, line in enumerate(lines[:first_main])
            if re.match(
                r"^[ \t]*(?:\*\*|__)?Süreç Bileşeni / Beceri Kodu(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?[ \t]*$",
                line,
                re.IGNORECASE,
            )
        ),
        None,
    )
    if process_index is None:
        return text

    continuations: list[str] = []
    cursor = process_index + 1
    while cursor < first_main:
        match = re.match(
            r"^[ \t]*[-*+][ \t]+(?:\*\*)?(Soru[ \t]+\d+[ \t]*:[ \t]*.+?)(?:\*\*)?[ \t]*$",
            lines[cursor],
            re.IGNORECASE,
        )
        if not match:
            break
        continuations.append(match.group(1).strip().replace("**", "").replace("__", ""))
        cursor += 1
    if not continuations:
        return text

    lines[process_index] = "**Süreç Bileşeni / Beceri Kodu:** " + "; ".join(continuations)
    del lines[process_index + 1:cursor]
    return "\n".join(lines)


def _flatten_markdown_table_rows(text: str) -> str:
    """Remove Markdown table syntax while preserving every non-empty cell.

    V7 reports are intentionally table-free, but NotebookLM may quote a source
    table under ÖNCE/SONRA.  Rejecting the whole report loses an otherwise
    complete evaluation.  This deterministic formatting pass keeps the cell
    text in reading order and removes only the outer table delimiters and
    separator rows.
    """
    result: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(?P<indent>[ \t]*)\|(?P<body>.*)\|[ \t]*$", line)
        if not match:
            result.append(line)
            continue
        cells = [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", match.group("body"))]
        if cells and all(not cell or re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        readable = " | ".join(cell for cell in cells if cell)
        if readable:
            result.append(match.group("indent") + readable)
    return "\n".join(result)


def canonicalize_report_markdown(markdown: str) -> str:
    """Normalize harmless NotebookLM Markdown variations without editing findings.

    Only heading levels, heading punctuation, enclosing code fences and fixed
    no-finding sentences are normalized. Decisions, evidence and field text are
    preserved verbatim.
    """
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("\ufeff")
    lines = text.splitlines()
    if lines and re.fullmatch(r"\s*```(?:markdown|md)?\s*", lines[0], re.IGNORECASE):
        lines = lines[1:]
        if lines and re.fullmatch(r"\s*```\s*", lines[-1]):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    text = _fold_process_code_metadata(text)
    text = _flatten_markdown_table_rows(text)

    title = re.search(r"(?mi)^\s*#{1,6}\s*TYMM\s+SORU\s+KONTROL\s+RAPORU\s*$", text)
    if title:
        text = REPORT_TITLE + text[title.end():]

    main_specs = (
        ("A", r"TYMM\s+UYGUNLUĞU", MAIN_HEADINGS[0]),
        ("B", r"BAĞLAM", MAIN_HEADINGS[1]),
        ("C", r"SORU\s+BAZLI\s+DEĞERLENDİRME", MAIN_HEADINGS[2]),
        ("D", r"SET\s+DÜZEYİ\s+DEĞERLENDİRME", MAIN_HEADINGS[3]),
    )
    for letter, title_pattern, canonical in main_specs:
        pattern = (
            rf"(?mi)^\s*(?:#{{1,6}}\s*)?(?:{EMPHASIS})?\s*{letter}\s*"
            rf"(?:[-–—:]\s*)?{title_pattern}\s*(?:{EMPHASIS})?\s*$"
        )
        text = re.sub(pattern, canonical, text)

    text = re.sub(
        rf"(?mi)^\s*#{{1,6}}\s*(?:{EMPHASIS})?(Genel\s+TYMM\s+Değerlendirmesi.*?)"
        rf"(?:{EMPHASIS})?\s*$",
        lambda match: "### " + match.group(1).strip().strip("*_ "),
        text,
    )

    finding_pattern = re.compile(
        rf"(?mi)^\s*#{{1,6}}\s*(?:{EMPHASIS})?"
        r"(?P<code>[ABCD]\.(?:\d+(?:\.\d+)?|SET-\d+))\s*"
        rf"(?:[-–—:]\s*)?(?P<title>.+?)(?:{EMPHASIS})?\s*$"
    )

    def canonical_finding(match: re.Match[str]) -> str:
        title_value = match.group("title").strip().strip("*_ ")
        return f"#### {match.group('code').upper()} — {title_value}"

    text = finding_pattern.sub(canonical_finding, text)

    c_start = text.find(MAIN_HEADINGS[2])
    d_start = text.find(MAIN_HEADINGS[3], c_start + 1) if c_start >= 0 else -1
    if c_start >= 0 and d_start >= 0:
        before, c_body, after = text[:c_start], text[c_start:d_start], text[d_start:]
        question_pattern = re.compile(
            rf"(?mi)^\s*#{{1,6}}\s*(?:{EMPHASIS})?\s*"
            r"(?:(?P<first>\d+)\s*[.)-]?\s*Soru|Soru\s*(?P<second>\d+))"
            rf"(?:\s*[-–—:].*)?(?:{EMPHASIS})?\s*$"
        )

        def canonical_question(match: re.Match[str]) -> str:
            return f"### Soru {match.group('first') or match.group('second')}"

        text = before + question_pattern.sub(canonical_question, c_body) + after

    fixed_sentences = (
        "Raporlanacak sorun bulunmadı.",
        "Tek soru bulunduğu için set düzeyi değerlendirme uygulanamaz.",
    )
    for sentence in fixed_sentences:
        pattern = rf"(?mi)^\s*{LIST_PREFIX}(?:{EMPHASIS}|\*)?{re.escape(sentence)}(?:{EMPHASIS}|\*)?\s*$"
        text = re.sub(pattern, sentence, text)
    return text.strip()


def complete_blank_source_fields(markdown: str) -> str:
    """Represent unavailable source information as blank report fields.

    NotebookLM first gets every opportunity to produce the complete V7 report.
    At the final export boundary, absent descriptive values must not discard an
    otherwise valid assessment.  This pass inserts labels only; it never
    invents a value, decision, evidence or correction.  Structural elements
    and every finding's ``Sonuç`` remain mandatory.
    """
    value = canonicalize_report_markdown(markdown)
    a_start = value.find(MAIN_HEADINGS[0])
    if a_start >= 0:
        preamble = value[:a_start]
        blank_metadata = [
            label
            for label in METADATA_LABELS
            if label != "Genel Sonuç" and not _label_line_match(preamble, label)
        ]
        if blank_metadata:
            insertion = "\n".join(f"**{label}:**" for label in blank_metadata)
            value = value[:a_start].rstrip() + "\n" + insertion + "\n\n" + value[a_start:].lstrip()

    # Work backwards so inserting into one finding does not invalidate the
    # offsets of findings that precede it.
    for match in reversed(list(FINDING_HEADING.finditer(value))):
        next_heading = ANY_HEADING.search(value, match.end())
        end = next_heading.start() if next_heading else len(value)
        block = value[match.start():end]
        result_match = _label_value_match(block, "Sonuç")
        if not result_match:
            continue
        result = normalize(result_match.group("value"))
        if "incelenemedi" in result:
            required = UNREVIEWABLE_FIELDS
        elif "uygun degil" in result or "duzeltilmeli" in result:
            required = NEGATIVE_FIELDS
        else:
            continue
        blank_fields = [
            field for field in required if field != "Sonuç" and not _label_line_match(block, field)
        ]
        if not blank_fields:
            continue
        relative_insert = len(block.rstrip())
        for optional_label in ("ÖNCE", "SONRA"):
            optional_match = _label_line_match(block, optional_label)
            if optional_match:
                relative_insert = min(relative_insert, optional_match.start())
        insert_at = match.start() + relative_insert
        insertion = "\n".join(f"{field}:" for field in blank_fields)
        before = value[:insert_at].rstrip()
        after = value[insert_at:].lstrip("\n")
        value = before + "\n" + insertion + "\n" + after
    return value.strip()


def _section(markdown: str, index: int) -> str:
    start = markdown.find(MAIN_HEADINGS[index])
    if start < 0:
        return ""
    end = markdown.find(MAIN_HEADINGS[index + 1], start) if index + 1 < len(MAIN_HEADINGS) else len(markdown)
    return markdown[start:end].strip()


def _metadata_value(markdown: str, label: str) -> str:
    match = _label_value_match(markdown, label)
    return match.group("value").strip() if match else ""


def question_numbers(markdown: str) -> list[int]:
    """Return question units visible in the C section, in report order."""
    value = canonicalize_report_markdown(markdown)
    return [int(match.group(1)) for match in QUESTION_HEADING.finditer(_section(value, 2))]


def common_report_section(markdown: str) -> str:
    """Return the non-question A/B portion for compatibility with older callers."""
    value = canonicalize_report_markdown(markdown)
    return "\n\n".join(part for part in (_section(value, 0), _section(value, 1)) if part)


def question_report_section(markdown: str, number: int) -> str:
    """Extract one C-section question unit without changing its Markdown."""
    section = _section(canonicalize_report_markdown(markdown), 2)
    matches = list(QUESTION_HEADING.finditer(section))
    for index, match in enumerate(matches):
        if int(match.group(1)) != number:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        return section[match.start():end].strip()
    return ""


def _finding_blocks(markdown: str) -> list[tuple[str, str, str, int]]:
    matches = list(FINDING_HEADING.finditer(markdown))
    blocks: list[tuple[str, str, str, int]] = []
    for index, match in enumerate(matches):
        next_heading = ANY_HEADING.search(markdown, match.end())
        end = next_heading.start() if next_heading else len(markdown)
        if index + 1 < len(matches):
            end = min(end, matches[index + 1].start())
        blocks.append((match.group("code").upper(), match.group("title").strip(), markdown[match.start():end].strip(), match.start()))
    return blocks


def _has_field(block: str, label: str) -> bool:
    return _label_line_match(block, label) is not None


def report_detail_score(markdown: str) -> tuple[int, int, int, int]:
    """Prefer a valid, richer V7 report when a repair answer is available."""
    value = canonicalize_report_markdown(markdown)
    missing = missing_detailed_sections(value)
    findings = _finding_blocks(value)
    field_count = sum(sum(_has_field(block, field) for field in NEGATIVE_FIELDS + UNREVIEWABLE_FIELDS) for _, _, block, _ in findings)
    return (1 if not missing else 0, len(findings), field_count, len(value))


def merge_actionable_findings(primary: str, audit: str) -> str:
    """Choose the more complete V7 report; never splice findings across units."""
    return audit if report_detail_score(audit) > report_detail_score(primary) else primary


def _question_blocks(markdown: str) -> list[tuple[int, str]]:
    section = _section(markdown, 2)
    matches = list(QUESTION_HEADING.finditer(section))
    result: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        result.append((int(match.group(1)), section[match.start():end].strip()))
    return result


def missing_detailed_sections(markdown: str) -> list[str]:
    """Return concrete V7 contract gaps that make export unsafe."""
    value = canonicalize_report_markdown(markdown)
    missing: list[str] = []
    if not value:
        return ["Boş rapor"]

    first_line = value.splitlines()[0].strip()
    if first_line != REPORT_TITLE:
        missing.append("İlk satırda tam V7 rapor başlığı")
    h1_lines = re.findall(r"(?m)^#(?!#)\s+.+$", value)
    if h1_lines != [REPORT_TITLE]:
        missing.append("Tek bir birinci düzey başlık")

    positions: list[int] = []
    for heading in MAIN_HEADINGS:
        count = value.count(heading)
        if count != 1:
            missing.append(f"Ana bölüm: {heading[3:]}")
        positions.append(value.find(heading))
    if all(position >= 0 for position in positions) and positions != sorted(positions):
        missing.append("A, B, C ve D bölüm sırası")
    visible_h2 = re.findall(r"(?m)^##(?!#)\s+.+$", value)
    unexpected_h2 = [heading for heading in visible_h2 if heading not in MAIN_HEADINGS]
    if unexpected_h2:
        missing.append("V7 dışında ikinci düzey başlık")

    preamble_end = positions[0] if positions and positions[0] >= 0 else len(value)
    preamble = value[:preamble_end]
    for label in METADATA_LABELS:
        # Source documents may genuinely omit these descriptive values.  A
        # present blank label is therefore exportable, while Genel Sonuç is a
        # decision and must always contain a value.
        present = _label_line_match(preamble, label) is not None
        if not present or (label == "Genel Sonuç" and not _metadata_value(preamble, label)):
            missing.append(f"Üst bilgi: {label}")

    if re.search(r"(?m)^\s*\|.*\|\s*$", value):
        missing.append("Tablosuz Markdown çıktı")
    if re.search(r"(?i)\bKATMAN\b", value):
        missing.append("KATMAN ifadesinin kaldırılması")

    a_section = _section(value, 0)
    general_units = re.findall(r"(?mi)^###\s+Genel TYMM Değerlendirmesi(?:\s+—.*)?\s*$", a_section)
    if not general_units:
        missing.append("A bölümünde Genel TYMM Değerlendirmesi")

    questions = _question_blocks(value)
    numbers = [number for number, _ in questions]
    if not numbers:
        missing.append("C bölümünde Soru 1")
    else:
        if numbers != sorted(set(numbers)):
            missing.append("C bölümünde benzersiz ve sıralı soru başlıkları")
        if numbers != list(range(1, max(numbers) + 1)):
            missing.append("C bölümünde kesintisiz soru numaraları")
        expected = [int(number) for number in re.findall(r"(?i)Soru\s*(\d+)", _metadata_value(preamble, "Kapsanan Sorular"))]
        if expected and numbers != expected:
            missing.append("Kapsanan Sorular ile C soru başlıklarının tutarlılığı")
        for number, block in questions:
            has_finding = re.search(r"(?m)^####\s+C\.", block) is not None
            has_clear_note = "Raporlanacak sorun bulunmadı." in block
            if not has_finding and not has_clear_note:
                missing.append(f"Soru {number}: bulgu veya sorunsuzluk cümlesi")

    finding_blocks = _finding_blocks(value)
    for code, title, block, position in finding_blocks:
        clean_title = re.sub(r"\*\([^)]*\)\*\s*$", "", title).strip()
        if not clean_title.endswith("?"):
            missing.append(f"{code}: soru biçimindeki tam ölçüt adı")
        section_index = max((index for index, start in enumerate(positions) if start >= 0 and start < position), default=-1)
        expected_prefix = "ABCD"[section_index] if section_index >= 0 else ""
        if not expected_prefix or not code.startswith(expected_prefix + "."):
            missing.append(f"{code}: doğru ana bölüm")
        result_match = _label_value_match(block, "Sonuç")
        if not result_match:
            missing.append(f"{code}: Sonuç")
            continue
        result = normalize(result_match.group("value"))
        if "uygulanamaz" in result or ("uygun" in result and "uygun degil" not in result):
            missing.append(f"{code}: raporlanmaması gereken uygun/uygulanamaz sonuç")
            continue
        if "incelenemedi" in result:
            absent = [field for field in UNREVIEWABLE_FIELDS if not _has_field(block, field)]
        elif "uygun degil" in result or "duzeltilmeli" in result:
            absent = [field for field in NEGATIVE_FIELDS if not _has_field(block, field)]
        else:
            absent = ["geçerli raporlanabilir Sonuç"]
        if absent:
            missing.append(f"{code}: " + ", ".join(absent))

    for main_index, prefix in enumerate("ABCD"):
        section = _section(value, main_index)
        for code in re.findall(r"(?mi)^####\s+([ABCD]\.(?:\d+(?:\.\d+)?|SET-\d+))\b", section):
            if not code.upper().startswith(prefix + "."):
                missing.append(f"{code.upper()}: {prefix} bölümünde yanlış kod")

    d_section = _section(value, 3)
    d_body = d_section[len(MAIN_HEADINGS[3]):].strip() if d_section else ""
    if len(numbers) == 1:
        expected_sentence = "Tek soru bulunduğu için set düzeyi değerlendirme uygulanamaz."
        if d_body != expected_sentence:
            missing.append("Tek soruda D bölümünün uygulama cümlesi")
    elif len(numbers) >= 2:
        has_d_finding = re.search(r"(?m)^####\s+D\.", d_body) is not None
        if not has_d_finding and d_body != "Raporlanacak sorun bulunmadı.":
            missing.append("D bölümünde set bulgusu veya sorunsuzluk cümlesi")

    return list(dict.fromkeys(missing))
