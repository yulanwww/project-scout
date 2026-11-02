import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from collector import ToolRepository

class AppTests(unittest.TestCase):
    def test_create_search_edit_delete(self):
        root = Path(__file__).resolve().parents[1]
        work = root / "work"
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            repo = ToolRepository(Path(tmp) / "ui.db")
            with patch("collector.ToolRepository", return_value=repo):
                app = AppTest.from_file(str(root / "app.py")).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                next(w for w in app.text_input if w.label == "工具名称").set_value("UI Test")
                next(b for b in app.button if b.label == "保存工具").click()
                app.run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(repo.search()), 1)
                next(w for w in app.text_input if w.label == "工具名称").set_value("UI Updated")
                next(b for b in app.button if b.label == "保存工具").click()
                app.run(timeout=30)
                self.assertEqual(len(repo.search("Updated")), 1)
                app.checkbox[0].check()
                app.run(timeout=30)
                next(b for b in app.button if b.label == "删除工具").click()
                app.run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(repo.search(), [])
