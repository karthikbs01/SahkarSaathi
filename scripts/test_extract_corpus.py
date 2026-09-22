"""Behavioral checks for legal boundaries and safe failure, using synthetic text."""
import csv
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

spec = importlib.util.spec_from_file_location("extract_corpus", Path(__file__).with_name("extract_corpus.py"))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def line(text, page=1, bold=False, block=0, x=40, table=False):
    return m.Line(text, page, (x, 120, 550, 132), 11, bold, block, table)


def source(dtype="act"):
    result = dict.fromkeys(m.META_FIELDS, "test")
    result.update(source_id="TEST", document_type=dtype, filename="test.pdf", title="Test Act", relative_path="test.pdf")
    return result


class ExtractionTests(unittest.TestCase):
    def test_section_across_pages_and_bottom_heading(self):
        lines = [line("22. Membership.—", bold=True), line("A member may apply under section 45.", page=2), line("The application shall be signed.", page=3)]
        units = m.units_from(lines, source())
        records = list(m.records_from(units, source()))
        child = next(record for record, _ in records if record["text_scope"] == "complete_provision")
        self.assertEqual((child["section"], child["page_start"], child["page_end"]), ("22", 1, 3))
        self.assertIn("under section 45", child["text"])

    def test_subsections_keep_proviso(self):
        lines = [line("22. Membership.—", bold=True)]
        for i in range(1, 4):
            lines.append(line(f"({i}) " + "A member has the following duty. " * 30, block=i))
            if i == 2:
                lines.append(line("Provided that the exception applies to that member.", block=5))
        records = list(m.records_from(m.units_from(lines, source()), source()))
        children = [r for r, _ in records if r["record_type"] == "child"]
        self.assertEqual([r["subsection"] for r in children], ["1", "2", "3"])
        self.assertIn("Provided that", children[1]["text"])
        self.assertNotIn("Provided that", children[2]["text"])

    def test_inline_first_subsection(self):
        lines = [line("22. Membership.—(1) " + "A member must apply. " * 60, bold=True), line("(2) " + "A member must sign. " * 60)]
        unit = m.Unit(dict.fromkeys(m.STRUCT_FIELDS), lines, kind="section", identifier="22")
        unit.meta.update(section="22", heading="Membership")
        _, children = m.legal_children(unit)
        self.assertEqual([number for number, _ in children], ["1", "2"])

    def test_short_section_not_split_for_numbering(self):
        unit = m.Unit(dict.fromkeys(m.STRUCT_FIELDS), [line("22. Membership.—"), line("(1) " + "The member shall apply. " * 8), line("(2) " + "The registrar shall reply. " * 8)], kind="section", identifier="22")
        self.assertEqual(m.legal_children(unit), ([], []))

    def test_definition_children(self):
        unit = m.Unit({**dict.fromkeys(m.STRUCT_FIELDS), "heading": "Definitions", "section": "2"}, [line("2. Definitions.—"), line('(a) "member" means ' + "a person with the qualifications specified in this Act " * 3), line('(b) "board" means ' + "the governing body constituted under this Act " * 3)], kind="section", identifier="2")
        _, children = m.legal_children(unit)
        self.assertEqual([number for number, _ in children], ["a", "b"])

    def test_nested_number_restarts_not_guessed(self):
        unit = m.Unit(dict.fromkeys(m.STRUCT_FIELDS), [line("(1) first"), line("(2) second"), line("(1) quoted")])
        self.assertEqual(m.legal_children(unit), ([], []))
        self.assertIn("STRUCTURE_UNCERTAIN", unit.warnings)

    def test_numbered_body_not_section(self):
        for text in ("(a) the member shall apply", "(i) the first case", "22. the following person shall apply"):
            self.assertIsNone(m.detect_structure([line(text)], 0, source(), 11, "section"))

    def test_amendment_item_not_quoted_section(self):
        s = source("amendment")
        self.assertEqual(m.detect_structure([line("15. In section 22, the following shall be inserted.")], 0, s, 11, "item")[:2], ("item", "15"))
        self.assertIsNone(m.detect_structure([line("22. Membership.—(1) A member shall apply.", bold=True)], 0, s, 11, "item"))

    def test_amendment_action(self):
        unit = m.Unit(dict.fromkeys(m.STRUCT_FIELDS), [line("15. In section 22, the following shall be substituted.")])
        m.amendment_metadata(unit)
        self.assertEqual(unit.meta["affected_provision"], "section 22")
        self.assertEqual(unit.meta["amendment_action"], "substitution")

    def test_forms_are_not_generic_numbered_sections(self):
        self.assertEqual(m.detect_structure([line("FORM VII", bold=True)], 0, source(), 11, "section")[0], "form")
        self.assertIsNone(m.detect_structure([line("1. Name of applicant", bold=True)], 0, source(), 11, "form"))

    def test_table_row_relationships(self):
        self.assertEqual(m.text_of([line("Crop | Rate\nRice | 2 percent", table=True)]), "Crop | Rate\nRice | 2 percent")

    def test_hyphen_and_contact_preservation(self):
        text = m.text_of([line("multi-state co-"), line("operative societies. Write to officer@example.gov.in.")])
        self.assertIn("multi-state", text)
        self.assertIn("cooperative", text)
        self.assertIn("officer@example.gov.in", text)
        self.assertEqual(m.text_of([line("co\u00ad"), line("operative")]), "cooperative")

    def test_child_before_parent_rejected(self):
        s = source()
        r = m.record_for(s, {}, "TEST_1", [line("Some complete text.")], "child", "missing")
        with self.assertRaises(ValueError):
            m.validate_record(r, s, set(), set(), 1, set())

    def test_unknown_topic_rejected(self):
        s = source()
        r = m.record_for(s, {}, "TEST_1", [line("Some complete text.")], "parent")
        r["topics"] = ["invented"]
        with self.assertRaises(ValueError):
            m.validate_record(r, s, set(), set(), 1, set())

    def test_deterministic_ids_and_context_parent(self):
        lines = [line("22. Membership.—", bold=True), line("The member may apply. " * 25)]
        a = list(m.records_from(m.units_from(lines, source()), source()))
        b = list(m.records_from(m.units_from(lines, source()), source()))
        self.assertEqual(a, b)
        self.assertEqual(a[1][0]["parent_id"], a[0][0]["chunk_id"])
        self.assertNotEqual(a[0][0]["text"], a[1][0]["text"])

    def test_table_and_unstructured_legal_text_retained(self):
        lines = [line("Uncertain legal text " * 1000), line("Field | Value\nName | Applicant", table=True)]
        records = list(m.records_from(m.units_from(lines, source()), source()))
        self.assertTrue(any("Field | Value" in r["text"] for r, _ in records))
        self.assertTrue(any("STRUCTURE_UNCERTAIN" in warnings for _, warnings in records))

    def test_toc_excluded_and_raw_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((40, 40), "CONTENTS")
            for i in range(1, 7):
                page.insert_text((40, 60 + 20 * i), f"{i}. Membership ........ {i + 1}")
            page = doc.new_page()
            page.insert_text((40, 100), "1. Membership. - A member has a duty under this Act.")
            doc.save(path)
            doc.close()
            before = m.digest(path)
            lines, metrics, _ = m.extract_layout(path, source())
            self.assertEqual(metrics["toc_pages_excluded"], 1)
            self.assertEqual(m.digest(path), before)
            self.assertTrue(all(l.page == 2 for l in lines))

    def test_checkpoint_integrity_and_deterministic_aggregation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, "OUT", Path(folder)):
            path = Path(folder) / "test.pdf"
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((40, 100), "22. Membership. - A member may apply under section 45.")
            page.insert_text((40, 120), "The application shall include the required documents and signatures.")
            doc.save(path)
            doc.close()
            s = source()
            paths = m.checkpoint_paths("TEST")
            manifest = m.process_source(s, path, "signature", paths)
            self.assertIsNotNone(m.valid_checkpoint(paths, "signature"))
            self.assertIsNone(m.valid_checkpoint(paths, "changed-input"))
            m.aggregate([s], {"TEST": manifest}, {})
            names = ("documents.jsonl", "extraction_report.csv", "chunk_stats.csv")
            before = {name: m.digest(Path(folder) / name) for name in names}
            m.aggregate([s], {"TEST": manifest}, {})
            self.assertEqual(before, {name: m.digest(Path(folder) / name) for name in names})
            paths[0].write_text("corrupt", encoding="utf-8")
            self.assertIsNone(m.valid_checkpoint(paths, "signature"))

    def test_failed_source_does_not_discard_completed_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(m, "OUT", Path(folder)):
            path = Path(folder) / "test.pdf"
            doc = pymupdf.open()
            doc.new_page().insert_text((40, 100), "22. Membership. - A member may apply.")
            doc.save(path)
            doc.close()
            completed = source()
            failed = {**source(), "source_id": "FAILED"}
            manifest = m.process_source(completed, path, "signature", m.checkpoint_paths("TEST"))
            summary, _ = m.aggregate([completed, failed], {"TEST": manifest}, {"FAILED": "TEST_ERROR"})
            self.assertEqual(summary["ERROR"], 1)
            self.assertEqual(summary["sources_processed"], 1)
            self.assertIsNotNone(m.valid_checkpoint(m.checkpoint_paths("TEST"), "signature"))

    def test_decimal_guideline_hierarchy(self):
        s = source("scheme_guideline")
        lines = [line("12. Claims", bold=True), line("The following procedures apply to insured farmers."),
                 line("12.3 Reporting", bold=True, block=1), line("The insured farmer shall report the loss within the prescribed period.", block=1),
                 line("12.3.1 Documents", bold=True, block=2), line("The report shall include the application and the supporting documents.", block=2)]
        records = [r for r, _ in m.records_from(m.units_from(lines, s), s)]
        by_section = {r["section"]: r for r in records if r["section"]}
        self.assertEqual(by_section['12.3']["parent_id"], by_section['12']["chunk_id"])
        self.assertEqual(by_section['12.3.1']["parent_id"], by_section['12.3']["chunk_id"])
        self.assertEqual(by_section['12.3.1']["heading"], "Reporting")

    def test_numbered_prose_does_not_invent_heading(self):
        detected = m.detect_structure([line("2.10 All data pertaining to crop-wise historical yield data,", bold=True)], 0, source("scheme_guideline"), 11, "heading")
        self.assertEqual(detected, ("heading", "2.10", None))
        wrapped = m.detect_structure([line("3.1 All farmers including sharecroppers and tenant farmers growing the notified crops in", bold=True)], 0, source("scheme_guideline"), 11, "heading")
        self.assertEqual(wrapped, ("heading", "3.1", None))

    def test_ordinal_schedule_retained_as_schedule(self):
        detected = m.detect_structure([line("THE FIRST SCHEDULE", bold=True)], 0, source(), 11, "section")
        self.assertEqual(detected[0], "schedule")


if __name__ == "__main__":
    unittest.main()
