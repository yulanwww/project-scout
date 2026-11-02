"""Local SQLite repository. No network dependencies."""
import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from config import project_path

DEFAULT_DB = project_path("PROJECT_SCOUT_DB_PATH", "tools.db")
FIELDS = ("name", "description", "purpose", "usage", "website", "github", "source_url", "price", "category", "tags", "collected_date")

class DuplicateTool(ValueError):
    pass

def name_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

def url_key(value):
    if not value:
        return ""
    p = urlsplit(value)
    host = p.netloc.casefold().removeprefix("www.")
    path = p.path.rstrip("/")
    if host == "github.com":
        path = path.casefold().removesuffix(".git")
        query = ""
    else:
        query = urlencode(sorted((k,v) for k,v in parse_qsl(p.query) if not k.casefold().startswith("utm_") and k.casefold() not in ("fbclid", "gclid")))
    return urlunsplit(("https", host, path, query, ""))

def validate(data):
    if not isinstance(data, dict):
        raise ValueError("每条工具必须是 JSON 对象")
    unknown = set(data) - set(FIELDS)
    if unknown:
        raise ValueError("未知字段: " + ", ".join(sorted(unknown)))
    result = {}
    for field in FIELDS:
        value = data.get(field, "")
        if field == "tags" and isinstance(value, list):
            if not all(isinstance(t, str) for t in value):
                raise ValueError("标签列表必须全部为字符串")
            value = ", ".join(value)
        if not isinstance(value, str):
            raise ValueError(field + " 必须为字符串")
        result[field] = value.strip()
    if not result["name"]:
        raise ValueError("工具名称不能为空")
    for field in ("website", "github", "source_url"):
        if result[field]:
            p = urlsplit(result[field])
            if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
                raise ValueError(field + " 必须是完整的 HTTP/HTTPS 链接")
    result["collected_date"] = result["collected_date"] or date.today().isoformat()
    date.fromisoformat(result["collected_date"])
    return result

class ToolRepository:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        with self.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS tools (id INTEGER PRIMARY KEY, " + ", ".join(f"{f} TEXT NOT NULL" for f in FIELDS) + ", name_key TEXT NOT NULL UNIQUE, website_key TEXT NOT NULL, github_key TEXT NOT NULL)")
            for field in ("website_key", "github_key"):
                conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{field} ON tools({field}) WHERE {field} != ''")
            conn.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _save(self, conn, data, tool_id=None):
        d = validate(data)
        keys = {"name_key": name_key(d["name"]), "website_key": url_key(d["website"]), "github_key": url_key(d["github"])}
        if tool_id is not None and not conn.execute("SELECT id FROM tools WHERE id=?", (tool_id,)).fetchone():
            raise ValueError("工具不存在")
        try:
            values = {**d, **keys}
            if tool_id is None:
                fields = list(values)
                cursor = conn.execute("INSERT INTO tools (" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")", tuple(values.values()))
                return cursor.lastrowid
            conn.execute("UPDATE tools SET " + ",".join(f"{f}=?" for f in values) + " WHERE id=?", (*values.values(), tool_id))
            return tool_id
        except sqlite3.IntegrityError as exc:
            raise DuplicateTool("名称、官网或 GitHub 地址与已有工具重复") from exc

    def add(self, data):
        with self.connection() as conn:
            return self._save(conn, data)

    def update(self, tool_id, data):
        """Patch supplied fields while preserving all remaining fields."""
        with self.connection() as conn:
            old = conn.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
            if old is None:
                raise ValueError("工具不存在")
            if not isinstance(data, dict) or set(data) - set(FIELDS):
                raise ValueError("更新字段无效")
            return self._save(conn, {**{f: old[f] for f in FIELDS}, **data}, tool_id)

    def get(self, tool_id):
        with self.connection() as conn:
            row = conn.execute("SELECT id," + ",".join(FIELDS) + " FROM tools WHERE id=?", (tool_id,)).fetchone()
            return dict(row) if row else None

    def search(self, query="", category=""):
        # Python casefold supports non-ASCII searches consistently with SQLite.
        with self.connection() as conn:
            rows = conn.execute("SELECT id," + ",".join(FIELDS) + " FROM tools ORDER BY collected_date DESC,id DESC").fetchall()
        q = query.strip().casefold()
        return [dict(r) for r in rows if (not category or r["category"] == category) and (not q or any(q in r[f].casefold() for f in FIELDS))]

    def delete(self, tool_id):
        with self.connection() as conn:
            return conn.execute("DELETE FROM tools WHERE id=?", (tool_id,)).rowcount > 0

    def import_json(self, content):
        payload = json.loads(content)
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise ValueError("JSON 顶层必须是工具对象或对象数组")
        # Validate the entire batch before writing; malformed batches change nothing.
        items = [validate(item) for item in payload]
        added, duplicates = 0, 0
        with self.connection() as conn:
            for item in items:
                try:
                    self._save(conn, item)
                    added += 1
                except DuplicateTool:
                    duplicates += 1
        return {"added": added, "duplicates": duplicates}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="本地 AI 工具收藏库")
    parser.add_argument("--import-json", type=Path)
    args = parser.parse_args()
    repo = ToolRepository()
    if args.import_json:
        print(repo.import_json(args.import_json.read_text(encoding="utf-8-sig")))
    else:
        print(f"数据库已就绪: {repo.path}")
