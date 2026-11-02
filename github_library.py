"""Private GitHub Markdown library. No HTTP server and no embedded credentials."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import date
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode

import yaml
from config import ROOT, configured_branch, configured_repository, project_path

FOLDERS = {"github": "GitHub-Projects", "website": "Websites", "diy": "DIY-Projects"}
HEADINGS = ("有什么用？", "收费情况", "能做什么有意义的事？", "有什么不足？", "收藏建议", "官方网站与参考链接")


class LibraryError(RuntimeError):
    pass


class UploadPending(LibraryError):
    def __init__(self, request_id, state):
        self.request_id, self.state = request_id, state
        super().__init__(f"未确认保存成功：{state}；恢复请求 {request_id}")


def canonical_url(value, repository=False):
    if not value:
        return ""
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("链接格式错误")
    p = urlsplit(value.strip())
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise ValueError("仅接受无内嵌凭据的 HTTP/HTTPS 链接")
    host = p.hostname.casefold().removeprefix("www.")
    port = p.port
    if port and port not in (80, 443):
        host += f":{port}"
    path = p.path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not k.casefold().startswith("utm_") and k.casefold() not in ("fbclid", "gclid")))
    if p.hostname.casefold().removeprefix("www.") == "github.com":
        segments = path.strip("/").split("/")
        if len(segments) >= 2:
            path = "/" + "/".join(segments[:2]).casefold().removesuffix(".git")
        query = ""
        if repository and len(segments) < 2:
            raise ValueError("GitHub 地址需要 owner/repository")
    elif repository:
        raise ValueError("github_url 必须为 github.com 仓库地址")
    return urlunsplit(("https", host, path, query, ""))


def normalize_project(data):
    if not isinstance(data, dict):
        raise ValueError("项目必须为对象")
    allowed = {"id", "title", "category", "url", "github_url", "source_url", "tags", "pricing", "status", "created", "updated", "usefulness", "examples", "limitations", "recommendation", "references"}
    if set(data) - allowed:
        raise ValueError("未知项目字段：" + ", ".join(sorted(set(data) - allowed)))
    p = {k: data.get(k, "") for k in allowed}
    for k in ("title", "category", "url", "github_url", "source_url", "pricing", "status", "created", "updated", "usefulness", "recommendation", "id"):
        if not isinstance(p[k], str):
            raise ValueError(k + " 必须为字符串")
        p[k] = p[k].strip()
    if not p["title"] or len(p["title"]) > 200 or "\n" in p["title"]:
        raise ValueError("title 必须为单行非空名称，最长 200 字")
    if p["category"] not in FOLDERS:
        raise ValueError("category 必须为 github、website 或 diy")
    if not p["url"]:
        p["url"] = p["github_url"]
    canonical_url(p["url"])
    if not p["url"]:
        raise ValueError("必须提供官网或原项目 url")
    if p["category"] == "github" and not p["github_url"]:
        p["github_url"] = canonical_url(p["url"], repository=True)
    if p["github_url"]:
        p["github_url"] = canonical_url(p["github_url"], repository=True)
    canonical_url(p["source_url"])
    # Do not store credential-bearing query strings even in a private repository.
    for k in ("url", "github_url", "source_url"):
        if any(re.search(r"token|password|secret|api.?key|signature|authorization", name, re.I) for name, _ in parse_qsl(urlsplit(p[k]).query)):
            raise ValueError("链接包含可能的凭据参数，请移除后再收藏")
    if not p["id"]:
        p["id"] = "ps-" + hashlib.sha256(canonical_url(p["github_url"] or p["url"]).encode()).hexdigest()[:24]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", p["id"]):
        raise ValueError("id 仅可包含字母、数字、下划线或连字符，最长 80 字")
    for k in ("created", "updated"):
        p[k] = p[k] or date.today().isoformat()
        date.fromisoformat(p[k])
    if p["updated"] < p["created"]:
        raise ValueError("updated 不能早于 created")
    p["pricing"] = p["pricing"] or "待确认"
    p["status"] = p["status"] or "collected"
    for k, lo, hi in (("tags", 0, 30), ("examples", 3, 4), ("limitations", 2, 3)):
        v = data.get(k, [])
        if not isinstance(v, list) or not lo <= len(v) <= hi or not all(isinstance(x, str) and x.strip() for x in v):
            raise ValueError(f"{k} 需要 {lo}–{hi} 个非空字符串")
        p[k] = list(dict.fromkeys(x.strip() for x in v))
        if len(p[k]) < lo:
            raise ValueError(k + " 存在重复项")
    if not p["usefulness"] or not p["recommendation"]:
        raise ValueError("需要完成评审：usefulness 和 recommendation 必填")
    refs = data.get("references", [])
    if not isinstance(refs, list) or len(refs) > 12:
        raise ValueError("references 必须是最多 12 项的数组")
    p["references"] = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"title", "url"} or not isinstance(ref["title"], str) or not ref["title"].strip():
            raise ValueError("参考资料需要 title 和 url")
        if not canonical_url(ref["url"]):
            raise ValueError("参考链接不能为空")
        if any(re.search(r"token|password|secret|api.?key|signature", k, re.I) for k, _ in parse_qsl(urlsplit(ref["url"]).query)):
            raise ValueError("参考链接包含可能的凭据")
        p["references"].append(dict(ref))
    if len(json.dumps(p, ensure_ascii=False)) > 100_000:
        raise ValueError("单条收藏过大")
    return p


def render_markdown(project):
    p = normalize_project(project)
    properties = {k: p[k] for k in ("id", "title", "category", "url", "source_url", "tags", "pricing", "status", "created", "updated", "github_url")}
    # Quoted JSON scalars/lists are valid YAML, avoiding implicit dates and injection.
    front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in properties.items())
    refs = [p["url"]] + ([p["github_url"]] if p["github_url"] else []) + [r["url"] for r in p["references"]]
    sections = [p["usefulness"], p["pricing"], "\n".join(f"- {x}" for x in p["examples"]), "\n".join(f"- {x}" for x in p["limitations"]), p["recommendation"], "\n".join(f"- <{u}>" for u in dict.fromkeys(refs))]
    title = re.sub(r"[\r\n]", " ", p["title"])
    return f"---\n{front}\n---\n\n# {title}\n\n" + "\n\n".join(f"## {i}. {h}\n\n{v}" for i, (h, v) in enumerate(zip(HEADINGS, sections), 1)) + "\n"


def parse_properties(text):
    text = text.lstrip("\ufeff")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise LibraryError("收藏笔记缺少 YAML Properties；请先补全，未写入任何收藏")
    try:
        props = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise LibraryError("收藏笔记 YAML 无效；请先修复") from exc
    if not isinstance(props, dict):
        raise LibraryError("YAML Properties 必须为对象")
    return props


def blob_sha(text):
    raw = text.encode("utf-8")
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class GhAPI:
    def __init__(self, executable=None):
        self.executable = str(executable or shutil.which("gh") or "gh")

    def request(self, method, endpoint, payload=None):
        args = [self.executable, "api", "--hostname", "github.com", "--method", method, endpoint, "-H", "Accept: application/vnd.github+json"]
        if payload is not None:
            args += ["--input", "-"]
        env = os.environ.copy()
        try:
            result = subprocess.run(args, input=json.dumps(payload) if payload is not None else "", capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LibraryError("GitHub 请求失败或超时；请检查 gh 登录与网络") from exc
        if result.returncode:
            # Do not echo arbitrary stderr or request bodies: they may contain private data.
            status = re.search(r"HTTP (\d{3})", result.stderr)
            raise LibraryError("GitHub API 失败" + (f"（HTTP {status[1]}）" if status else "；检查登录、网络或权限"))
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except ValueError as exc:
            raise LibraryError("GitHub 返回了无法识别的响应") from exc


class GitHubStore:
    def __init__(self, api=None, branch=None, repository=None):
        self.api = api or GhAPI()
        # Bind confirmation to a concrete branch; do not silently follow a changed default.
        self.branch = branch or configured_branch()
        self.repo = repository or configured_repository()

    def endpoint(self, suffix=""):
        return f"repos/{self.repo}" + ("/" + suffix if suffix else "")

    def metadata(self):
        user = self.api.request("GET", "user")
        expected_owner = self.repo.split("/", 1)[0]
        if user.get("login", "").casefold() != expected_owner.casefold():
            raise LibraryError("gh 当前账号与目标仓库所有者不符，停止操作")
        meta = self.api.request("GET", self.endpoint())
        if meta.get("private") is not True or meta.get("full_name", "").casefold() != self.repo.casefold():
            raise LibraryError("目标仓库不是配置的私人仓库，停止操作")
        return meta

    def snapshot(self):
        meta = self.metadata()
        branch = self.branch or meta["default_branch"]
        head = self.api.request("GET", self.endpoint("git/ref/heads/" + quote(branch, safe="")))["object"]["sha"]
        commit = self.api.request("GET", self.endpoint("git/commits/" + head))
        tree = self.api.request("GET", self.endpoint("git/trees/" + commit["tree"]["sha"] + "?recursive=1"))
        if tree.get("truncated"):
            raise LibraryError("仓库目录过大，无法完整查重，停止写入")
        return {"branch": branch, "head": head, "tree": commit["tree"]["sha"], "files": {e["path"]: e for e in tree["tree"] if e["type"] == "blob"}}

    def read(self, entry):
        if entry.get("size", 0) > 1_000_000 or entry.get("mode", "100644") not in ("100644", "100755"):
            raise LibraryError("不支持过大文件或符号链接")
        blob = self.api.request("GET", self.endpoint("git/blobs/" + entry["sha"]))
        if blob.get("encoding") != "base64":
            raise LibraryError("不支持的文件编码")
        raw = base64.b64decode(blob["content"])
        if len(raw) > 1_000_000:
            raise LibraryError("笔记超过大小限制")
        text = raw.decode("utf-8")
        if blob_sha(text) != entry["sha"]:
            raise LibraryError("GitHub 文件 SHA 校验失败")
        return text

    def notes(self, snap):
        result = []
        for path, entry in snap["files"].items():
            if path.split("/", 1)[0] in FOLDERS.values() and path.endswith(".md"):
                content = self.read(entry)
                props = parse_properties(content)
                # A malformed existing note must never be silently ignored by deduplication.
                if not props.get("id") or not props.get("url"):
                    raise LibraryError("已有收藏缺少 id/url，需先修复：" + path)
                result.append({"path": path, "revision": entry["sha"], "properties": props, "content": content})
        return result

    def commit_files(self, snap, files, message):
        self.metadata()  # fail closed if visibility or account changed since the read
        entries = []
        for path, content in files.items():
            if path.startswith(("/", "\\")) or ".." in path.split("/"):
                raise ValueError("不安全的仓库路径")
            blob = self.api.request("POST", self.endpoint("git/blobs"), {"content": content, "encoding": "utf-8"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self.api.request("POST", self.endpoint("git/trees"), {"base_tree": snap["tree"], "tree": entries})
        commit = self.api.request("POST", self.endpoint("git/commits"), {"message": message, "tree": tree["sha"], "parents": [snap["head"]]})
        self.api.request("PATCH", self.endpoint("git/refs/heads/" + quote(snap["branch"], safe="")), {"sha": commit["sha"], "force": False})
        return commit["sha"]


def identity_keys(props):
    return {canonical_url(str(props.get(k) or ""), repository=k == "github_url") for k in ("url", "github_url")} - {""}


class LibraryService:
    """Transport-neutral save/search/update interface. Adapter must authenticate human consent."""
    def __init__(self, store=None, outbox=None):
        self.store = store or GitHubStore()
        self.outbox = Path(outbox) if outbox else project_path("PROJECT_SCOUT_STATE_DIR", ".local") / "github-outbox.db"

    def review_project(self, project, *, action="save", expected_revision=""):
        """Pure preview; no database, GitHub or file writes. Digest binds action and target."""
        if action not in ("save", "update"):
            raise ValueError("action 错误")
        if action == "update" and not re.fullmatch(r"[a-f0-9]{40}", expected_revision):
            raise ValueError("更新必须提供当前笔记 revision")
        p = normalize_project(project)
        envelope = {"project": p, "action": action, "expected_revision": expected_revision, "repository": self.store.repo, "branch": self.store.branch or "<default>"}
        digest = hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {**envelope, "review_digest": digest, "markdown": render_markdown(p), "state": "reviewed_not_saved"}

    @contextmanager
    def _db(self):
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.outbox, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, envelope TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
                yield db
        finally:
            db.close()

    def save_project(self, project, *, review_digest, confirmation):
        return self._confirm(project, review_digest, confirmation, "save", "")

    def update_project(self, project, *, expected_revision, review_digest, confirmation):
        return self._confirm(project, review_digest, confirmation, "update", expected_revision)

    def _confirm(self, project, digest, confirmation, action, revision):
        # Check before ANY persistence or network write. A model-supplied bool is not consent.
        if confirmation != "确认收藏":
            raise PermissionError("只有用户明确确认收藏后才可写入")
        reviewed = self.review_project(project, action=action, expected_revision=revision)
        if reviewed["review_digest"] != digest:
            raise PermissionError("评审内容、目标或操作发生变化，必须重新展示并确认收藏")
        envelope = {k: reviewed[k] for k in ("project", "action", "expected_revision", "repository", "branch")}
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO requests VALUES (?, ?, 'confirmed_pending', NULL)", (digest, json.dumps(envelope, ensure_ascii=False)))
        return self.recover(digest)

    def _state(self, request_id, state, result=None):
        with self._db() as db:
            db.execute("UPDATE requests SET state=?,result=? WHERE id=?", (state, json.dumps(result, ensure_ascii=False) if result else None, request_id))

    def recover(self, request_id):
        if not self.outbox.exists():
            raise ValueError("没有已确认的恢复请求")
        with self._db() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise ValueError("恢复请求不存在")
        e = json.loads(row["envelope"])
        if e["repository"] != self.store.repo or e["branch"] != (self.store.branch or "<default>"):
            raise PermissionError("恢复目标与原确认不同")
        try:
            return self._execute(request_id, e)
        except (LibraryError, OSError, ValueError, KeyError) as exc:
            self._state(request_id, "failed_or_unknown")
            raise UploadPending(request_id, "failed_or_unknown") from exc

    def _execute(self, request_id, e):
        p = e["project"]
        snap = self.store.snapshot()
        notes = self.store.notes(snap)
        same = [n for n in notes if str(n["properties"]["id"]) == p["id"]]
        if len(same) > 1:
            raise LibraryError("发现多个同 ID 收藏，请人工整理")
        wanted = render_markdown(p)
        if same and same[0]["content"] == wanted:
            result = self._result("existing", same[0], request_id, verified=True)
            self._state(request_id, "verified", result)
            return result
        matches = [n for n in notes if identity_keys(n["properties"]) & identity_keys(p)]
        if e["action"] == "save" and (same or matches):
            result = self._result("duplicate", (same or matches)[0], request_id, verified=True)
            self._state(request_id, "duplicate", result)
            return result
        if e["action"] == "update":
            if not same:
                raise LibraryError("要修改的收藏不存在")
            current = same[0]
            if current["revision"] != e["expected_revision"]:
                raise LibraryError("收藏已在别处修改，请重新评审差异并确认，未覆盖")
            if any(n["path"] != current["path"] for n in matches):
                raise LibraryError("更新后的链接与其他收藏重复")
            if str(current["properties"].get("created")) != p["created"]:
                raise LibraryError("更新不可改变创建日期")
            if current["properties"].get("category") != p["category"]:
                raise LibraryError("本版不自动迁移分类，请保留原分类，避免遗留重复笔记")
            path = current["path"]
        else:
            path = FOLDERS[p["category"]] + "/" + p["id"] + ".md"
            if path in snap["files"]:
                raise LibraryError("目标文件已存在，拒绝覆盖")
        try:
            self.store.commit_files(snap, {path: wanted}, "Project Scout: " + e["action"] + " " + p["id"])
        except LibraryError:
            # The server may have accepted a commit despite a timeout. Verify before retry.
            check = self.store.snapshot()
            entry = check["files"].get(path)
            if not entry or self.store.read(entry) != wanted:
                raise
        checked = self.store.snapshot()
        entry = checked["files"].get(path)
        if not entry or self.store.read(entry) != wanted:
            raise LibraryError("写入回读不一致，结果未知")
        result = self._result("created" if e["action"] == "save" else "updated", {"path": path, "revision": entry["sha"], "properties": p}, request_id, verified=True)
        self._state(request_id, "verified", result)
        return result

    def _result(self, status, note, request_id, verified):
        return {"status": status, "id": note["properties"]["id"], "path": note["path"], "revision": note["revision"], "request_id": request_id, "verified": verified, "repository": self.store.repo, "branch": self.store.branch or "<default>"}

    def search_projects(self, query="", category=""):
        if category and category not in FOLDERS:
            raise ValueError("分类错误")
        snap = self.store.snapshot()
        notes = self.store.notes(snap)
        return [{"path": n["path"], "revision": n["revision"], **n["properties"]} for n in notes if (not category or n["properties"].get("category") == category) and query.casefold() in n["content"].casefold()]


def main():
    parser = argparse.ArgumentParser(description="Project Scout 私人 GitHub 收藏；评审与确认分离")
    parser.add_argument("--branch", help="默认仓库主分支；测试使用隔离分支")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "save", "update"):
        c = sub.add_parser(name)
        c.add_argument("file", type=Path)
        c.add_argument("--expected-revision", default="")
        if name == "review":
            c.add_argument("--action", choices=["save", "update"], default="save")
        else:
            c.add_argument("--review-digest", required=True)
            c.add_argument("--confirmation", required=True)
    s = sub.add_parser("search")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--category", default="")
    r = sub.add_parser("recover")
    r.add_argument("request_id")
    args = parser.parse_args()
    service = LibraryService(GitHubStore(branch=args.branch))
    try:
        if args.command == "search":
            result = service.search_projects(args.query, args.category)
        elif args.command == "recover":
            result = service.recover(args.request_id)
        else:
            data = json.loads(args.file.read_text(encoding="utf-8-sig"))
            if args.command == "review":
                result = service.review_project(data, action=args.action, expected_revision=args.expected_revision)
            elif args.command == "save":
                result = service.save_project(data, review_digest=args.review_digest, confirmation=args.confirmation)
            else:
                result = service.update_project(data, expected_revision=args.expected_revision, review_digest=args.review_digest, confirmation=args.confirmation)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, PermissionError, LibraryError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
