import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.intelligence.models import Report,Requirement,VisionResult,Answer
from workbench.intelligence.pipeline import project_summary,ask_summary
from workbench.storage.local import LocalStore
from workbench.storage.schema import validate_run
from workbench.documents.parser import parse_document,pending_images,group_blocks,heading_level
from workbench.exports.reports import word,pdf,excel


class FakeAI:
    provider='offline'
    model='fixture'
    def __init__(self):self.calls=[]
    def generate(self,system,prompt,schema,images=None):
        self.calls.append((schema,prompt))
        if schema==VisionResult:return VisionResult(transcription='用户下单 → 支付 → 提货',visual_description='三个节点连续连接',limitations='无')
        if schema==Answer:return Answer(answer='仅依据 Summary 回答。',sources=[])
        requirements=[]
        if '完整梳理以下片段' in prompt:
            group=json.loads(prompt.split('\n',1)[1])
            requirements=[Requirement(module='订单',title='订单规则',description='明确订单处理规则',roles='消费者',scenario='下单',
                rules='按原规则处理',exceptions='未说明',acceptance='未说明',priority='未说明',sources=[group[0]['source']],evidence=group[0]['text'][:12])]
        return Report(title='总结',document_type='PRD',summary='项目与产品的需求概览',background='业务背景',goals='优化体验',users='消费者',
            scope='订单与会员',workflow='下单并提货',metrics='未说明',requirements=requirements)


def generate(store):
    project=store.create_project('数字零售')
    ai=FakeAI()
    marker='RAW_MARKER_NOT_FOR_STORAGE'
    products=[{'name':'会员','documents':[{'name':'会员PRD.txt','raw':(marker+'会员规则正文。').encode()},
        {'name':'积分PRD.txt','raw':'积分处理业务规则正文，测试会员的积分场景。'.encode()}]},
        {'name':'到店','documents':[{'name':'到店BRD.txt','raw':'到店提货支持消费者选择门店，订单完成后可申请售后。'.encode()}]}]
    return project_summary(project,products,ai),ai


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=LocalStore(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_multi_product_multi_document_and_summary_only_storage(self):
        result,ai=generate(self.store)
        self.assertEqual([p['name'] for p in result['report']['products']],['会员','到店'])
        self.assertEqual(len(result['report']['products'][0]['report']['requirements']),2)
        self.assertEqual(len(ai.calls),5)
        self.store.save(result)
        self.store.save(result)
        self.assertEqual(len(LocalStore(self.temp.name).runs()),1)
        text=json.dumps(self.store.runs(),ensure_ascii=False)
        self.assertNotIn('RAW_MARKER_NOT_FOR_STORAGE',text)
        self.assertNotIn('evidence',text)
        self.assertNotIn('parsed',text)
        self.assertFalse((Path(self.temp.name)/'originals').exists())
        self.assertFalse(any(p.suffix in ('.pdf','.docx','.txt') for p in Path(self.temp.name).rglob('*')))

    def test_persistence_rejects_original_fields(self):
        result,_=generate(self.store)
        result['raw']=b'original'
        with self.assertRaises(ValueError):self.store.save(result)
        self.assertEqual(self.store.runs(),[])

    def test_project_isolation_and_history_management(self):
        result,_=generate(self.store)
        self.store.save(result)
        second=self.store.create_project('另一个项目')
        self.assertEqual(self.store.runs(second['id']),[])
        self.store.rename_project(result['project_id'],'重命名项目')
        self.assertTrue(any(p['name']=='重命名项目' for p in self.store.projects()))
        self.assertEqual(self.store.runs()[0]['project_name'],'数字零售')
        self.store.delete_project(result['project_id'])
        self.assertEqual(self.store.runs(),[])

    def test_exports_include_products_without_original_excerpt(self):
        result,_=generate(self.store)
        from docx import Document
        paragraphs='\n'.join(p.text for p in Document(io.BytesIO(word(result))).paragraphs)
        self.assertIn('会员 Summary',paragraphs)
        self.assertIn('到店 Summary',paragraphs)
        self.assertNotIn('RAW_MARKER',paragraphs)
        from pypdf import PdfReader
        self.assertGreater(len(PdfReader(io.BytesIO(pdf(result))).pages),0)
        from openpyxl import load_workbook
        workbook=load_workbook(io.BytesIO(excel(result)))
        self.assertEqual(workbook['需求清单']['A1'].value,'产品')
        self.assertEqual(workbook['需求清单']['A2'].value,'会员')
        self.assertEqual(workbook['需求清单']['A4'].value,'到店')

    def test_duplicate_products_rejected_before_api(self):
        project=self.store.create_project('项目')
        ai=FakeAI()
        with self.assertRaises(ValueError):project_summary(project,[{'name':'产品','documents':[{}]},{'name':'产品','documents':[{}]}],ai)
        self.assertEqual(ai.calls,[])

    def test_question_uses_summary_not_original(self):
        result,ai=generate(self.store)
        answer=ask_summary(result,ai,'有哪些规则？',[])
        self.assertIn('Summary',answer)
        self.assertNotIn('RAW_MARKER',ai.calls[-1][1])

    def test_parse_docx_images_and_table_in_memory(self):
        from docx import Document
        from PIL import Image
        image=io.BytesIO()
        Image.new('RGB',(100,50),'white').save(image,format='PNG')
        image.seek(0)
        doc=Document()
        doc.add_heading('一、业务需求',1)
        table=doc.add_table(rows=1,cols=2)
        table.cell(0,0).text='角色'
        table.cell(0,1).text='消费者'
        doc.add_picture(image)
        raw=io.BytesIO();doc.save(raw)
        units,_=parse_document('prd.docx',raw.getvalue())
        self.assertEqual(len(pending_images(units)),1)
        self.assertIn('角色 | 消费者',units[0]['text'])

    def test_daily_quota(self):
        with patch.dict(os.environ,{'DAILY_CALL_LIMIT':'1'}):
            self.store.reserve_call()
            with self.assertRaises(ValueError):self.store.reserve_call()

    def test_image_recognition_is_not_persisted_as_original_payload(self):
        from docx import Document
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(60,30),'white').save(image,format='PNG');image.seek(0)
        doc=Document();doc.add_heading('一、流程',1);doc.add_picture(image)
        out=io.BytesIO();doc.save(out)
        project=self.store.create_project('图片项目')
        result=project_summary(project,[{'name':'产品','documents':[{'name':'图.docx','raw':out.getvalue()}]}],FakeAI())
        self.store.save(result)
        text=json.dumps(self.store.runs(),ensure_ascii=False)
        self.assertNotIn('image/png',text)
        self.assertNotIn('transcription',text)
        self.assertNotIn('base64',text)

    def test_legacy_result_migration_strips_evidence_and_is_idempotent(self):
        import importlib.util
        script=Path(__file__).resolve().parents[1]/'scripts/migrate_legacy.py'
        spec=importlib.util.spec_from_file_location('legacy_migration',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        old=FakeAI().generate('','完整梳理以下片段\n'+json.dumps([{'source':'正文','text':'RAW_MARKER_旧文档摘录'}]),Report).model_dump()
        rows=[{'id':'12345678123456781234567812345678','name':'旧PRD.pdf','project':'旧项目','created':'2026-11-01T12:00:00+08:00',
            'provider':'old','model':'old','report':old}]
        self.assertEqual(module.migrate(self.store,rows),1)
        self.assertEqual(module.migrate(self.store,rows),0)
        self.assertEqual(len(self.store.projects()),1)
        self.assertNotIn('RAW_MARKER',json.dumps(self.store.runs()))
