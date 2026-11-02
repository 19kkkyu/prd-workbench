import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from core import Answer, Report, Requirement, Store, analyze, ask, chunks, parse_document
from exports import excel, pdf, word


def sample_report(source="第1页", evidence="订单完成后七天内可以申请退款。"):
    return Report(title="售后需求梳理", document_type="PRD", summary="梳理退款规则。", background="改善售后体验。",
        goals="明确退款条件。", users="消费者", scope="订单退款", workflow="申请退款后审核。", metrics="未说明",
        requirements=[Requirement(module="退款", title="申请退款", description=evidence, roles="消费者",
            scenario="订单已完成", rules="七天内申请", exceptions="未说明", acceptance="未说明", priority="未说明",
            sources=[source], evidence=evidence)])


class FakeAI:
    provider = "offline-test"
    model = "fixture"

    def __init__(self, report=None, fail=False):
        self.report = report or sample_report()
        self.fail = fail
        self.count = 0

    def generate(self, system, prompt, schema):
        self.count += 1
        if self.fail:
            raise RuntimeError("offline failure")
        if schema == Answer:
            return Answer(answer="订单完成后七天内可以申请退款。", sources=["第1页"])
        return self.report.model_copy(deep=True)


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.units = [{"source":"第1页", "text":"订单完成后七天内可以申请退款。退款需由消费者本人发起。"}]
        self.doc_id = self.store.add("售后PRD.pdf", "售后", b"fixture", self.units, [])

    def tearDown(self):
        self.temp.cleanup()

    def test_durable_analysis_and_exports(self):
        analyze(self.store, self.doc_id, FakeAI())
        reopened = Store(self.temp.name)
        doc = reopened.get(self.doc_id)
        self.assertEqual(doc["status"], "done")
        self.assertEqual(doc["report"]["coverage"]["characters"], len(self.units[0]["text"]))
        from docx import Document
        self.assertIn("退款", "\n".join(p.text for p in Document(io.BytesIO(word(doc))).paragraphs))
        from pypdf import PdfReader
        self.assertGreaterEqual(len(PdfReader(io.BytesIO(pdf(doc))).pages), 1)
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(excel(doc)))
        self.assertEqual(workbook["需求清单"]["A2"].value, "REQ-001")

    def test_failed_retry_preserves_previous_report(self):
        analyze(self.store, self.doc_id, FakeAI())
        with self.assertRaises(RuntimeError):
            analyze(self.store, self.doc_id, FakeAI(fail=True))
        doc = self.store.get(self.doc_id)
        self.assertEqual(doc["status"], "failed")
        self.assertTrue(doc["report"])

    def test_invalid_source_and_invented_quote_rejected(self):
        for report in [sample_report("第99页"), sample_report(evidence="原文完全没有的句子")]:
            with self.assertRaises(ValueError):
                analyze(self.store, self.doc_id, FakeAI(report))
            self.assertEqual(self.store.get(self.doc_id)["status"], "failed")

    def test_lease_excludes_concurrent_workers(self):
        def claim(_):
            try:
                return self.store.claim(self.doc_id, "test", "model")
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(4)))
        self.assertEqual(sum(x is not None for x in results), 1)
        with self.assertRaises(ValueError):
            self.store.delete(self.doc_id)

    def test_character_chunking_no_loss(self):
        units = [{"source":"第1页", "text":"甲乙丙丁" * 11000}, {"source":"第2页", "text":"末尾规则" * 700}]
        result = chunks(units, 1000)
        self.assertEqual("".join(p["text"] for g in result for p in g), "".join(u["text"] for u in units))
        self.assertTrue(all(sum(len(p["text"]) for p in g) <= 1000 for g in result))

    def test_multi_chunk_retains_all_requirements(self):
        units = [{"source":"第1页", "text":self.units[0]["text"] * 1000}]
        doc_id = self.store.add("long.txt", "", b"long", units, [])
        ai = FakeAI()
        with patch.dict(os.environ, {"CHUNK_CHARS":"1000"}):
            # Use same verifiable excerpt at every chunk boundary.
            class ChunkAI(FakeAI):
                def generate(self, system, prompt, schema):
                    self.count += 1
                    if "以下是" in prompt:
                        return sample_report()
                    group = json.loads(prompt[prompt.index("\n")+1:])
                    text = group[0]["text"][:10]
                    return sample_report(evidence=text)
            result = analyze(self.store, doc_id, ChunkAI())
        self.assertEqual(len(result["requirements"]), result["coverage"]["chunks"])
        self.assertEqual(result["requirements"][-1]["id"], f"REQ-{len(result['requirements']):03d}")

    def test_docx_tables_and_paragraph_order(self):
        from docx import Document
        doc = Document()
        doc.add_heading("退款", 1)
        doc.add_paragraph("订单完成后七天内可以申请退款。")
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "角色"
        table.cell(0, 1).text = "消费者"
        doc.add_paragraph("超过期限不支持。")
        out = io.BytesIO()
        doc.save(out)
        parsed, _ = parse_document("prd.docx", out.getvalue())
        self.assertEqual(len(parsed), 1)
        self.assertIn("角色 | 消费者", parsed[0]["text"])
        self.assertEqual(parsed[0]["blocks"][-1]["text"], "超过期限不支持。")

    def test_pdf_and_empty_scan(self):
        from reportlab.pdfgen.canvas import Canvas
        out = io.BytesIO()
        c = Canvas(out)
        c.drawString(30, 700, "Order refund is available within seven days.")
        c.save()
        parsed, _ = parse_document("prd.pdf", out.getvalue())
        self.assertEqual(parsed[0]["source"], "第1页")
        out = io.BytesIO()
        c = Canvas(out)
        c.showPage()
        c.save()
        parsed, notes = parse_document("scan.pdf", out.getvalue())
        from parsing import pending_images
        self.assertEqual(len(pending_images(parsed)), 1)

    def test_question_history_and_delete(self):
        analyze(self.store, self.doc_id, FakeAI())
        ask(self.store, self.store.get(self.doc_id), FakeAI(), "退款时限？")
        self.assertEqual(len(self.store.messages(self.doc_id)), 1)
        self.store.delete(self.doc_id)
        self.assertFalse((self.store.root / "originals" / self.doc_id).exists())
        self.assertEqual(self.store.messages(self.doc_id), [])

    def test_quota_atomic(self):
        with patch.dict(os.environ, {"DAILY_CALL_LIMIT":"2"}):
            self.store.reserve_call()
            self.store.reserve_call()
            with self.assertRaises(ValueError):
                self.store.reserve_call()

    def test_excel_formula_injection_is_plain_text(self):
        analyze(self.store, self.doc_id, FakeAI())
        doc = self.store.get(self.doc_id)
        doc["report"]["requirements"][0]["title"] = '=HYPERLINK("https://example.com")'
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(excel(doc)))
        self.assertEqual(wb["需求清单"]["C2"].data_type, "s")


if __name__ == "__main__":
    unittest.main()
