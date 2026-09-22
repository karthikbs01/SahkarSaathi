"""Conservative, offline structure-first extraction; never writes to data/raw.

Usage: python scripts/extract_corpus.py [--source SOURCE_ID] [--force]
Only one PDF's layout/text is held in memory. Per-source JSONL and manifests are
atomic checkpoints keyed by PDF, metadata, validation reports, parser and PyMuPDF
version. Aggregation streams checkpoints in CSV order. A source-specific run
refreshes that source and aggregates only current checkpoints for other sources.
Missing/stale checkpoints are reported as ERROR, never silently included.

Parents normally contain the full provision. Above 900 words, safely partitioned
parents contain just introductory context; text_scope='context_only' identifies
these records, whose complete text is reconstructed from parent then children.
Child metadata is inherited, and parent_id supplies any shared introductory text.
No paraphrasing, legal inference, OCR, translation, or network calls are used.
Warnings are preserved in chunk_stats.csv; uncertain material is retained.
"""

import argparse
import contextlib
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import hashlib
import json
import io
import inspect
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import tempfile
import unicodedata

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
REPORT_FIELDS = "source_id filename pages raw_chars cleaned_chars parent_records child_records total_records sections_detected rules_detected clauses_detected headings_detected tables_detected forms_detected warnings status".split()
STATS_FIELDS = "chunk_id source_id record_type retrieval_status document_type jurisdiction word_count char_count page_start page_end section subsection rule subrule clause heading topics warning".split()
META_FIELDS = "source_id title jurisdiction document_type authority priority source_url relative_path retrieved_date".split()
STRUCT_FIELDS = "part chapter section subsection rule subrule clause subclause heading subheading affected_provision amendment_action form_number scheme_name".split()
TOPICS = {
    "membership": r"\bmembership\b|admission of (?:a |the )?members?|who may become a member", "registration": r"\bregistration\b",
    "management": r"\bmanag(?:ement|ing|er)\b", "governance": r"\bgovernance\b|\bboard of directors\b",
    "elections": r"\belect(?:ion|ions|oral)\b", "meetings": r"\bmeetings?\b",
    "loans": r"\b(?:loans?|borrow(?:ing|er|ers)?)\b", "deposits": r"\bdeposits?\b",
    "financial_literacy": r"\bfinancial literacy\b", "pacs": r"\bPACS\b|primary agricultural credit societ",
    "pacs_services": r"\bPACS\b.{0,80}\bservices?\b|\bservices?\b.{0,80}\bPACS\b",
    "computerization": r"\bcomputeri[sz](?:ation|ed|ing)\b",
    "crop_insurance": r"\bcrop insurance\b", "pmfby": r"\bPMFBY\b|pradhan mantri fasal bima",
    "eligibility": r"\beligib(?:le|ility)\b", "premium": r"\bpremiums?\b",
    "crop_loss": r"\bcrop (?:loss|damage)|\bloss of crops?\b",
    "claim": r"\bclaim(?:s)?\s+(?:procedure|settlement|payment|processing|assessment|calculation|intimation)|\b(?:submit|file|settle|pay|process|assess)(?:ed|ing|ment)?\s+(?:the |a |insurance )?claims?\b", "reporting": r"\breport(?:ing|ed)\b|\bintimat(?:ion|e)\b",
    "documents": r"\bdocuments?\b|\bdocumentary\b", "timeline": r"\b(?:within \w+ days?|time[- ]limit|deadline|timeline|days from|hours of)\b",
    "grievance": r"\bgrievances?\b", "complaint": r"\bcomplain(?:t|ts|ant|ants)\b",
    "ombudsman": r"\bombudsman\b", "appeal": r"\bappeal(?:s|late)?\b",
    "form_vi": r"\bform\s*[-–]?\s*VI\b", "form_vii": r"\bform\s*[-–]?\s*VII\b",
    "registrar": r"\bregistrar\b", "multistate": r"\bmulti[- ]state\b",
    "state_law": r"\b(?:Karnataka|Maharashtra)\b.{0,100}\b(?:Act|Rules)\b",
    "byelaws": r"\bbye[- ]?laws?\b",
}
TOPIC_RE = {key: re.compile(pattern, re.I | re.S) for key, pattern in TOPICS.items()}
NUMBER = r"\d{1,3}(?:-?[A-Z])?"
PROVISION = re.compile(r"^(?:\d{1,3}\s*\[\s*|\[\s*)?(?P<num>" + NUMBER + r")[.．]\s*(?P<body>.*)$")
DECIMAL = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,3}){1,4})\.?\s+(?P<body>\S.*)$")
SUB = re.compile(r"^\s*(?:\d+\[)?\((?P<num>\d{1,3}|[a-z]{1,4}|[ivxlcdm]+)\)\s*")
SPECIAL = re.compile(r"^(?:THE\s+)?(?:(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+)?(?P<kind>SCHEDULE|ANNEXURE|ANNEX|APPENDIX|FORM)\b\s*(?:[-–:]\s*)?[\"'‘’“”]?(?P<num>[IVXLCDM]+(?:-[A-Z0-9]+)?|\d+[A-Z]?(?:-[A-Z0-9]+)?|[A-Z](?:-[A-Z0-9]+)?)?\b", re.I)
QUALIFIER = re.compile(r"^(?:Provided\b|Explanation\b|Exception\b|Illustration\b|Note\s*[:.\d])", re.I)


@dataclass
class Line:
    text: str
    page: int
    box: tuple
    size: float
    bold: bool = False
    block: int = 0
    table: bool = False
    warnings: set = field(default_factory=set)


@dataclass
class Unit:
    meta: dict
    lines: list = field(default_factory=list)
    warnings: set = field(default_factory=set)
    kind: str = "context"
    identifier: str = ""


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_line(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def words(text):
    return len(text.split())


def slug(value):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def text_of(lines):
    """Reflow within paragraphs, preserving numbering, table rows and hyphens.

    Soft-hyphen line breaks and the requested co-/operative layout case are
    repaired. Other visible hyphens are retained when joining wrapped words.
    """
    output = []
    previous = None
    for line in lines:
        text = "\n".join(norm(row) for row in line.text.splitlines()) if line.table else norm(line.text)
        if not text:
            continue
        new_block = previous is None or line.table or previous.table or bool(SUB.match(text))
        new_block |= bool(QUALIFIER.match(text)) or (previous is not None and line.page == previous.page and line.block != previous.block)
        if output and not new_block:
            if output[-1].endswith("\u00ad") and re.match(r"^[a-z]", text):
                output[-1] = output[-1][:-1] + text
            elif re.search(r"\bco-$", output[-1]) and re.match(r"^operative\b", text):
                output[-1] = output[-1][:-1] + text
            elif re.search(r"[A-Za-z]-$", output[-1]) and re.match(r"^[a-z]", text):
                output[-1] += text
            else:
                output[-1] += " " + text
        else:
            output.append(text)
        previous = line
    return "\n\n".join(output).strip()


def page_lines(page, page_number):
    result = []
    for block_index, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(span["text"] for span in spans).strip()
            if not text:
                continue
            weight = sum(len(span["text"]) for span in spans) or 1
            result.append(Line(text, page_number, tuple(line["bbox"]),
                               sum(span["size"] * len(span["text"]) for span in spans) / weight,
                               sum(len(span["text"]) for span in spans if span["flags"] & 16) / weight >= .55,
                               block_index))
    # Isolated section numbers and marginal titles often share a baseline.
    result.sort(key=lambda line: (round(line.box[1], 1), line.box[0]))
    joined = []
    for line in result:
        if joined:
            prev = joined[-1]
            if abs(prev.box[3] - line.box[3]) < 2.0 and 0 <= line.box[0] - prev.box[2] < 36 and (re.fullmatch(r"[\dA-Z.\[\]-]+", prev.text) or prev.bold == line.bold):
                prev.text += " " + line.text
                prev.box = (prev.box[0], min(prev.box[1], line.box[1]), line.box[2], max(prev.box[3], line.box[3]))
                prev.bold |= line.bold
                continue
        joined.append(line)
    return joined


def table_lines(page, lines):
    """Use grid text only when its token multiset exactly preserves source cells.
    Otherwise keep original text and flag it. Even grids need visual review for
    merged cells, column reading order and units, so every detected table is flagged.
    """
    count = 0
    warnings = set()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            tables = page.find_tables().tables
        for table in tables:
            if table.row_count < 2 or table.col_count < 2:
                continue
            count += 1
            rect = pymupdf.Rect(table.bbox)
            affected = [line for line in lines if rect.contains(pymupdf.Rect(line.box))]
            for line in affected:
                line.warnings.add("TABLE_REVIEW")
                line.table = True
            cells = table.extract()
            row_texts = [" | ".join(norm(cell or "") for cell in row) for row in cells]
            tokens = lambda text: Counter(re.findall(r"\w+|[^\w\s|]", text))
            if affected and tokens(" ".join(l.text for l in affected)) == tokens(" ".join(row_texts)):
                selected = {id(line) for line in affected}
                first = min(affected, key=lambda line: (line.box[1], line.box[0]))
                clean = all(cell is not None for row in cells for cell in row) and all(len(row) == table.col_count for row in cells)
                grid = replace(first, text="\n".join(row_texts), box=tuple(table.bbox), table=True, warnings=set() if clean else {"TABLE_REVIEW"})
                lines = [line for line in lines if id(line) not in selected] + [grid]
                if not clean:
                    warnings.add("TABLE_REVIEW")
            else:
                warnings.add("TABLE_REVIEW")
        # Borderless tables may have no drawing grid. Repeated three-column
        # alignments are uncertain: retain original lines and flag them instead
        # of inventing cells. Two-column legal margin headings are excluded.
        if not count:
            rows = defaultdict(list)
            for line in lines:
                rows[round(line.box[3] / 4)].append(line)
            candidates = [row for row in rows.values() if len(row) >= 3 and all(words(line.text) <= 12 for line in row)]
            alignments = Counter(round(line.box[0] / 12) for row in candidates for line in row)
            repeated_columns = {x for x, occurrences in alignments.items() if occurrences >= 3}
            if len(candidates) >= 3 and len(repeated_columns) >= 3:
                count = 1
                warnings.add("TABLE_REVIEW")
                for row in candidates:
                    for line in row:
                        line.table = True
                        line.warnings.add("TABLE_REVIEW")
        lines.sort(key=lambda line: (line.box[1], line.box[0]))
    except Exception:
        warnings.add("TABLE_DETECTION_FAILED")
        for line in lines:
            line.warnings.add("TABLE_DETECTION_FAILED")
    return lines, count, warnings


def cached_pages(path, source):
    """Cache PDF layout independently of chunking; hold one source at a time."""
    folder = OUT / "checkpoints" / "layout"
    folder.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256((digest(path) + pymupdf.__version__ + inspect.getsource(page_lines) + inspect.getsource(table_lines)).encode()).hexdigest()
    cache = folder / (source["source_id"] + ".jsonl")
    manifest = folder / (source["source_id"] + ".json")
    if cache.exists() and manifest.exists():
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        if meta.get("signature") == signature and meta.get("sha256") == digest(cache):
            with cache.open(encoding="utf-8") as stream:
                for row in stream:
                    page = json.loads(row)
                    page["lines"] = [Line(**{**line, "box": tuple(line["box"]), "warnings": set(line["warnings"])}) for line in page["lines"]]
                    yield page
            return
    temporary = cache.with_suffix(".jsonl.tmp")
    with pymupdf.open(path) as doc, temporary.open("w", encoding="utf-8", newline="\n") as stream:
        if not doc.is_pdf or doc.needs_pass or not doc.page_count:
            raise ValueError("Unreadable, encrypted, or empty PDF")
        for page_number, page in enumerate(doc, 1):
            lines, table_count, warnings = table_lines(page, page_lines(page, page_number))
            row = dict(height=page.rect.height, width=page.rect.width, raw_chars=len(page.get_text("text")), tables=table_count,
                       warnings=sorted(warnings), lines=[{**asdict(line), "warnings": sorted(line.warnings)} for line in lines])
            stream.write(json_line(row))
            row["lines"] = lines
            yield row
    temporary.replace(cache)
    manifest.write_text(json_line(dict(signature=signature, sha256=digest(cache))), encoding="utf-8")


def extract_layout(path, source):
    pages, heights, widths = [], [], []
    raw_chars = tables = 0
    warnings = set()
    for page in cached_pages(path, source):
        raw_chars += page["raw_chars"]
        pages.append(page["lines"])
        heights.append(page["height"])
        widths.append(page["width"])
        tables += page["tables"]
        warnings.update(page["warnings"])
    frequency = defaultdict(set)
    for index, lines in enumerate(pages):
        for line in lines:
            if line.box[3] < heights[index] * .1 or line.box[1] > heights[index] * .9:
                frequency[norm(line.text).casefold()].add(index)
    # Repetition alone is insufficient: require short furniture and recognizable
    # titles/publication/watermark markers in the outer margin.
    recurring = set()
    for text, occurrences in frequency.items():
        recognizable = (text == source["title"].casefold() or re.search(r"gazette|government of|ministry of|department of|downloaded|www\.|https?://|operational guidelines|co-operative societies act|cooperative societies act|co-operative societies rules", text))
        if len(occurrences) >= max(3, len(pages) * .3) and len(text) <= 170 and recognizable:
            recurring.add(text)
    cleaned, excluded_toc = [], 0
    in_toc = False
    for index, lines in enumerate(pages):
        filtered = []
        for line in lines:
            margin = line.box[3] < heights[index] * .1 or line.box[1] > heights[index] * .9
            page_number = bool(re.fullmatch(r"(?:page\s*)?[-–—]?\s*\d{1,4}\s*[-–—]?", line.text, re.I))
            if margin and ((page_number and line.box[0] > widths[index] * .3) or norm(line.text).casefold() in recurring):
                continue
            filtered.append(line)
        texts = [line.text for line in filtered]
        toc_title = any(re.fullmatch(r"(?:table of )?contents|index|arrangement of (?:sections|rules)", text, re.I) for text in texts)
        leaders = sum(bool(re.search(r"\.{3,}\s*\d+\s*$", text)) for text in texts)
        numbered = sum(bool(PROVISION.match(text)) for text in texts)
        long_lines = sum(words(text) >= 16 for text in texts)
        short_ratio = sum(words(text) <= 12 for text in texts) / max(1, len(texts))
        is_toc = ((toc_title or in_toc) and short_ratio > .65 and numbered >= 4 and long_lines <= 5) or (leaders >= 5 and short_ratio > .8 and long_lines <= 3)
        if is_toc:
            excluded_toc += 1
            in_toc = True
            continue
        in_toc = toc_title and short_ratio > .85
        if toc_title:
            warnings.add("TOC_REVIEW")
            for line in filtered:
                line.warnings.add("TOC_REVIEW")
        cleaned.extend(filtered)
    scripts = Counter()
    for line in cleaned:
        for character in line.text:
            if character.isalpha():
                name = unicodedata.name(character, "")
                for script in ("LATIN", "DEVANAGARI", "KANNADA"):
                    if name.startswith(script):
                        scripts[script] += 1
        if "\ufffd" in line.text or re.search(r"\(cid:\d+\)", line.text):
            line.warnings.add("EXTRACTION_QUALITY_REVIEW")
            warnings.add("EXTRACTION_QUALITY_REVIEW")
    if scripts["LATIN"] > 200 and (scripts["DEVANAGARI"] > 100 or scripts["KANNADA"] > 100):
        warnings.add("BILINGUAL_REVIEW")
    character_total = sum(len(line.text) for line in cleaned)
    legacy_characters = sum(sum("\u00a1" <= char <= "\u00ff" for char in line.text) for line in cleaned)
    if legacy_characters > max(100, character_total * .03):
        warnings.add("LEGACY_FONT_ENCODING_REVIEW")
        for line in cleaned:
            if sum("\u00a1" <= char <= "\u00ff" for char in line.text) > len(line.text) * .03:
                line.warnings.add("LEGACY_FONT_ENCODING_REVIEW")
    return cleaned, dict(pages=len(pages), raw_chars=raw_chars,
                        cleaned_chars=len(text_of(cleaned)), tables_detected=tables,
                        toc_pages_excluded=excluded_toc), warnings


def heading_text(body):
    # A dash separating heading from operative text is strong legal evidence.
    heading = re.split(r"[.—–]\s*[-—–]|[—–]|\.\s*\(1\)", body, maxsplit=1)[0].strip(" .-—–")
    if words(heading) > 35 or len(heading) > 250:
        return None
    return heading or None


def detect_structure(lines, index, source, body_size, active_kind):
    line = lines[index]
    text = norm(line.text)
    if line.table or line.size < body_size * .82:
        return None
    if re.fullmatch(r"STATEMENT\s+OF\s+OBJECTS\s+AND\s+REASONS[. ]*", text, re.I):
        return "background", "", text
    if active_kind == "background" and line.bold and re.fullmatch(r"[IVXLCDM]+", text):
        return "background", text, text
    if source["document_type"] in {"amendment", "amendment_rules"} and re.fullmatch(r"MINISTRY OF COOPERATION", text, re.I):
        return "background", "ENGLISH_NOTICE", text
    for kind in ("chapter", "part"):
        match = re.match(r"^" + kind + r"\s*[-–:]?\s*([IVXLCDM]+|\d+)(?:\b|[-–])", text, re.I)
        if match and words(text) < 25:
            return kind, match.group(1), text
    match = SPECIAL.match(text)
    valid_form = not match or match["kind"].lower() != "form" or (match["num"] and re.match(r"^(?:FORM|Form)\b", text))
    if match and valid_form and (line.bold or words(text) <= 12 or text.upper() == text) and not re.search(r"\b(?:shall|must|may|under|referred|prescribed|specified)\b", text, re.I):
        return match["kind"].lower(), match["num"] or "", text
    hindi_form = re.match(r"^(?:प्ररूप|प्ररुप|प्रपत्र|प्रारूप)\s*[-–:]?\s*([IVXLCDM]+|[\d०-९]+)\b", text)
    if hindi_form and words(text) <= 12:
        return "form", hindi_form[1], text
    dtype = source["document_type"]
    if dtype == "scheme_guideline":
        bare = re.match(r"^(\d{1,2})\s+([A-Z].*)$", text)
        if bare and line.bold and words(bare[2]) <= 10 and not re.search(r"[.;,]$|\b(?:shall|must|should|will|may)\b", bare[2], re.I):
            return "heading", bare[1], bare[2]
        match = DECIMAL.match(text)
        if match and (line.bold or words(text) <= 18) and not QUALIFIER.match(text):
            # Decimal numbering identifies an official block even when it has
            # no heading. Do not promote its opening body sentence to a title.
            title = match["body"] if (line.bold and words(match["body"]) <= 8 and not re.search(r"[.,;]$|\b(?:shall|must|should|will|may|are|is|were|has|have)\b|\b(?:in|for|of|the|to|and|or|with|from|by|under|a|an)$", match["body"], re.I)) else None
            return "heading", match["num"], title
    # Numbered items inside a prescribed form/schedule are not Act sections.
    if active_kind in {"form", "schedule", "annexure", "annex", "appendix"}:
        if line.bold and words(text) <= 18 and not SUB.match(text) and not PROVISION.match(text):
            return None
        return None
    match = PROVISION.match(text)
    if not match:
        explicit = re.match(r"^(?:Section|Rule)\s+(" + NUMBER + r")\s*[.:-]?\s+(.+)$", text, re.I)
        if explicit and line.bold and words(text) <= 25:
            match = {"num": explicit.group(1), "body": explicit.group(2)}
    if match:
        body = match["body"].strip()
        if not body and index + 1 < len(lines):
            following = lines[index + 1]
            if following.bold and following.page - line.page <= 1 and not PROVISION.match(following.text):
                body = norm(following.text)
        title = heading_text(body)
        initial = next((character for character in body if character.isalpha()), "")
        capitalized = initial.isupper() or (initial and not unicodedata.name(initial, "").startswith("LATIN"))
        strong_heading = bool(title and capitalized and (line.bold or re.search(r"[—–]|\.\s*[-—–]|\.\s*\(1\)", body)))
        # Some Acts put the heading in a side column. An explicit (1) after a
        # bold section number still confidently identifies the section itself.
        if dtype in {"act", "rules"} and line.bold and re.match(r"^\(1\)", body):
            strong_heading = True
            title = None
        if dtype in {"amendment", "amendment_rules"}:
            amendment_heading = bool(re.match(r"^(?:Amendment|Insertion|Substitution|Omission|Renumbering|Short title|Commencement)\b|^(?:In|For|After|Before)\s+(?:the\b|said\b|rule\b|section\b)", body, re.I))
            amendment_heading |= bool(re.match(r"^मूल\s", body))
            amendment_heading |= match["num"] == "1" and bool(re.match(r"^\(1\)|संक्षिप्त", body))
            strong_heading = amendment_heading
            if re.search(r"[\u0900-\u097f]", body) or not title or re.search(r"\bshall\b", title, re.I):
                title = None
        if dtype in {"act", "rules", "amendment", "amendment_rules", "model_byelaws"} and strong_heading:
            kind = {"act": "section", "rules": "rule", "amendment": "item", "amendment_rules": "item", "model_byelaws": "clause"}[dtype]
            return kind, match["num"], title
        if dtype == "scheme_guideline" and line.bold and title and capitalized and words(body) <= 18 and not re.search(r"\b(?:shall|must|should|will|may)\b|[.;,]$", body, re.I):
            return "heading", match["num"], title
    # Encoded Marathi still has trustworthy bold Arabic section numbers. Keep
    # the section boundary while leaving unreadable heading metadata null.
    if source["source_id"] == "MH_ACT_1960" and line.bold:
        encoded = PROVISION.match(text)
        if encoded and (encoded["body"] or (index + 1 < len(lines) and not PROVISION.match(lines[index + 1].text))):
            return "section", encoded["num"], None
    if dtype in {"scheme_guideline", "grievance_guidance"}:
        # A short typographic heading, not an arbitrary body sentence.
        previous = lines[index - 1] if index else None
        following = lines[index + 1] if index + 1 < len(lines) else None
        isolated = (previous is None or previous.block != line.block or previous.page != line.page) and (following is None or following.block != line.block or following.page != line.page or not following.bold)
        if line.bold and (isolated or line.size > body_size * 1.12) and 2 <= words(text) <= 18 and not SUB.match(text) and not QUALIFIER.match(text) and not re.search(r"[.;,]$", text):
            return "heading", "", text
        if dtype == "grievance_guidance" and re.match(r"^(?:Who can|How to|Scope of|Procedure for|Complaint[s]?|Appeal[s]?|Time limit|Contact|Filing|Form\s+VI)\b", text, re.I) and (text.endswith(":") or words(text) <= 12):
            return "heading", "", text.rstrip(":")
    return None


def units_from(lines, source):
    sizes = Counter(round(line.size, 1) for line in lines if words(line.text) > 6)
    body_size = sizes.most_common(1)[0][0] if sizes else 10
    context = {field: None for field in STRUCT_FIELDS}
    # Scheme name is used only when the exact name occurs in extracted content.
    if source["source_id"] == "PMFBY_2023" and any(re.search(r"Pradhan Mantri Fasal Bima Yojana", line.text, re.I) for line in lines):
        context["scheme_name"] = "Pradhan Mantri Fasal Bima Yojana"
    units = []
    unit = Unit(context.copy())
    last_numbers = {}
    heading_context = {}
    for index, line in enumerate(lines):
        detected = detect_structure(lines, index, source, body_size, unit.kind)
        if detected:
            kind, identifier, heading = detected
            if kind in {"chapter", "part"}:
                if unit.lines:
                    units.append(unit)
                context[kind] = norm(line.text)
                if kind == "part":
                    context["chapter"] = None
                heading_context.clear()
                unit = Unit(context.copy(), kind="context")
            else:
                if unit.lines:
                    units.append(unit)
                meta = context.copy()
                meta["heading"] = heading
                if kind in {"section", "rule", "clause"}:
                    meta[kind] = identifier
                elif kind == "item":
                    meta["amendment_item"] = identifier
                elif kind == "heading" and identifier:
                    meta["section"] = identifier
                    if "." in identifier:
                        meta["subheading"] = heading
                        ancestors = [key for key in heading_context if identifier.startswith(key + ".")]
                        if ancestors:
                            meta["heading"] = heading_context[max(ancestors, key=lambda key: len(key.split(".")))]
                    heading_context[identifier] = heading
                elif kind == "form":
                    meta["form_number"] = identifier or None
                if kind in {"form", "schedule", "annexure", "annex", "appendix"}:
                    heading_context.clear()
                unit = Unit(meta, kind=kind, identifier=identifier)
                if kind in {"section", "rule", "clause", "item"}:
                    number = int(re.match(r"\d+", identifier)[0])
                    if kind in last_numbers and number < last_numbers[kind]:
                        unit.warnings.add("MALFORMED_NUMBERING_HIERARCHY")
                    last_numbers[kind] = number
        elif PROVISION.match(line.text) and not line.table and unit.kind == "context":
            unit.warnings.add("STRUCTURE_UNCERTAIN")
        unit.lines.append(line)
        unit.warnings.update(line.warnings)
    if unit.lines:
        units.append(unit)
    # Headings/chapter context become parent context for the next provision, not
    # a separate tiny chunk containing no operative text.
    merged = []
    pending = []
    for unit in units:
        if unit.kind == "context" and words(text_of(unit.lines)) < 40:
            pending.extend(unit.lines)
            continue
        if pending:
            unit.lines = pending + unit.lines
            pending = []
        merged.append(unit)
    if pending:
        if merged:
            merged[-1].lines.extend(pending)
        else:
            merged.append(Unit(context.copy(), pending))
    if source["document_type"] in {"scheme_guideline", "grievance_guidance"}:
        combined = []
        for unit in merged:
            if combined and words(text_of(combined[-1].lines)) < 20 and combined[-1].kind == "heading" and not combined[-1].identifier:
                previous = combined.pop()
                if previous.meta.get("section") and unit.meta.get("section", "") and str(unit.meta["section"]).startswith(str(previous.meta["section"]) + "."):
                    unit.meta["subheading"] = unit.meta["heading"]
                    unit.meta["heading"] = previous.meta["heading"]
                unit.lines = previous.lines + unit.lines
                unit.warnings.update(previous.warnings)
            combined.append(unit)
        merged = combined
    return merged


def amendment_metadata(unit):
    text = text_of(unit.lines)
    # Only the item's operative introduction; quoted replacement provisions
    # must not redefine the affected provision or action.
    lead = text[:1500]
    affected = re.search(r"\b(?:In|For|After|Before|of)\s+(?:the\s+)?(section|rule|sub-section|sub-rule)\s+(\d+[A-Z]?(?:\s*\([\da-z]+\))?)", lead, re.I)
    if affected:
        unit.meta["affected_provision"] = affected.group(1).lower() + " " + affected.group(2)
    actions = []
    for name, pattern in (("insertion", r"\binsert(?:ed|ion)\b"), ("substitution", r"\bsubstitut(?:ed|ion)\b"), ("omission", r"\bomitt?ed\b|\bomission\b"), ("renumbering", r"\brenumber(?:ed|ing)\b")):
        if re.search(pattern, lead, re.I):
            actions.append(name)
    if len(actions) == 1:
        unit.meta["amendment_action"] = actions[0]
    elif len(actions) > 1:
        unit.warnings.add("MULTIPLE_AMENDMENT_ACTIONS")
    elif re.search(r"\bamend(?:ment|ed)\b", lead, re.I):
        unit.meta["amendment_action"] = "amendment"


def legal_children(unit):
    """Split only top-level sequential subsection/definition runs.
    Small or dependent fragments stay with their complete parent provision.
    Provisos and explanations travel with the preceding numbered provision.
    """
    definitions = bool(re.search(r"\bdefinitions?\b", unit.meta.get("heading") or "", re.I))
    expanded = []
    for index, line in enumerate(unit.lines):
        # First subsection often begins on the same line as the section heading.
        inline = re.search(r"(?<=[—–.:-])\s*(\(1\))\s*", line.text) if index < 4 else None
        if inline:
            start = inline.start(1)
            expanded.extend([replace(line, text=line.text[:start].rstrip()), replace(line, text=line.text[start:])])
        else:
            expanded.append(line)
    unit.lines = expanded
    candidates = []
    for index, line in enumerate(unit.lines):
        if line.table:
            continue
        match = SUB.match(line.text)
        if match and (match["num"].isdigit() or (definitions and len(match["num"]) == 1)):
            candidates.append((index, match["num"], line.box[0]))
    if len(candidates) < 2:
        return [], []
    numeric = [candidate for candidate in candidates if candidate[1].isdigit()]
    selected = numeric if len(numeric) >= 2 else candidates
    # Leftmost run is the outer level, preventing embedded lists from becoming
    # sibling sub-sections. Sequence validation rejects restarts/quoted lists.
    left = min(item[2] for item in selected)
    selected = [item for item in selected if item[2] <= left + 16]
    values = [int(item[1]) if item[1].isdigit() else ord(item[1]) for item in selected]
    if len(selected) < 2 or any(b <= a for a, b in zip(values, values[1:])):
        unit.warnings.add("STRUCTURE_UNCERTAIN")
        return [], []
    intro = unit.lines[:selected[0][0]]
    pieces = []
    for position, (index, identifier, _) in enumerate(selected):
        end = selected[position + 1][0] if position + 1 < len(selected) else len(unit.lines)
        part = unit.lines[index:end]
        if words(text_of(part)) <= 3:
            # Do not create a child whose legal meaning depends on a tiny list
            # fragment; retaining the parent is safer than inventing grouping.
            return [], []
        pieces.append((identifier, part))
    if words(text_of(unit.lines)) <= 450 and not definitions:
        return [], []
    return intro, pieces


def prose_children(unit):
    """Use complete layout paragraphs and sentence boundaries for long prose.
    Numbered procedures, notes, forms and tables stay atomic. Approximate overlap
    is a complete preceding sentence only, never a cut-off 50-word fragment.
    """
    if words(text_of(unit.lines)) <= 500 or unit.kind in {"form", "schedule", "annexure", "annex", "appendix"}:
        return [], []
    paragraphs = []
    for line in unit.lines:
        if (not paragraphs or line.table or paragraphs[-1][-1].table or SUB.match(line.text)
                or (line.page == paragraphs[-1][-1].page and line.block != paragraphs[-1][-1].block)):
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)
    atomic = []
    for paragraph in paragraphs:
        text = text_of(paragraph)
        protected = any(line.table for line in paragraph) or SUB.match(text) or PROVISION.match(text) or QUALIFIER.match(text)
        list_start = bool(SUB.match(text) or PROVISION.match(text) or re.match(r"^[•●]", text))
        previous_list = atomic and (SUB.match(atomic[-1][-1].text) or PROVISION.match(atomic[-1][-1].text) or re.match(r"^[•●]", atomic[-1][-1].text))
        if atomic and (QUALIFIER.match(text) or re.match(r"^(?:[•●]|\([a-zivx]+\))", text)
                       or (list_start and (previous_list or text_of(atomic[-1]).endswith(":")))
                       or atomic[-1][-1].table or any(line.table for line in paragraph)):
            atomic[-1].extend(paragraph)
        elif not protected and words(text) > 500 and len({line.page for line in paragraph}) == 1:
            # Do not split abbreviations, initials, decimals or section references.
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z][a-z]{2,}\b)", text)
            if len(sentences) > 1:
                for sentence in sentences:
                    atomic.append([replace(paragraph[0], text=sentence)])
            else:
                atomic.append(paragraph)
        else:
            atomic.append(paragraph)
    groups, current = [], []
    for paragraph in atomic:
        if current and words(text_of(current)) >= 300 and words(text_of(current + paragraph)) > 500 and re.search(r"[.!?][\"')\]]*$", text_of(current)):
            groups.append(current)
            current = []
        current.extend(paragraph)
    if current:
        groups.append(current)
    if len(groups) < 2 or any(words(text_of(group)) < 20 for group in groups):
        return [], []
    # Paragraph boundaries take precedence over target size. Use overlap only
    # between plain prose blocks and cap it to one intact 25–75-word sentence.
    with_overlap = []
    for index, group in enumerate(groups):
        if index:
            previous = groups[index - 1]
            if not any(line.table or SUB.match(line.text) or PROVISION.match(line.text) or QUALIFIER.match(line.text) for line in previous[-1:] + group[:1]):
                tail = re.split(r"(?<=[.!?])\s+(?=[A-Z][a-z]{2,}\b)", text_of(previous))[-1]
                if 25 <= words(tail) <= 75:
                    group = [replace(previous[-1], text=tail)] + group
        with_overlap.append((str(index + 1), group))
    intro = [unit.lines[0]] if unit.kind == "heading" and words(unit.lines[0].text) <= 40 else []
    return intro, with_overlap


def form_children(unit):
    """Large forms split only at explicit titled field groups, never by length."""
    if words(text_of(unit.lines)) <= 900:
        return [], []
    starts = []
    for index, line in enumerate(unit.lines):
        if index and line.bold and not line.table and 2 <= words(line.text) <= 15 and not QUALIFIER.match(line.text):
            previous = unit.lines[index - 1]
            following = unit.lines[index + 1] if index + 1 < len(unit.lines) else None
            if (previous.block != line.block or previous.page != line.page) and (following is None or not following.bold):
                starts.append(index)
    if len(starts) < 2:
        return [], []
    groups = [unit.lines[start:(starts[i + 1] if i + 1 < len(starts) else len(unit.lines))] for i, start in enumerate(starts)]
    if any(words(text_of(group)) < 20 for group in groups):
        return [], []
    return unit.lines[:starts[0]], [(str(i + 1), group) for i, group in enumerate(groups)]


def replacement_children(unit):
    """Partition a long amendment at its explicitly numbered replacement rules.
    The amendment source and item remain the parent; nothing is consolidated.
    """
    if words(text_of(unit.lines)) <= 900:
        return [], []
    starts = []
    for index, line in enumerate(unit.lines):
        if not index or line.table:
            continue
        text = norm(line.text).lstrip('“"‘')
        match = PROVISION.match(text)
        if not match:
            continue
        body = match["body"]
        has_title_boundary = bool(re.search(r"[—–]|\.\s*[-—–]|[.:-]\s*\(1\)", body))
        if has_title_boundary and not re.match(r"(?:In|For|After|Before)\b", body, re.I):
            starts.append((index, match["num"]))
    if len(starts) < 2:
        return [], []
    children = [(number, unit.lines[index:(starts[pos + 1][0] if pos + 1 < len(starts) else len(unit.lines))]) for pos, (index, number) in enumerate(starts)]
    return unit.lines[:starts[0][0]], children


def iso_date(value):
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Invalid retrieved_date in sources.csv")


def source_topics(sid):
    topics = {"PMFBY_2023": {"pmfby", "crop_insurance"}, "PACS_MODEL_BYLAWS": {"pacs", "byelaws"},
              "PACS_COMPUTERIZATION": {"pacs", "computerization"}, "CRCS_OMBUDSMAN": {"grievance", "ombudsman"}}.get(sid, set()).copy()
    if sid.startswith("MSCS_"):
        topics.add("multistate")
    if sid in {"KA_ACT_1959", "MH_ACT_1960"}:
        topics.add("state_law")
    return topics


def tag_topics(source, meta, text):
    content = " ".join(filter(None, [meta.get("heading"), meta.get("subheading"), text]))
    topics = source_topics(source["source_id"]) | {key for key, regex in TOPIC_RE.items() if regex.search(content)}
    if source["source_id"] == "PMFBY_2023" and re.search(r"(?:optional|compulsory|mandatory) for (?:all )?farmers|farmers (?:who|including)|eligible|eligibility", content, re.I):
        topics.add("eligibility")
    return sorted(topics)


def form_metadata(meta, text):
    forms = re.findall(r"\bForm\s*[-–]?\s*(VII|VI|[IVXLCDM]+|[0-9]+|[A-Z](?:-[A-Z0-9]+)?)\b", text, re.I)
    forms = list(dict.fromkeys("Form " + form.upper() for form in forms))
    existing = meta.get("form_number")
    if existing:
        existing = existing if existing.startswith("Form ") else "Form " + existing
    specific = bool(existing or re.search(r"fil(?:e|ing)|submit|complaint|appeal|application|prescribed form", text, re.I))
    return (existing or forms[0] if specific and forms else existing), bool(specific and len(forms) > 1)


def blocking_warnings(record, warnings):
    """Only unresolved retrieval risks block a source, not every observation."""
    severe = {"HIERARCHY_REVIEW", "ORPHAN_CHILD", "MAJOR_DUPLICATE_TEXT", "LEGACY_FONT_ENCODING_REVIEW",
              "EXTRACTION_QUALITY_REVIEW", "TABLE_CORRUPTION", "TOC_REVIEW", "HEADER_DOMINATED", "INCOMPLETE_PROVISION",
              "BILINGUAL_REVIEW", "MULTIPLE_AMENDMENT_ACTIONS"}
    result = set(warnings) & severe
    return result


def retrieval_status(record, warnings):
    """Classify preservation records without making short legal units ineligible."""
    if record["record_type"] == "parent":
        if warnings & {"EXTRACTION_QUALITY_REVIEW", "LEGACY_FONT_ENCODING_REVIEW"}:
            return "REVIEW"
        return "REFERENCE_ONLY"
    if record.get("word_count", 0) > 900:
        if record.get("document_type") in {"scheme_guideline", "rules"} and (
            re.search(r"annex|schedule|form", record.get("heading") or "", re.I)
            or "TABLE_REVIEW" in warnings
            or not (record.get("section") or record.get("rule"))
        ):
            return "REFERENCE_ONLY"
        if not (blocking_warnings(record, warnings) - {"LONG_CHUNK_NO_SAFE_SPLIT"}):
            return "ACTIVE"
    if blocking_warnings(record, warnings):
        return "REVIEW"
    if record.get("text_scope") in {"front_matter", "context_only"}:
        return "REFERENCE_ONLY"
    return "ACTIVE"


def record_for(source, meta, identifier, lines, record_type, parent_id=None, scope="complete_provision"):
    text = text_of(lines)
    record = dict(chunk_id=identifier, record_type=record_type, parent_id=parent_id)
    record.update({key: source[key] for key in META_FIELDS})
    record["retrieved_date"] = iso_date(source["retrieved_date"])
    record.update({key: meta.get(key) for key in STRUCT_FIELDS})
    if "amendment_item" in meta:
        record["amendment_item"] = meta["amendment_item"]
    record["form_number"], multiple_forms = form_metadata(meta, text)
    record.update(page_start=min(line.page for line in lines), page_end=max(line.page for line in lines),
                  topics=tag_topics(source, meta, text),
                  text=text, char_count=len(text), word_count=words(text), text_scope=scope)
    record["retrieval_status"] = retrieval_status(record, set())
    if multiple_forms:
        record["_form_review"] = True
    return record


def records_from(units, source):
    used = Counter()
    structural_parents = {}
    def unique(base):
        used[base] += 1
        return base if used[base] == 1 else f"{base}_{used[base]:03d}"
    if not units:
        return
    # One document context parent avoids duplicating every short provision into
    # an artificial heading parent and a full-text child. Full short provisions
    # are single retrieval children; only structurally split provisions get
    # their own intermediate parent.
    root_id = unique(source["source_id"] + "_DOC")
    root_lines = [units[0].lines[0]]
    root_only_first_unit = text_of(root_lines) == text_of(units[0].lines)
    root_meta = units[0].meta if root_only_first_unit else {}
    root = record_for(source, root_meta, root_id, root_lines, "parent", scope="context_only")
    root["page_end"] = max(line.page for unit in units for line in unit.lines)
    yield root, {"CONTEXT_PARENT"} | (units[0].warnings if root_only_first_unit else set())
    for ordinal, unit in enumerate(units, 1):
        if ordinal == 1 and root_only_first_unit:
            continue
        if not text_of(unit.lines):
            continue
        dtype = source["document_type"]
        if dtype in {"amendment", "amendment_rules"}:
            amendment_metadata(unit)
        prefix = {"section": "SEC", "rule": "RULE", "clause": "CLAUSE", "item": "ITEM", "heading": "SEC", "form": "FORM"}.get(unit.kind, unit.kind.upper())
        identifier = unique(f"{source['source_id']}_{prefix}_{slug(unit.identifier) or f'{ordinal:03d}'}")
        warnings = set(unit.warnings)
        enclosing_id = root_id
        has_descendants = False
        if unit.kind in {"form", "schedule", "annexure", "annex", "appendix"}:
            structural_parents.clear()
        if unit.kind == "heading" and unit.identifier:
            ancestors = [key for key in structural_parents if unit.identifier.startswith(key + ".")]
            if ancestors:
                enclosing_id = structural_parents[max(ancestors, key=lambda key: len(key.split(".")))]
            elif "." in unit.identifier:
                warnings.add("STRUCTURE_UNCERTAIN")
            for later in units[ordinal:]:
                if later.kind in {"form", "schedule", "annexure", "annex", "appendix"}:
                    break
                if later.kind == "heading" and later.identifier:
                    has_descendants = later.identifier.startswith(unit.identifier + ".")
                    break
        front_matter = unit.kind == "background" or unit.kind == "context" and words(text_of(unit.lines)) <= 250 and ordinal == 1
        if unit.kind == "context" and not front_matter:
            warnings.add("STRUCTURE_UNCERTAIN")
        if dtype == "act" and not unit.meta["section"] and not front_matter and unit.kind not in {"form", "schedule", "annexure", "annex", "appendix"}:
            warnings.add("SECTION_IDENTIFIER_MISSING")
        if dtype == "rules" and not unit.meta["rule"] and not front_matter and unit.kind not in {"form", "schedule", "annexure", "annex", "appendix"}:
            warnings.add("RULE_IDENTIFIER_MISSING")
        intro, children = legal_children(unit) if dtype in {"act", "rules", "model_byelaws"} and unit.kind in {"section", "rule", "clause"} else ([], [])
        if dtype in {"scheme_guideline", "grievance_guidance"}:
            intro, children = prose_children(unit)
        if unit.kind == "background":
            intro, children = prose_children(unit)
        if unit.kind == "item":
            intro, children = replacement_children(unit)
        if unit.kind in {"form", "schedule", "annexure", "annex", "appendix"}:
            intro, children = form_children(unit)
        warnings.update(unit.warnings)
        if not children:
            if has_descendants:
                structural_parents[unit.identifier] = identifier
                yield record_for(source, unit.meta, identifier, unit.lines, "parent", enclosing_id, scope="context_only"), warnings
            else:
                yield record_for(source, unit.meta, identifier, unit.lines, "child", enclosing_id, scope="front_matter" if front_matter else "complete_provision"), warnings
            continue
        store_context = words(text_of(unit.lines)) > 900
        parent_lines = (intro or [unit.lines[0]]) if store_context else unit.lines
        parent = record_for(source, unit.meta, identifier, parent_lines, "parent", enclosing_id, scope="context_only" if store_context else "complete_provision")
        if has_descendants:
            structural_parents[unit.identifier] = identifier
        parent["page_end"] = max(line.page for line in unit.lines)
        yield parent, warnings | ({"CONTEXT_PARENT"} if store_context else set())
        for child_identifier, child_lines in children:
            meta = unit.meta.copy()
            if unit.kind == "item":
                meta["rule" if dtype == "amendment_rules" else "section"] = child_identifier
                meta["heading"] = None
            elif unit.kind in {"form", "schedule", "annexure", "annex", "appendix"}:
                meta["subheading"] = norm(child_lines[0].text)
            elif dtype == "act" and not front_matter:
                meta["subsection" if child_identifier.isdigit() else "clause"] = child_identifier
            elif dtype == "rules":
                meta["subrule" if child_identifier.isdigit() else "clause"] = child_identifier
            elif dtype == "model_byelaws":
                meta["subclause"] = child_identifier
            child = record_for(source, meta, unique(identifier + "_SUB_" + slug(child_identifier)), child_lines, "child", identifier, scope="front_matter" if front_matter else "complete_provision")
            yield child, warnings


def validate_record(record, source, seen, parent_ids, total_pages, warnings):
    warnings = set(warnings)
    if record.pop("_form_review", False):
        warnings.add("MULTIPLE_FORMS_REVIEW")
    for key in ("chunk_id", "source_id", "text", "source_url"):
        if not record.get(key):
            raise ValueError(f"Missing required record field: {key}")
    if record["chunk_id"] in seen:
        raise ValueError("Duplicate chunk_id")
    if record["source_id"] != source["source_id"] or any(record[key] != source[key] for key in ("jurisdiction", "document_type")):
        raise ValueError("Record/source metadata mismatch")
    if record["char_count"] != len(record["text"]) or record["word_count"] != words(record["text"]):
        raise ValueError("Invalid text counts")
    if not 1 <= record["page_start"] <= record["page_end"] <= total_pages:
        raise ValueError("Invalid page range")
    if set(record["topics"]) - TOPICS.keys():
        raise ValueError("Unknown topic")
    if record["parent_id"] is not None and record["parent_id"] not in parent_ids:
        raise ValueError("Missing parent or child before parent")
    if record["record_type"] == "child" and record["parent_id"] is None:
        raise ValueError("Child has no parent")
    if record["record_type"] == "parent":
        parent_ids.add(record["chunk_id"])
    seen.add(record["chunk_id"])
    if record["word_count"] < 20:
        if record["record_type"] == "parent" and record["text_scope"] == "context_only":
            warnings.add("SHORT_CONTEXT_PARENT")
        elif re.fullmatch(r"\s*[\dA-Z().\[\]-]+\s*", record["text"]):
            warnings.add("INCOMPLETE_PROVISION")
        elif any(record.get(k) for k in ("section", "rule", "clause", "form_number")) and re.search(r"[.;:]|omitted|XXX|means|shall", record["text"], re.I):
            warnings.add("SHORT_COMPLETE_PROVISION")
        else:
            warnings.add("SHORT_CHUNK")
    if record["word_count"] > 900:
        warnings.add("LONG_CHUNK_NO_SAFE_SPLIT")
    if len(re.findall(r"\.{3,}\s*\d+", record["text"])) >= 3 and not re.search(r"\b(?:form|signature|address|name)\b", record["text"], re.I):
        warnings.add("TOC_REVIEW")
    if len(re.findall(r"gazette|downloaded from|www\.", record["text"], re.I)) > max(3, record["word_count"] / 15):
        warnings.add("HEADER_DOMINATED")
    return warnings


def fingerprint(source, validation, page_validation_hash):
    raw = (ROOT / "data" / "raw").resolve()
    path = (raw / source["relative_path"]).resolve()
    if not path.is_relative_to(raw) or not path.is_file():
        raise ValueError("Source path missing or outside data/raw")
    pdf_hash = digest(path)
    if validation.get("sha256") != pdf_hash:
        raise ValueError("PDF checksum differs from validated input; rerun validate_corpus.py")
    if validation.get("classification") != "TEXT_BASED" or validation.get("metadata_issues") or validation.get("errors"):
        raise ValueError("Source validation is not clean/TEXT_BASED")
    data = dict(source=source, pdf=pdf_hash, validation=validation, pages=page_validation_hash,
                parser=digest(Path(__file__)), pymupdf=pymupdf.__version__)
    return path, hashlib.sha256(json_line(data).encode()).hexdigest()


def checkpoint_paths(source_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
        raise ValueError("Unsafe source_id for checkpoint")
    folder = OUT / "checkpoints"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{source_id}.jsonl", folder / f"{source_id}.stats.csv", folder / f"{source_id}.manifest.json"


def valid_checkpoint(paths, signature):
    records, stats, manifest = paths
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data["fingerprint"] == signature and data["records_sha256"] == digest(records) and data["stats_sha256"] == digest(stats):
            return data
    except (OSError, ValueError, KeyError):
        pass
    return None


def process_source(source, path, signature, paths):
    lines, metrics, warnings = extract_layout(path, source)
    units = units_from(lines, source)
    counts = Counter(unit.kind for unit in units)
    record_path, stats_path, manifest_path = paths
    record_temp, stats_temp = record_path.with_suffix(".jsonl.tmp"), stats_path.with_suffix(".csv.tmp")
    seen, parents = set(), set()
    totals = Counter()
    # Buffer only this source so parent ranges can be extended over descendants
    # before the records are streamed in parent-before-child order.
    items = list(records_from(units, source))
    by_id = {record["chunk_id"]: record for record, _ in items}
    for record, record_warnings in reversed(items):
        parent = by_id.get(record["parent_id"])
        if parent:
            parent["page_start"] = min(parent["page_start"], record["page_start"])
            parent["page_end"] = max(parent["page_end"], record["page_end"])
            invalid = parent["source_id"] != record["source_id"]
            invalid |= any(parent.get(k) and record.get(k) and parent[k] != record[k] for k in ("rule", "clause"))
            if parent.get("section") and record.get("section"):
                invalid |= not (record["section"] == parent["section"] or record["section"].startswith(parent["section"] + "."))
            if parent["text_scope"] == "complete_provision" and norm(record["text"]) not in norm(parent["text"]):
                invalid = True
            if invalid:
                record_warnings.add("HIERARCHY_REVIEW")
    blockers = warnings & {"LEGACY_FONT_ENCODING_REVIEW", "EXTRACTION_QUALITY_REVIEW", "TABLE_CORRUPTION"}
    with record_temp.open("w", encoding="utf-8", newline="\n") as output, stats_temp.open("w", encoding="utf-8", newline="") as stats:
        writer = csv.DictWriter(stats, fieldnames=STATS_FIELDS)
        writer.writeheader()
        for record, record_warnings in items:
            record_warnings = validate_record(record, source, seen, parents, metrics["pages"], record_warnings)
            record["retrieval_status"] = retrieval_status(record, record_warnings)
            output.write(json_line(record))
            row = {key: record.get(key) for key in STATS_FIELDS}
            row.update(topics=";".join(record["topics"]), warning=";".join(sorted(record_warnings)))
            writer.writerow(row)
            totals[record["record_type"]] += 1
            warnings.update(record_warnings - {"CONTEXT_PARENT"})
            blockers.update(blocking_warnings(record, record_warnings))
    if not seen:
        raise ValueError("No records extracted")
    report = dict(source_id=source["source_id"], filename=source["filename"],
                  **{key: metrics[key] for key in ("pages", "raw_chars", "cleaned_chars", "tables_detected")},
                  parent_records=totals["parent"], child_records=totals["child"], total_records=len(seen),
                  sections_detected=counts["section"] + (counts["item"] if source["document_type"] == "amendment" else 0),
                  rules_detected=counts["rule"] + (counts["item"] if source["document_type"] == "amendment_rules" else 0),
                  clauses_detected=counts["clause"], headings_detected=sum(bool(u.meta["heading"]) for u in units),
                  forms_detected=counts["form"], warnings=";".join(sorted(warnings)), status="REVIEW" if blockers else "PASS")
    record_temp.replace(record_path)
    stats_temp.replace(stats_path)
    manifest = dict(fingerprint=signature, records_sha256=digest(record_path), stats_sha256=digest(stats_path),
                    report=report, blocking_warnings=sorted(blockers), toc_pages_excluded=metrics["toc_pages_excluded"])
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json_line(manifest), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def aggregate(sources, available, failures):
    """Disk-backed global duplicate detection; never load corpus text at once."""
    reports = []
    readiness = []
    counts = Counter()
    child_sizes = []
    samples = {}
    with tempfile.TemporaryDirectory(prefix="validation-", dir=OUT) as tempdir:
        db = sqlite3.connect(str(Path(tempdir) / "audit.sqlite"))
        db.execute("CREATE TABLE records (id TEXT PRIMARY KEY, hash TEXT, source TEXT, kind TEXT, position INTEGER)")
        position = 0
        for source in sources:
            sid = source["source_id"]
            if sid not in available:
                continue
            records_path, _, _ = checkpoint_paths(sid)
            with records_path.open(encoding="utf-8") as stream:
                for line in stream:
                    record = json.loads(line)
                    position += 1
                    if record["parent_id"] is not None:
                        parent = db.execute("SELECT kind FROM records WHERE id=?", (record["parent_id"],)).fetchone()
                        if not parent or parent[0] != "parent":
                            raise ValueError("Missing parent during final validation")
                    db.execute("INSERT INTO records VALUES (?,?,?,?,?)", (record["chunk_id"], hashlib.sha256(record["text"].encode()).hexdigest(), sid, record["record_type"], position))
        db.execute("CREATE INDEX content_hash ON records(hash)")
        db.execute("CREATE TABLE duplicates AS SELECT hash FROM records GROUP BY hash HAVING count(*) > 1")
        db.execute("CREATE INDEX duplicate_hash ON duplicates(hash)")
        documents_temp = OUT / "documents.jsonl.tmp"
        stats_temp = OUT / "chunk_stats.csv.tmp"
        with documents_temp.open("w", encoding="utf-8", newline="\n") as output, stats_temp.open("w", encoding="utf-8", newline="") as stats:
            writer = csv.DictWriter(stats, fieldnames=STATS_FIELDS)
            writer.writeheader()
            for source in sources:
                sid = source["source_id"]
                if sid not in available:
                    report = dict.fromkeys(REPORT_FIELDS, 0)
                    report.update(source_id=sid, filename=source["filename"], warnings=failures.get(sid, "CHECKPOINT_MISSING_OR_STALE"), status="ERROR")
                    reports.append(report)
                    readiness.append(dict(source_id=sid, total_records=0, active_records=0, reference_only_records=0,
                                         review_records=0, unresolved_structure_problems=1, status="ERROR"))
                    continue
                record_path, stats_path, _ = checkpoint_paths(sid)
                report = dict(available[sid]["report"])
                source_warnings = set(filter(None, report["warnings"].split(";")))
                source_blockers = set(available[sid].get("blocking_warnings", []))
                source_structure_problems = 0
                with record_path.open(encoding="utf-8") as stream, stats_path.open(encoding="utf-8", newline="") as stat_stream:
                    stat_rows = csv.DictReader(stat_stream)
                    for line in stream:
                        record = json.loads(line)
                        row = next(stat_rows)
                        if row["chunk_id"] != record["chunk_id"]:
                            raise ValueError("Checkpoint statistics mismatch")
                        warnings = set(filter(None, row["warning"].split(";")))
                        duplicate = db.execute("SELECT 1 FROM records r JOIN duplicates d ON r.hash=d.hash WHERE r.id=?", (record["chunk_id"],)).fetchone()
                        if duplicate:
                            warnings.add("DUPLICATE_TEXT")
                            if record["word_count"] >= 150:
                                warnings.add("MAJOR_DUPLICATE_TEXT")
                        effective = warnings - {"CONTEXT_PARENT"}
                        blocking = blocking_warnings(record, warnings)
                        source_blockers.update(blocking)
                        source_structure_problems += bool(record.get("retrieval_status") == "REVIEW" and {"STRUCTURE_UNCERTAIN", "MALFORMED_NUMBERING_HIERARCHY", "SECTION_IDENTIFIER_MISSING", "RULE_IDENTIFIER_MISSING", "HIERARCHY_REVIEW"} & warnings)
                        source_warnings.update(effective)
                        row["warning"] = ";".join(sorted(warnings))
                        writer.writerow(row)
                        output.write(line)
                        counts["records"] += 1
                        counts[record["record_type"]] += 1
                        counts["suspicious"] += bool(blocking)
                        counts["table_warnings"] += bool({"TABLE_REVIEW", "TABLE_DETECTION_FAILED"} & effective)
                        counts["structure_warnings"] += bool({"STRUCTURE_UNCERTAIN", "MALFORMED_NUMBERING_HIERARCHY", "SECTION_IDENTIFIER_MISSING", "RULE_IDENTIFIER_MISSING"} & effective)
                        if record["record_type"] == "child":
                            child_sizes.append(record["word_count"])
                        category = "act" if record["document_type"] == "act" and record["record_type"] == "child" and record["subsection"] and record["word_count"] >= 20 else "pmfby" if sid == "PMFBY_2023" and record["record_type"] == "child" and record["section"] and 100 <= record["word_count"] <= 500 else "ombudsman" if sid == "CRCS_OMBUDSMAN" and record["record_type"] == "child" and record["word_count"] >= 20 else None
                        preferred = category == "pmfby" and record["parent_id"] != sid + "_DOC" or category == "ombudsman" and bool(record["heading"])
                        old_preferred = category in samples and (samples[category]["parent_id"] != sid + "_DOC" if category == "pmfby" else bool(samples[category]["heading"]) if category == "ombudsman" else True)
                        if category and (category not in samples or preferred and not old_preferred):
                            samples[category] = {**record, "text": record["text"][:200]}
                report.update(warnings=";".join(sorted(source_warnings)), status="REVIEW" if source_blockers else "PASS")
                reports.append(report)
                source_records = [r for r in (json.loads(line) for line in record_path.open(encoding="utf-8"))]
                readiness.append(dict(source_id=sid, total_records=len(source_records),
                                      active_records=sum(r.get("retrieval_status") == "ACTIVE" for r in source_records),
                                      reference_only_records=sum(r.get("retrieval_status") == "REFERENCE_ONLY" for r in source_records),
                                      review_records=sum(r.get("retrieval_status") == "REVIEW" for r in source_records),
                                      unresolved_structure_problems=source_structure_problems,
                                      status=report["status"]))
        db.close()
    report_temp = OUT / "extraction_report.csv.tmp"
    with report_temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(reports)
    documents_temp.replace(OUT / "documents.jsonl")
    stats_temp.replace(OUT / "chunk_stats.csv")
    report_temp.replace(OUT / "extraction_report.csv")
    readiness_path = OUT / "retrieval_readiness.csv.tmp"
    with readiness_path.open("w", encoding="utf-8", newline="") as stream:
        fields = "source_id total_records active_records reference_only_records review_records unresolved_structure_problems status".split()
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(readiness)
    readiness_path.replace(OUT / "retrieval_readiness.csv")
    statuses = Counter(row["status"] for row in reports)
    summary = dict(sources_processed=len(available), **{status: statuses[status] for status in ("PASS", "REVIEW", "ERROR")},
                   total_records=counts["records"], parent_records=counts["parent"], child_records=counts["child"],
                   child_words=dict(min=min(child_sizes, default=0), median=statistics.median(child_sizes) if child_sizes else 0,
                                    average=round(statistics.mean(child_sizes), 2) if child_sizes else 0, max=max(child_sizes, default=0)),
                   suspicious_chunks=counts["suspicious"], table_warning_chunks=counts["table_warnings"],
                   structure_warning_chunks=counts["structure_warnings"],
                   sources_requiring_review=[row["source_id"] for row in reports if row["status"] != "PASS"])
    return summary, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Regenerate or resume one source, then aggregate current checkpoints")
    parser.add_argument("--force", action="store_true", help="Ignore completed checkpoints for selected sources")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "data/metadata/sources.csv").open(encoding="utf-8-sig", newline="") as stream:
        sources = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(stream)]
    if not sources or len({s["source_id"] for s in sources}) != len(sources):
        raise ValueError("Missing sources or duplicate source IDs")
    if args.source and args.source not in {s["source_id"] for s in sources}:
        parser.error("Unknown --source")
    with (ROOT / "data/metadata/corpus_validation.csv").open(encoding="utf-8-sig", newline="") as stream:
        validations = {row["source_id"]: row for row in csv.DictReader(stream)}
    page_validation_hash = digest(ROOT / "data/metadata/page_validation.csv")
    available, failures = {}, {}
    for source in sources:
        sid = source["source_id"]
        try:
            path, signature = fingerprint(source, validations.get(sid, {}), page_validation_hash)
            paths = checkpoint_paths(sid)
            cached = valid_checkpoint(paths, signature)
            selected = not args.source or args.source == sid
            if selected and (args.force or not cached):
                before = digest(path)
                cached = process_source(source, path, signature, paths)
                if digest(path) != before:
                    paths[2].unlink(missing_ok=True)
                    raise ValueError("PDF changed during extraction")
                print(f"{source['filename']}: {cached['report']['total_records']} records; {cached['report']['status']}", flush=True)
            elif cached:
                print(f"{source['filename']}: {cached['report']['total_records']} records; checkpoint reused", flush=True)
            if cached:
                available[sid] = cached
        except Exception as exc:
            failures[sid] = f"{type(exc).__name__}: {exc}"
            print(f"{source['filename']}: WARNING {failures[sid]}", flush=True)
    summary, samples = aggregate(sources, available, failures)
    print(json.dumps(summary, indent=2))
    for category in ("act", "pmfby", "ombudsman"):
        if category in samples:
            print(json.dumps(samples[category], ensure_ascii=False))
    return 1 if summary["ERROR"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, csv.Error, sqlite3.Error) as error:
        print(f"WARNING: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(2)
