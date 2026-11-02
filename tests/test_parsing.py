import base64
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from core import Store, VisionResult, recognize_images
from parsing import group_blocks, heading_level, parse_document, pending_images


class ParsingTests(unittest.TestCase):
    def test_short_chapters_and_numbered_children(self):
        blocks = []
        def p(text, style=None):
            blocks.append({"kind":"paragraph", "text":text, "level":heading_level(text, style)})
        p("一、需求基础信息")
        blocks.append({"kind":"table", "rows":[["字段","内容"],["需求名称","即时零售到店"]]})
        p("二、需求背景和用户痛点")
        p("背景：",2)
        p("介绍业务背景。",1)
        p("用户痛点：",2)
        p("用户需要到店提货。",1)
        p("三、业务价值和目标")
        p("价值：提升选择自由度。")
        p("目标：支持到店提货。")
        p("四、业务需求")
        for n in range(1,8):
            p(f"4.{n} 功能模块")
            p(f"4.{n}.1 更深一层")
            p("详细的使用角色和规则。",1)
        for title in ("五、验收标准", "六、风险管理", "七、时间线"):
            p(title)
            blocks.append({"kind":"table", "rows":[["事项","说明"],["内容","完整保留"]]})
        units = group_blocks(blocks)
        self.assertEqual(len(units),13)
        self.assertEqual(units[1]["source"],"二、需求背景和用户痛点")
        self.assertIn("背景：",units[1]["text"])
        self.assertIn("用户痛点：",units[1]["text"])
        self.assertIn("4.1 功能模块",units[3]["source"])
        self.assertIn("4.1.1 更深一层",units[3]["text"])
        self.assertEqual(units[0]["blocks"][1]["kind"],"table")
        self.assertFalse(any("段落块" in u["source"] for u in units))
        self.assertEqual(sum(len(u["blocks"]) for u in units),len(blocks))

    def test_wrong_heading_style_on_sentence_is_not_heading(self):
        self.assertIsNone(heading_level("仅提供已上架、有可售库存且符合门店履约要求的商品。",1))

    def test_docx_embedded_image_in_context_and_vision_persistence(self):
        from PIL import Image
        from docx import Document
        image = io.BytesIO()
        Image.new("RGB",(100,50),"white").save(image,format="PNG")
        image.seek(0)
        doc = Document()
        doc.add_heading("一、业务流程",1)
        doc.add_paragraph("下图说明订单流程。")
        doc.add_picture(image)
        doc.add_paragraph("订单完成后进入售后环节。")
        out = io.BytesIO()
        doc.save(out)
        units, notes = parse_document("flow.docx",out.getvalue())
        self.assertEqual(len(pending_images(units)),1)
        self.assertEqual(units[0]["blocks"][2]["kind"],"image")
        class VisionAI:
            provider="fixture"
            model="vision"
            calls=0
            def generate(self,system,prompt,schema,images=None):
                self.calls+=1
                self.assert_image=images[0]["mime"]
                return VisionResult(transcription="提交订单 → 支付 → 门店备货",visual_description="箭头表示三个连续步骤。",limitations="无")
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            doc_id=store.add("flow.docx","",out.getvalue(),units,notes)
            ai=VisionAI()
            recognize_images(store,doc_id,ai)
            saved=Store(directory).get(doc_id)
            self.assertEqual(len(pending_images(saved["parsed"])),0)
            self.assertIn("提交订单",saved["parsed"][0]["text"])
            recognize_images(store,doc_id,ai)
            self.assertEqual(ai.calls,1)
            self.assertEqual(saved["status"],"ready")

    def test_no_silent_drop_on_image_failure(self):
        unit={"source":"流程图","text":"","blocks":[{"kind":"image","label":"图1","text":"","data":"AA==","mime":"image/png","recognized":False}]}
        class BrokenAI:
            provider="fixture"
            model="vision"
            def generate(self,*args,**kwargs):
                raise RuntimeError("offline")
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            doc_id=store.add("scan.pdf","",b"original",[unit],[])
            with self.assertRaises(RuntimeError):
                recognize_images(store,doc_id,BrokenAI())
            self.assertEqual(len(pending_images(store.get(doc_id)["parsed"])),1)
            self.assertEqual(store.get(doc_id)["status"],"failed")

    def test_no_base64_image_data_in_text_chunks(self):
        from core import chunks
        unit={"source":"流程图","text":"文本"*1000,"blocks":[{"kind":"image","data":"secret-image-bytes"}]}
        self.assertNotIn("blocks",chunks([unit])[0][0])

    def test_provider_multimodal_payloads_without_network(self):
        from core import AI
        from unittest.mock import MagicMock
        result=VisionResult(transcription="可读文字",visual_description="箭头",limitations="无")
        image={"mime":"image/png","data":base64.b64encode(b"fixture-image").decode()}
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            client=MagicMock()
            client.__enter__.return_value=client
            client.responses.parse.return_value.output_parsed=result
            with patch("openai.OpenAI",return_value=client):
                answer=AI(store,"openai","test-model","not-a-real-key").generate("system","read image",VisionResult,images=[image])
            payload=client.responses.parse.call_args.kwargs["input"][0]["content"]
            self.assertEqual(payload[1]["type"],"input_image")
            self.assertTrue(payload[1]["image_url"].startswith("data:image/png;base64,"))
            self.assertEqual(answer.transcription,"可读文字")
            client=MagicMock()
            client.__enter__.return_value=client
            client.models.generate_content.return_value.text=result.model_dump_json()
            with patch("google.genai.Client",return_value=client):
                answer=AI(store,"gemini","test-model","not-a-real-key").generate("system","read image",VisionResult,images=[image])
            payload=client.models.generate_content.call_args.kwargs["contents"]
            self.assertEqual(payload[1].inline_data.mime_type,"image/png")
            self.assertEqual(payload[1].inline_data.data,b"fixture-image")
