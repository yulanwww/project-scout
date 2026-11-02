import json
import tempfile
import unittest
from pathlib import Path
from collector import ToolRepository, DuplicateTool

WORK = Path(__file__).resolve().parents[1] / "work"

class RepositoryTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.repo = ToolRepository(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_query_persistence(self):
        i = self.repo.add({"name": "工具 Alpha", "purpose": "整理笔记", "tags": ["Agent", "学习"]})
        self.assertEqual(self.repo.get(i)["tags"], "Agent, 学习")
        self.assertEqual(self.repo.search("笔记")[0]["id"], i)
        self.assertEqual(len(self.repo.search("ALPHA")), 1)
        self.assertEqual(ToolRepository(self.repo.path).get(i)["name"], "工具 Alpha")

    def test_update_and_delete(self):
        i = self.repo.add({"name": "Alpha", "category": "研究"})
        self.repo.update(i, {"description": "新介绍"})
        self.assertEqual(self.repo.get(i)["description"], "新介绍")
        self.assertEqual(len(self.repo.search(category="研究")), 1)
        self.assertTrue(self.repo.delete(i))
        self.assertIsNone(self.repo.get(i))
        with self.assertRaises(ValueError):
            self.repo.update(i, {"name": "Missing"})

    def test_duplicate_names(self):
        self.repo.add({"name": "ＡＬＰＨＡ  Agent"})
        with self.assertRaises(DuplicateTool):
            self.repo.add({"name": "alpha agent"})

    def test_duplicate_links(self):
        self.repo.add({"name": "First", "website": "http://www.example.com/tool/?utm_source=red#intro", "github": "https://github.com/Owner/Repo.git"})
        for fields in ({"website": "https://example.com/tool"}, {"github": "https://github.com/owner/repo/"}):
            with self.assertRaises(DuplicateTool):
                self.repo.add({"name": "Alias", **fields})

    def test_update_duplicate_keeps_original(self):
        self.repo.add({"name": "First"})
        i = self.repo.add({"name": "Second"})
        with self.assertRaises(DuplicateTool):
            self.repo.update(i, {"name": "FIRST"})
        self.assertEqual(self.repo.get(i)["name"], "Second")

    def test_import_duplicates_and_repeat(self):
        content = json.dumps([{"name": "A"}, {"name": "a"}, {"name": "B"}])
        self.assertEqual(self.repo.import_json(content), {"added": 2, "duplicates": 1})
        self.assertEqual(self.repo.import_json(content), {"added": 0, "duplicates": 3})
        self.assertEqual(self.repo.import_json('{"name":"C"}')["added"], 1)

    def test_invalid_batch_is_atomic(self):
        for payload in ([{"name": "Good"}, {"name": ""}], [{"name": "Bad", "website": "javascript:alert(1)"}], [{"name": "Bad", "collected_date": "bad"}], [{"name": "Bad", "tags": [1]}]):
            with self.assertRaises(ValueError):
                self.repo.import_json(json.dumps(payload))
            self.assertEqual(self.repo.search(), [])
        with self.assertRaises(ValueError):
            self.repo.import_json("null")

    def test_search_literal_and_validation(self):
        self.repo.add({"name": "100% Agent"})
        self.assertEqual(len(self.repo.search("%")), 1)
        self.assertEqual(self.repo.search("' OR 1=1 --"), [])
        with self.assertRaises(ValueError):
            self.repo.add({"name": "Bad", "unexpected": "x"})

if __name__ == "__main__":
    unittest.main()
