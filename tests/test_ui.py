import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workbench.storage.local import LocalStore
from test_summary import generate


class UITests(unittest.TestCase):
    def test_home_results_and_history_are_separate(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'STORAGE_BACKEND':'local','DATA_DIR':directory,'OPENAI_API_KEY':'','GEMINI_API_KEY':''}):
            st.cache_resource.clear()
            store=LocalStore(directory)
            result,_=generate(store)
            store.save(result)
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertFalse(any(b.label in ('删除 Summary','删除项目及全部 Summary','下载原始文件') for b in app.button))
            self.assertFalse(any(x.label=='定位原文' for x in app.selectbox))
            self.assertFalse(any(x.value=='项目总 Summary' for x in app.tabs))
            app.radio[0].set_value('历史记录').run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertTrue(any(b.label=='删除 Summary' for b in app.button))
            self.assertTrue(any('会员' in str(x.options) for x in app.selectbox if x.label=='查看需求详情'))
            next(b for b in app.button if b.label=='生成 Word / PDF / Excel').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            app.radio[0].set_value('使用说明').run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            st.cache_resource.clear()

    def test_project_creation_and_product_controls(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'STORAGE_BACKEND':'local','DATA_DIR':directory,'OPENAI_API_KEY':'','GEMINI_API_KEY':''}):
            st.cache_resource.clear()
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
            app.text_input[0].set_value('项目一')
            next(b for b in app.button if b.label=='创建项目').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertEqual(len(LocalStore(directory).projects()),1)
            next(b for b in app.button if b.label=='＋ 添加产品').click().run()
            self.assertEqual(len(app.exception),0,str(app.exception))
            self.assertTrue(any(x.label=='产品 2 名称' for x in app.text_input))
            st.cache_resource.clear()
