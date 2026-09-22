"""Stream a corpus quality audit, retaining only metadata and 200-char excerpts.

python scripts/audit_extraction.py [--input-dir data/processed]
Writes per-record extraction_audit.csv, source_quality_summary.csv and six
compact exception lists under audit_lists/. Percentiles use linear interpolation.
Word bands count children; all other warning counts include parents and children.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import statistics

import extract_corpus as pipeline

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = {"STRUCTURE_UNCERTAIN", "MALFORMED_NUMBERING_HIERARCHY", "SECTION_IDENTIFIER_MISSING", "RULE_IDENTIFIER_MISSING", "HIERARCHY_REVIEW"}
TABLE = {"TABLE_REVIEW", "TABLE_DETECTION_FAILED", "TABLE_CORRUPTION"}
AUDIT_FIELDS = "chunk_id source_id record_type word_count page_start page_end section rule clause heading warning audit_flags severity groups text_excerpt".split()
SUMMARY_FIELDS = "source_id parent_records child_records child_word_min child_word_p10 child_word_median child_word_p90 child_word_max chunks_lt20 chunks_20_49 chunks_50_149 chunks_150_450 chunks_451_900 chunks_gt900 all_records_lt20 all_records_gt900 structure_warnings table_warnings duplicate_text_warnings missing_heading_count missing_structural_id_count missing_parent_count topic_tag_warnings form_number_warnings hierarchy_warnings metadata_warnings suspicious_chunks".split()


def percentile(values, p):
    if not values:
        return 0
    values = sorted(values)
    at = (len(values) - 1) * p
    lo = int(at)
    hi = min(lo + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (at - lo), 2)


def guaranteed_topics(source_id):
    topics = {"PMFBY_2023": {"pmfby", "crop_insurance"}, "PACS_MODEL_BYLAWS": {"pacs", "byelaws"},
              "PACS_COMPUTERIZATION": {"pacs", "computerization"}, "CRCS_OMBUDSMAN": {"grievance", "ombudsman"}}.get(source_id, set()).copy()
    if source_id.startswith("MSCS_"):
        topics.add("multistate")
    if source_id in {"KA_ACT_1959", "MH_ACT_1960"}:
        topics.add("state_law")
    return topics


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(folder):
    with (ROOT / "data/metadata/sources.csv").open(encoding="utf-8-sig", newline="") as stream:
        sources = {r["source_id"]: r for r in csv.DictReader(stream)}
    with (folder / "chunk_stats.csv").open(encoding="utf-8", newline="") as stream:
        stats = {r["chunk_id"]: r for r in csv.DictReader(stream)}
    parents, seen, hashes, rows = {}, set(), defaultdict(list), []
    summaries = {sid: Counter() for sid in sources}
    sizes = defaultdict(list)
    with (folder / "documents.jsonl").open(encoding="utf-8") as stream:
        for raw in stream:
            r = json.loads(raw)
            sid, cid, text = r["source_id"], r["chunk_id"], r["text"]
            source = sources.get(sid, {})
            summary = summaries.setdefault(sid, Counter())
            flags = set()
            warnings = set(filter(None, stats.get(cid, {}).get("warning", "").split(";")))
            summary[r["record_type"] + "_records"] += 1
            count = r["word_count"]
            if r["record_type"] == "child":
                sizes[sid].append(count)
                band = "lt20" if count < 20 else "20_49" if count < 50 else "50_149" if count < 150 else "150_450" if count <= 450 else "451_900" if count <= 900 else "gt900"
                summary["chunks_" + band] += 1
            summary["all_records_lt20"] += count < 20
            summary["all_records_gt900"] += count > 900
            summary["structure_warnings"] += bool(warnings & STRUCTURE)
            summary["table_warnings"] += bool(warnings & TABLE)
            summary["duplicate_text_warnings"] += "DUPLICATE_TEXT" in warnings
            summary["missing_heading_count"] += not r.get("heading")
            expected = "section" if r["document_type"] == "act" else "rule" if r["document_type"] == "rules" else None
            exempt = r.get("text_scope") in {"context_only", "front_matter"} or r.get("form_number") or re.search(r"schedule|annex|appendix|statement of objects|preamble", r.get("heading") or "", re.I)
            if expected and not r.get(expected) and not exempt:
                summary["missing_structural_id_count"] += 1
                flags.add("MISSING_STRUCTURAL_ID")
            if cid in seen:
                flags.add("DUPLICATE_ID")
            parent = parents.get(r.get("parent_id"))
            if r["record_type"] == "child" and not parent:
                summary["missing_parent_count"] += 1
                flags.add("MISSING_PARENT")
            if parent:
                invalid = parent["source_id"] != sid or not (parent["page_start"] <= r["page_start"] <= r["page_end"] <= parent["page_end"])
                invalid |= any(parent.get(k) and r.get(k) and parent[k] != r[k] for k in ("rule", "clause"))
                if parent.get("section") and r.get("section"):
                    invalid |= not (r["section"] == parent["section"] or r["section"].startswith(parent["section"] + "."))
                if parent["text_scope"] == "complete_provision" and re.sub(r"\s+", " ", text).strip() not in parent["normalized_text"]:
                    invalid = True
                if invalid:
                    summary["hierarchy_warnings"] += 1
                    flags.add("HIERARCHY_REVIEW")
            topic_issue = bool(set(r["topics"]) - pipeline.TOPICS.keys() or guaranteed_topics(sid) - set(r["topics"]))
            if "membership" in r["topics"] and not re.search(r"membership|admission of (?:a |the )?members?|who may become a member", text + " " + (r.get("heading") or ""), re.I):
                topic_issue = True
            if topic_issue:
                summary["topic_tag_warnings"] += 1
                flags.add("TOPIC_TAG_REVIEW")
            form_mentions = re.findall(r"\bForm\s*[-–]?\s*(VII|VI|6|7)\b", text, re.I)
            filing = re.search(r"fil(?:e|ing)|submit|complaint|appeal|application", text, re.I)
            if form_mentions and filing and not r.get("form_number"):
                summary["form_number_warnings"] += 1
                flags.add("FORM_NUMBER_MISSING")
            if "MULTIPLE_FORMS_REVIEW" in warnings:
                summary["form_number_warnings"] += 1
            try:
                canonical = source["retrieved_date"]
                canonical = datetime.strptime(canonical, "%d-%m-%Y").date().isoformat() if re.fullmatch(r"\d{2}-\d{2}-\d{4}", canonical) else datetime.strptime(canonical, "%Y-%m-%d").date().isoformat()
                metadata_ok = r["retrieved_date"] == canonical and all(r[k] == source[k] for k in ("jurisdiction", "document_type", "authority", "relative_path", "source_url"))
            except (ValueError, KeyError):
                metadata_ok = False
            if not metadata_ok:
                flags.add("METADATA_REVIEW")
                summary["metadata_warnings"] += 1
            if not text.strip() or r["char_count"] != len(text) or count != len(text.split()):
                flags.add("TEXT_COUNT_ERROR")
            seen.add(cid)
            if r["record_type"] == "parent":
                parents[cid] = {k: r.get(k) for k in ("source_id", "page_start", "page_end", "section", "rule", "clause", "text_scope")}
                parents[cid]["normalized_text"] = re.sub(r"\s+", " ", text).strip() if r.get("text_scope") == "complete_provision" else ""
            groups = []
            if count > 900:
                groups.append("A_LONG")
            if count < 20:
                groups.append("B_SHORT")
            if "STRUCTURE_UNCERTAIN" in warnings:
                groups.append("E_STRUCTURE")
            if "TABLE_REVIEW" in warnings:
                groups.append("F_TABLE")
            row = {key: r.get(key, "") for key in AUDIT_FIELDS}
            blocker = pipeline.blocking_warnings(r, warnings) if hasattr(pipeline, "blocking_warnings") else warnings - {"CONTEXT_PARENT"}
            row.update(warning=";".join(sorted(warnings)), audit_flags=";".join(sorted(flags)),
                       severity="REVIEW" if blocker or flags else "INFO", groups=";".join(groups), text_excerpt=text[:200])
            rows.append(row)
            hashes[hashlib.sha256(text.encode()).hexdigest()].append(len(rows) - 1)
    for indices in hashes.values():
        if len(indices) > 1:
            for index in indices:
                flags = set(filter(None, rows[index]["audit_flags"].split(";"))) | {"DUPLICATE_TEXT"}
                rows[index]["audit_flags"] = ";".join(sorted(flags))
    for name, selected in (("C_TOP20_LONG", sorted(rows, key=lambda r: -r["word_count"])[:20]), ("D_TOP20_SHORT", sorted(rows, key=lambda r: r["word_count"])[:20])):
        for row in selected:
            row["groups"] = ";".join(filter(None, [row["groups"], name]))
    summary_rows = []
    for sid, summary in summaries.items():
        values = sizes[sid]
        summary.update(child_word_min=min(values, default=0), child_word_p10=percentile(values, .1),
                       child_word_median=statistics.median(values) if values else 0, child_word_p90=percentile(values, .9), child_word_max=max(values, default=0))
        summary["suspicious_chunks"] = sum(row["source_id"] == sid and row["severity"] == "REVIEW" for row in rows)
        summary_rows.append({key: sid if key == "source_id" else summary[key] for key in SUMMARY_FIELDS})
    write_csv(folder / "extraction_audit.csv", AUDIT_FIELDS, rows)
    write_csv(folder / "source_quality_summary.csv", SUMMARY_FIELDS, summary_rows)
    lists = folder / "audit_lists"
    lists.mkdir(exist_ok=True)
    for name in ("A_LONG", "B_SHORT", "C_TOP20_LONG", "D_TOP20_SHORT", "E_STRUCTURE", "F_TABLE"):
        selected = [r for r in rows if name in r["groups"].split(";")]
        if name == "C_TOP20_LONG":
            selected.sort(key=lambda r: -r["word_count"])
        if name == "D_TOP20_SHORT":
            selected.sort(key=lambda r: r["word_count"])
        write_csv(lists / (name + ".csv"), AUDIT_FIELDS, selected)
    print(json.dumps({"sources": len(summary_rows), "records": len(rows), "children": sum(len(v) for v in sizes.values()),
                      "all_chunks_lt20": sum(r["word_count"] < 20 for r in rows), "all_chunks_gt900": sum(r["word_count"] > 900 for r in rows),
                      "hierarchy_warnings": sum(r["hierarchy_warnings"] for r in summary_rows), "missing_parents": sum(r["missing_parent_count"] for r in summary_rows)}))
    return rows, summary_rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data/processed")
    audit(parser.parse_args().input_dir.resolve())
