import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from github_library import (LibraryService, GitHubStore, GhAPI, LibraryError, UploadPending,
                            render_markdown, normalize_project, parse_properties, blob_sha, HEADINGS)
from library_structure import bootstrap, structure_files

ROOT = Path(__file__).resolve().parents[1]


def sample_project(**changes):
    data = {
        "id": "ps-test-001", "title": "测试项目：不是正式收藏", "category": "website",
        "url": "https://example.com/scout-test", "source_url": "", "github_url": "",
        "tags": ["测试", "temporary"], "pricing": "测试数据，无真实报价", "status": "collected",
        "created": "2026-11-02", "updated": "2026-11-02",
        "usefulness": "这是 Project Scout 的存储链路测试资料，不是一个真实工具的评审，也不会进入主分支的正式收藏。它用于检查结构化资料能否转换为带有 YAML 属性的 Markdown，并验证分类目录、中文标题、段落与链接是否保留。测试会先生成只读预览，取得内容摘要，再模拟明确确认后的新增和修改；重复提交应返回已有记录，网络失败时应保留恢复请求并回读核验。验证通过后会删除本次新建的隔离测试分支，避免在日常收藏中混入无用资料。",
        "examples": ["生成一条测试笔记 → 检查中文与属性", "重复上传 → 确认不产生第二条笔记", "修改说明 → 检查版本冲突保护"],
        "limitations": ["仅为诊断数据，没有真实产品功能", "不能把测试结果当作真实项目评审"],
        "recommendation": "不推荐：仅用于部署验证，不应作为正式收藏。",
        "references": [{"title": "诊断占位地址", "url": "https://example.com/scout-test"}],
    }
    data.update(changes)
    return data


class FakeStore(GitHubStore):
    def __init__(self):
        self.repo = "example-owner/private-library"
        self.branch = "test"
        self.files = {"README.md": "# Existing user README\n"}
        self.writes = 0
        self.snapshots = 0
        self.fail = False
        self.timeout_after_write = False
        self.cannot_read = False
        self.lose_readback = False
        self.head = 0

    def snapshot(self):
        self.snapshots += 1
        if self.cannot_read:
            raise LibraryError("network unavailable")
        return {"head": self.head, "branch": self.branch, "files": {p: {"sha": blob_sha(c), "mode": "100644", "size": len(c.encode())} for p, c in self.files.items()}}

    def read(self, entry):
        if self.cannot_read:
            raise LibraryError("network unavailable")
        return next(c for c in self.files.values() if blob_sha(c) == entry["sha"])

    def commit_files(self, snap, files, message):
        if self.fail or snap["head"] != self.head:
            raise LibraryError("upload failed or concurrent update")
        self.files.update(files)
        self.head += 1
        self.writes += 1
        if self.lose_readback:
            self.cannot_read = True
        if self.timeout_after_write:
            raise LibraryError("response lost after successful commit")
        return str(self.head)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        work = ROOT / "work"
        work.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=work)
        self.store = FakeStore()
        self.outbox = Path(self.tmp.name) / "outbox.db"
        self.service = LibraryService(self.store, self.outbox)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, p=None):
        p = p or sample_project()
        r = self.service.review_project(p)
        return self.service.save_project(p, review_digest=r["review_digest"], confirmation="确认收藏")

    def test_review_and_unconfirmed_are_readonly(self):
        r = self.service.review_project(sample_project())
        self.assertEqual(r["state"], "reviewed_not_saved")
        self.assertFalse(self.outbox.exists())
        for bad in (True, "好", "确认收藏 ", "", "值得收藏"):
            with self.assertRaises(PermissionError):
                self.service.save_project(sample_project(), review_digest=r["review_digest"], confirmation=bad)
        self.assertFalse(self.outbox.exists())
        self.assertEqual(self.store.snapshots, 0)

    def test_changed_content_and_target_need_new_confirmation(self):
        r = self.service.review_project(sample_project())
        with self.assertRaises(PermissionError):
            self.service.save_project(sample_project(title="changed"), review_digest=r["review_digest"], confirmation="确认收藏")
        self.store.branch = "another"
        with self.assertRaises(PermissionError):
            self.service.save_project(sample_project(), review_digest=r["review_digest"], confirmation="确认收藏")
        self.assertFalse(self.outbox.exists())

    def test_add_search_replay(self):
        result = self.save()
        self.assertEqual(result["status"], "created")
        self.assertTrue(result["verified"])
        self.assertEqual(result["revision"], blob_sha(self.store.files[result["path"]]))
        self.assertEqual(self.save()["status"], "existing")
        self.assertEqual(self.store.writes, 1)
        self.assertEqual(len(self.service.search_projects("中文", "website")), 1)

    def test_duplicate_id_does_not_overwrite(self):
        original = self.save()
        result = self.save(sample_project(title="different content"))
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["revision"], original["revision"])
        self.assertEqual(self.store.writes, 1)

    def test_duplicate_website_across_categories(self):
        self.save()
        result = self.save(sample_project(id="other", category="diy", url="http://www.example.com/scout-test/?utm_source=x#intro"))
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(self.store.writes, 1)

    def test_duplicate_github_and_nested_repo_url(self):
        self.save(sample_project(category="github", url="https://github.com/Owner/Repo"))
        result = self.save(sample_project(id="another", category="diy", url="https://example.org", github_url="http://github.com/OWNER/REPO.git/"))
        self.assertEqual(result["status"], "duplicate")
        result = self.save(sample_project(id="third", category="github", url="https://github.com/owner/repo/tree/main"))
        self.assertEqual(result["status"], "duplicate")

    def test_update_preserves_created_and_detects_conflicts(self):
        old = self.save()
        changed = sample_project(title="Updated test")
        r = self.service.review_project(changed, action="update", expected_revision=old["revision"])
        new = self.service.update_project(changed, expected_revision=old["revision"], review_digest=r["review_digest"], confirmation="确认收藏")
        self.assertEqual(new["status"], "updated")
        self.assertEqual(new["path"], old["path"])
        self.assertNotEqual(new["revision"], old["revision"])
        self.assertEqual(self.service.search_projects()[0]["created"], "2026-11-02")
        conflict = sample_project(title="Stale update")
        r = self.service.review_project(conflict, action="update", expected_revision=old["revision"])
        with self.assertRaises(UploadPending):
            self.service.update_project(conflict, expected_revision=old["revision"], review_digest=r["review_digest"], confirmation="确认收藏")
        self.assertEqual(self.store.writes, 2)

    def test_update_duplicate_url_rejected(self):
        a = self.save()
        self.save(sample_project(id="ps-other", url="https://example.org"))
        data = sample_project(url="https://example.org")
        r = self.service.review_project(data, action="update", expected_revision=a["revision"])
        with self.assertRaises(UploadPending):
            self.service.update_project(data, expected_revision=a["revision"], review_digest=r["review_digest"], confirmation="确认收藏")
        self.assertEqual(self.store.writes, 2)

    def test_failure_survives_restart_and_recovers(self):
        self.store.fail = True
        with self.assertRaises(UploadPending) as caught:
            self.save()
        self.assertEqual(len(self.store.files), 1)
        self.store.fail = False
        restarted = LibraryService(self.store, self.outbox)
        self.assertEqual(restarted.recover(caught.exception.request_id)["status"], "created")
        self.assertEqual(self.store.writes, 1)

    def test_timeout_after_commit_verified_without_duplicate(self):
        self.store.timeout_after_write = True
        self.assertEqual(self.save()["status"], "created")
        self.assertEqual(self.store.writes, 1)

    def test_readback_failure_unknown_not_success(self):
        self.store.lose_readback = True
        with self.assertRaises(UploadPending) as caught:
            self.save()
        self.store.cannot_read = False
        self.store.lose_readback = False
        result = self.service.recover(caught.exception.request_id)
        self.assertEqual(result["status"], "existing")
        self.assertEqual(self.store.writes, 1)

    def test_markdown_yaml_properties_and_sections(self):
        text = render_markdown(sample_project(title='含冒号： quote " title', tags=['a:b', '#tag']))
        props = yaml.safe_load(text.split("\n---", 1)[0][4:])
        for key in ("id", "title", "category", "url", "source_url", "tags", "pricing", "status", "created", "updated"):
            self.assertIn(key, props)
        self.assertIsInstance(props["created"], str)
        self.assertEqual(props["tags"], ['a:b', '#tag'])
        for i, heading in enumerate(HEADINGS, 1):
            self.assertIn(f"## {i}. {heading}", text)
        self.assertEqual(parse_properties(text), props)
        self.assertEqual(parse_properties(text.replace("\n", "\r\n")), props)
        self.assertNotIn("评分表", text)

    def test_safe_ids_urls_and_incomplete_review(self):
        for fields in ({"id": "../escape"}, {"url": "file:///C:/secret"}, {"url": "https://example.com/?token=secret"}, {"url": "https://user:pass@example.com"}, {"category": "invalid"}, {"usefulness": ""}, {"examples": []}):
            with self.assertRaises(ValueError):
                self.service.review_project(sample_project(**fields))
        self.assertFalse(self.outbox.exists())

    def test_manual_malformed_note_stops_dedup(self):
        self.store.files["Websites/manual.md"] = "# No YAML"
        with self.assertRaises(UploadPending):
            self.save()
        self.assertEqual(self.store.writes, 0)

    def test_generated_id_stable(self):
        a = normalize_project(sample_project(id="", url="http://www.example.com/scout-test/?utm_source=x"))
        b = normalize_project(sample_project(id="", url="https://example.com/scout-test"))
        self.assertEqual(a["id"], b["id"])

    def test_three_categories_route_to_separate_folders(self):
        for cat, folder in (("github", "GitHub-Projects"), ("website", "Websites"), ("diy", "DIY-Projects")):
            data = sample_project(id="ps-" + cat, category=cat, url="https://github.com/test/repo" if cat == "github" else "https://example.com/" + cat)
            result = self.save(data)
            self.assertEqual(result["path"], f"{folder}/ps-{cat}.md")
            self.assertEqual(len(self.service.search_projects(category=cat)), 1)

    def test_recovery_cannot_change_target(self):
        result = self.save()
        self.store.branch = "changed"
        with self.assertRaises(PermissionError):
            self.service.recover(result["request_id"])

    def test_concurrent_edit_is_not_overwritten(self):
        original = self.save()
        changed = sample_project(title="Desired new title")
        r = self.service.review_project(changed, action="update", expected_revision=original["revision"])
        real_commit = self.store.commit_files
        def racing_commit(snap, files, message):
            self.store.files[original["path"]] = render_markdown(sample_project(title="Phone edit"))
            self.store.head += 1
            return real_commit(snap, files, message)
        self.store.commit_files = racing_commit
        with self.assertRaises(UploadPending):
            self.service.update_project(changed, expected_revision=original["revision"], review_digest=r["review_digest"], confirmation="确认收藏")
        self.assertIn("Phone edit", self.store.files[original["path"]])
        self.assertEqual(self.store.writes, 1)

    def test_scaffold_preserves_existing_content(self):
        self.store.files["Home.md"] = "My custom home"
        result = bootstrap(self.store)
        self.assertEqual(self.store.files["Home.md"], "My custom home")
        self.assertTrue(self.store.files["README.md"].startswith("# Existing user README"))
        self.assertIn("Templates/diy.md", self.store.files)
        self.assertEqual(bootstrap(self.store)["status"], "existing")


class TransportTests(unittest.TestCase):
    def test_private_and_account_guards(self):
        class API:
            def __init__(self, login="example-owner", private=False):
                self.login, self.private = login, private
            def request(self, method, endpoint, payload=None):
                return {"login": self.login} if endpoint == "user" else {"private": self.private, "full_name": "example-owner/private-library"}
        for api in (API(), API(login="wrong", private=True)):
            with self.assertRaises(LibraryError):
                GitHubStore(api, repository="example-owner/private-library").metadata()

    def test_atomic_commit_uses_base_tree_parent_no_force(self):
        class API:
            def __init__(self): self.calls = []
            def request(self, method, endpoint, payload=None):
                self.calls.append((method, endpoint, payload))
                if endpoint == "user": return {"login": "example-owner"}
                if endpoint == "repos/example-owner/private-library":
                    return {"private": True, "full_name": "example-owner/private-library"}
                return {"sha": "new-sha"}
        api = API()
        store = GitHubStore(api, repository="example-owner/private-library")
        store.commit_files({"head": "parent", "tree": "old-tree", "branch": "main"}, {"Websites/test.md": "hello"}, "test")
        self.assertEqual(api.calls[-1][2], {"sha": "new-sha", "force": False})
        self.assertEqual(api.calls[-2][2]["parents"], ["parent"])
        self.assertEqual(api.calls[-3][2]["base_tree"], "old-tree")

    def test_gh_api_stdin_not_shell_and_no_secret_echo(self):
        import subprocess
        ok = subprocess.CompletedProcess([], 0, '{"ok":true}', '')
        with patch("github_library.subprocess.run", return_value=ok) as run:
            self.assertEqual(GhAPI("gh.exe").request("POST", "test", {"note": "private"}), {"ok": True})
            args, kwargs = run.call_args
            self.assertIsInstance(args[0], list)
            self.assertNotIn("shell", kwargs)
            self.assertIn("--input", args[0])
        bad = subprocess.CompletedProcess([], 1, '', 'HTTP 403 secret-value')
        with patch("github_library.subprocess.run", return_value=bad):
            with self.assertRaises(LibraryError) as e:
                GhAPI("gh.exe").request("GET", "test")
            self.assertNotIn("secret-value", str(e.exception))


if __name__ == "__main__":
    unittest.main()
