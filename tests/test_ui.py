import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store, analyze
from test_workbench import FakeAI


class InterfaceTests(unittest.TestCase):
    def test_pages_history_and_export_without_api(self):
        from streamlit.testing.v1 import AppTest
        import streamlit as st
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "DATA_DIR":directory, "OPENAI_API_KEY":"", "GEMINI_API_KEY":""
        }):
            st.cache_resource.clear()
            store = Store(directory)
            doc_id = store.add("测试退款PRD.pdf", "会员", b"fixture", [
                {"source":"第1页", "text":"订单完成后七天内可以申请退款。退款由消费者本人发起。"}], [])
            analyze(store, doc_id, FakeAI())
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
            app.run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertFalse(any(x.label in ("选择服务","模型名称","仅当前会话使用的 API Key") for x in list(app.text_input)+list(app.selectbox)))
            self.assertTrue(any("七天" in str(x.value) for x in app.markdown))
            export_button = next(b for b in app.button if b.label == "生成 Word / PDF / Excel")
            export_button.click().run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            app.radio[0].set_value("历史记录").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            self.assertTrue(any("历史记录" in x.value for x in app.title))
            app.radio[0].set_value("使用说明").run()
            self.assertEqual(len(app.exception), 0, str(app.exception))
            st.cache_resource.clear()


if __name__ == "__main__":
    unittest.main()
