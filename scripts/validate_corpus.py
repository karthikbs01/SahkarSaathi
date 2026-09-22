"""Read-only PDF corpus audit. Run with: python scripts/validate_corpus.py.

Character counts are len(page.get_text("text")), including whitespace; no
cleaning or OCR is performed. Classification uses unrounded percentages.
Unreadable pages have blank counts/status (unknown, not EMPTY) and an error.
Failed documents retain partial counts, marked extraction_complete=False.
Exit codes: 0 = audit passed (OCR recommendations allowed), 1 = review needed,
2 = setup/input failure. Paths are anchored to this script's project root.
"""

import csv
import hashlib
from collections import Counter
from pathlib import Path, PureWindowsPath
import sys

try:
    import pymupdf
except ImportError:
    raise SystemExit("Missing PyMuPDF. Install with: python -m pip install -r requirements.txt")


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "source_id", "filename", "relative_path", "source_url", "jurisdiction",
    "document_type", "authority", "priority",
)
RESULT_FIELDS = list(REQUIRED) + [
    "metadata_row", "file_exists", "file_size_bytes", "sha256", "pdf_opens",
    "is_encrypted", "password_protected", "page_count", "pages_extracted",
    "extraction_complete", "total_extracted_characters", "average_characters_per_page",
    "usable_text_pages", "low_text_pages", "empty_text_pages",
    "little_or_no_text_pages", "usable_page_percent", "classification",
    "ocr_recommendation", "metadata_issues", "errors", "manual_review_required",
]
PAGE_FIELDS = ["source_id", "filename", "page_number", "extracted_characters", "text_status", "extraction_error"]
OCR = {"TEXT_BASED": "NO", "MIXED": "PARTIAL", "LIKELY_SCANNED": "YES", "ERROR": "REVIEW"}


def classify(usable, total):
    if total <= 0:
        return "ERROR"
    if usable * 100 >= total * 80:
        return "TEXT_BASED"
    if usable * 100 >= total * 20:
        return "MIXED"
    return "LIKELY_SCANNED"


def resolve_pdf(raw, relative):
    normalized = relative.replace("\\", "/")
    if not relative or PureWindowsPath(relative).drive or normalized.startswith("/"):
        raise ValueError("relative_path must be a nonempty relative path under data/raw")
    path = (raw / normalized).resolve()
    if not path.is_relative_to(raw.resolve()):
        raise ValueError("relative_path escapes data/raw")
    return path


def audit(row, row_number, raw, duplicates):
    result = dict.fromkeys(RESULT_FIELDS, "")
    result.update({key: row.get(key, "") for key in REQUIRED})
    result.update(metadata_row=row_number, file_exists=False, pdf_opens=False,
                  extraction_complete=False, classification="ERROR")
    issues, errors, pages = [], [], []
    for key in REQUIRED:
        if not row.get(key):
            issues.append(f"missing {key}")
    for key in ("source_id", "relative_path"):
        if row[key] and duplicates[key][row[key]] > 1:
            issues.append(f"duplicate {key}")
    if row["priority"] not in {"P0", "P1"}:
        issues.append("invalid priority (expected P0/P1)")
    try:
        path = resolve_pdf(raw, row["relative_path"])
        if path.name != row["filename"]:
            issues.append("filename does not match relative_path basename")
        result["file_exists"] = path.is_file()
        if not result["file_exists"]:
            issues.append("relative_path does not match an existing file")
            raise FileNotFoundError(f"Missing file: {path}")
        result["file_size_bytes"] = path.stat().st_size
        with path.open("rb") as stream:
            result["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        with pymupdf.open(path) as doc:
            if not doc.is_pdf:
                raise ValueError("File is not a PDF")
            result["pdf_opens"] = True
            result["password_protected"] = bool(doc.needs_pass)
            result["is_encrypted"] = bool(doc.is_encrypted or doc.needs_pass or (doc.metadata or {}).get("encryption"))
            result["page_count"] = doc.page_count
            if doc.needs_pass:
                raise ValueError("Password-protected PDF: cannot extract without a password")
            if not doc.page_count:
                raise ValueError("PDF contains no pages")
            counts = []
            statuses = Counter()
            for index in range(doc.page_count):
                page = dict(source_id=row["source_id"], filename=row["filename"],
                            page_number=index + 1, extracted_characters="",
                            text_status="", extraction_error="")
                try:
                    count = len(doc.load_page(index).get_text("text"))
                    status = "USABLE" if count >= 100 else "LOW_TEXT" if count else "EMPTY"
                    page.update(extracted_characters=count, text_status=status)
                    counts.append(count)
                    statuses[status] += 1
                except Exception as exc:
                    page["extraction_error"] = f"{type(exc).__name__}: {exc}"
                    errors.append(f"Page {index + 1}: {page['extraction_error']}")
                pages.append(page)
            complete = len(counts) == doc.page_count
            result.update(
                pages_extracted=len(counts), extraction_complete=complete,
                total_extracted_characters=sum(counts),
                average_characters_per_page=round(sum(counts) / doc.page_count, 2) if complete else "",
                usable_text_pages=statuses["USABLE"], low_text_pages=statuses["LOW_TEXT"],
                empty_text_pages=statuses["EMPTY"],
                little_or_no_text_pages=statuses["LOW_TEXT"] + statuses["EMPTY"],
                usable_page_percent=round(100 * statuses["USABLE"] / doc.page_count, 2) if complete else "",
                classification=classify(statuses["USABLE"], doc.page_count) if complete else "ERROR",
            )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    # Known but unreadable pages stay unknown rather than appearing empty.
    if not pages and isinstance(result["page_count"], int):
        for number in range(1, result["page_count"] + 1):
            pages.append(dict(source_id=row["source_id"], filename=row["filename"],
                              page_number=number, extracted_characters="", text_status="",
                              extraction_error="; ".join(errors)))
    result.update(ocr_recommendation=OCR[result["classification"]],
                  metadata_issues="; ".join(issues), errors="; ".join(errors),
                  manual_review_required=bool(issues or errors))
    return result, pages


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    metadata = ROOT / "data" / "metadata"
    try:
        with (metadata / "sources.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = set(REQUIRED) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")
            rows = []
            for row in reader:
                if None in row:
                    raise ValueError(f"Extra CSV values at line {reader.line_num}")
                rows.append({key: (row.get(key) or "").strip() for key in REQUIRED})
        if not rows:
            raise ValueError("sources.csv contains no source rows")
        duplicates = {key: Counter(row[key] for row in rows) for key in ("source_id", "relative_path")}
        results, pages = [], []
        for number, row in enumerate(rows, start=2):
            result, page_rows = audit(row, number, ROOT / "data" / "raw", duplicates)
            results.append(result)
            pages.extend(page_rows)
        write_csv(metadata / "corpus_validation.csv", RESULT_FIELDS, results)
        write_csv(metadata / "page_validation.csv", PAGE_FIELDS, pages)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2

    classes = Counter(row["classification"] for row in results)
    found = sum(row["file_exists"] for row in results)
    print("## Corpus Validation Summary\n")
    print(f"Sources in CSV: {len(rows)}\nFiles found: {found}\nMissing files: {len(rows) - found}\n")
    for name in OCR:
        print(f"{name}: {classes[name]}")
    print(f"\nOCR required: {classes['LIKELY_SCANNED']}\nPartial OCR recommended: {classes['MIXED']}")
    print(f"Metadata issues: {sum(bool(row['metadata_issues']) for row in results)} source(s)")
    for label, selected in (
        ("OCR required", [r for r in results if r["ocr_recommendation"] == "YES"]),
        ("Partial OCR recommended", [r for r in results if r["ocr_recommendation"] == "PARTIAL"]),
        ("Manual review required", [r for r in results if r["manual_review_required"]]),
    ):
        print(f"\n{label}: " + (", ".join(r["source_id"] or f"CSV row {r['metadata_row']}" for r in selected) or "None"))
    print("\nErrors / metadata issues:")
    problems = [r for r in results if r["manual_review_required"]]
    for row in problems:
        print(f"  {row['source_id'] or row['metadata_row']}: " + "; ".join(filter(None, [row["metadata_issues"], row["errors"]])))
    if not problems:
        print("  None")
    columns = [("source_id", "source_id"), ("pages", "page_count"),
               ("extracted_chars", "total_extracted_characters"),
               ("usable_page_percent", "usable_page_percent"),
               ("classification", "classification"), ("ocr_recommendation", "ocr_recommendation")]
    widths = [max(len(label), *(len(str(r[key])) for r in results)) for label, key in columns]
    print()
    print(" | ".join(label.ljust(width) for (label, _), width in zip(columns, widths)))
    print("-+-".join("-" * width for width in widths))
    for row in results:
        print(" | ".join(str(row[key]).ljust(width) for (_, key), width in zip(columns, widths)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
