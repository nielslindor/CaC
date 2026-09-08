#!/usr/bin/env python3
"""Bounded, provenance-aware index for official Codex docs and local memory.

The module deliberately has no implicit discovery.  Callers provide a source
configuration and, separately, an explicit list of memory files.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.request import HTTPRedirectHandler, build_opener

MAX_DOCUMENT_BYTES = 2_000_000
MAX_MEMORY_BYTES = 1_000_000
MAX_RESULTS = 20
MAX_SNIPPET = 240
MAX_READ_CHARS = 20_000
DEFAULT_TIMEOUT = 10
OFFICIAL_HOSTS = frozenset({"help.openai.com", "openai.com", "platform.openai.com", "developers.openai.com", "learn.chatgpt.com"})


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _state(state_dir: os.PathLike[str] | str) -> Path:
    p = Path(state_dir).expanduser()
    if p.exists() and not p.is_dir():
        raise ValueError("state directory is not a directory")
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(p, 0o700)
    return p


def _db(state_dir: os.PathLike[str] | str) -> sqlite3.Connection:
    path = _state(state_dir) / "context.sqlite3"
    if path.is_symlink():
        raise ValueError("state database symlink is not allowed")
    c = sqlite3.connect(path)
    try: os.chmod(path, 0o600)
    except OSError: pass
    c.row_factory = sqlite3.Row
    c.executescript("""
      CREATE TABLE IF NOT EXISTS docs (url TEXT PRIMARY KEY, title TEXT NOT NULL,
        body TEXT NOT NULL, sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL,
        codex_version TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS memory (path TEXT NOT NULL, host_id TEXT NOT NULL,
        scope TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL,
        indexed_at TEXT NOT NULL, provenance TEXT NOT NULL, PRIMARY KEY(path, host_id))
    """)
    return c


def validate_url(url: str) -> str:
    """Accept only HTTPS URLs on the explicit OpenAI official host allowlist."""
    try:
        u = urlparse(url)
    except Exception as e:
        raise ValueError("invalid documentation URL") from e
    host = (u.hostname or "").lower().rstrip(".")
    if u.scheme != "https" or not host or host not in OFFICIAL_HOSTS or u.username or u.password or u.port:
        raise ValueError("documentation URL is not an allowed official HTTPS URL")
    if u.fragment:
        raise ValueError("documentation URL must not contain a fragment")
    return url


class _OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str, timeout: int = DEFAULT_TIMEOUT, max_bytes: int = MAX_DOCUMENT_BYTES) -> bytes:
    req = Request(validate_url(url), headers={"User-Agent": "cac-context/1"})
    with build_opener(_OfficialRedirects()).open(req, timeout=timeout) as response:  # no credentials/cookies
        validate_url(response.geturl())
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("documentation response exceeds size limit")
    return data


def load_sources(source_config: os.PathLike[str] | str | Mapping) -> list[dict]:
    """Load explicit source objects from JSON path or mapping."""
    obj = json.loads(Path(source_config).read_text(encoding="utf-8")) if isinstance(source_config, (str, os.PathLike)) else source_config
    values = obj.get("sources") if isinstance(obj, Mapping) else obj
    if not isinstance(values, list) or not values:
        raise ValueError("source config must contain a non-empty sources list")
    out = []
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("url"), str):
            raise ValueError("each source must contain a URL")
        url = validate_url(item["url"])
        out.append({"url": url, "title": str(item.get("title") or url)[:200]})
    return out


def refresh_docs(state_dir, sources, *, fetcher: Callable[[str], bytes] | None = None, codex_version: str = "unknown") -> dict:
    """Fetch explicit official sources and atomically update changed rows."""
    source_list = load_sources(sources)
    fetch = fetcher or _fetch
    c = _db(state_dir)
    changed = 0
    try:
        c.execute("BEGIN")
        for source in source_list:
            raw = fetch(source["url"])
            if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_DOCUMENT_BYTES:
                raise ValueError("documentation source returned invalid or oversized data")
            body = raw.decode("utf-8", errors="replace")
            digest = hashlib.sha256(raw).hexdigest()
            old = c.execute("SELECT sha256 FROM docs WHERE url=?", (source["url"],)).fetchone()
            if old and old["sha256"] == digest and c.execute("SELECT codex_version FROM docs WHERE url=?", (source["url"],)).fetchone()[0] == str(codex_version):
                c.execute("UPDATE docs SET fetched_at=? WHERE url=?", (_now(), source["url"]))
                continue
            c.execute("INSERT INTO docs VALUES(?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,body=excluded.body,sha256=excluded.sha256,fetched_at=excluded.fetched_at,codex_version=excluded.codex_version", (source["url"], source["title"], body, digest, _now(), str(codex_version)))
            changed += 1
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {"sources": len(source_list), "changed": changed, "unchanged": len(source_list) - changed}


def _safe_memory_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid memory path")
    if Path(value).name.lower() in {".env", ".env.local", "credentials", "auth.json"} or Path(value).suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("memory file type is not allowed")
    if Path(value).suffix.lower() not in {".md", ".markdown", ".txt", ".text"}:
        raise ValueError("memory files must be markdown or text")
    if root.is_symlink() or any(part.is_symlink() for part in root.parents if part.exists()):
        raise ValueError("memory root has a symlink ancestor")
    root = root.resolve()
    candidate = root / value
    # Inspect the lexical path before resolving: resolving first would hide an
    # otherwise disallowed symlink that points to another file inside root.
    if any(part.is_symlink() for part in [candidate, *candidate.parents] if part.exists()):
        raise ValueError("memory symlinks are not allowed")
    p = candidate.resolve(strict=False)
    if p != root and root not in p.parents:
        raise ValueError("memory path is outside memory root")
    return p


def index_memory(state_dir, memory_root, files: Iterable[str], *, host_id: str) -> dict:
    """Index only explicitly named regular files under memory_root."""
    if not isinstance(host_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", host_id):
        raise ValueError("invalid host id")
    names = list(files)
    root = Path(memory_root).expanduser()
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValueError("memory root must be an existing directory")
    c = _db(state_dir); changed = 0
    try:
        c.execute("BEGIN")
        for name in names:
            p = _safe_memory_path(root, name)
            if not p.is_file(): raise ValueError("memory path is not a regular file")
            raw = p.read_bytes()
            if len(raw) > MAX_MEMORY_BYTES: raise ValueError("memory file exceeds size limit")
            digest = hashlib.sha256(raw).hexdigest(); key = str(p.relative_to(root))
            old = c.execute("SELECT sha256,host_id FROM memory WHERE path=? AND host_id=?", (key, host_id)).fetchone()
            if old and old["sha256"] == digest and old["host_id"] == host_id: continue
            provenance = json.dumps({"root": str(root), "path": key}, sort_keys=True)
            c.execute("INSERT INTO memory VALUES(?,?,?,?,?,?,?) ON CONFLICT(path,host_id) DO UPDATE SET scope=excluded.scope,body=excluded.body,sha256=excluded.sha256,indexed_at=excluded.indexed_at,provenance=excluded.provenance", (key, host_id, "host-local", raw.decode("utf-8", errors="replace"), digest, _now(), provenance)); changed += 1
        c.commit()
    except Exception: c.rollback(); raise
    finally: c.close()
    return {"files": len(names), "changed": changed}


def search(state_dir, query: str, *, collection: str = "docs", host_id: str | None = None, limit: int = 10) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 200: raise ValueError("invalid search query")
    limit = max(1, min(int(limit), MAX_RESULTS)); c = _db(state_dir)
    try:
        table = "docs" if collection == "docs" else "memory" if collection == "memory" else None
        if not table: raise ValueError("collection must be docs or memory")
        if table == "memory" and not host_id: raise ValueError("host_id is required for memory search")
        args = ["%" + query.strip() + "%"]; where = "(title LIKE ? OR body LIKE ?)" if table == "docs" else "body LIKE ?"
        if table == "docs": args = [args[0], args[0]]
        if table == "memory" and host_id is not None: where += " AND host_id=?"; args.append(host_id)
        order = "fetched_at" if table == "docs" else "indexed_at"
        rows = c.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY {order} DESC LIMIT ?", (*args, limit)).fetchall()
        result = []
        needle = query.strip().lower()
        for r in rows:
            body = r["body"]; pos = body.lower().find(needle); start = max(0, pos - MAX_SNIPPET // 2) if pos >= 0 else 0
            result.append({"id": r["url"] if table == "docs" else r["path"], "title": r["title"] if table == "docs" else r["path"], "snippet": re.sub(r"\s+", " ", body[start:start + MAX_SNIPPET]), "line": body[:pos].count("\n") + 1 if pos >= 0 else 1, "host_id": r["host_id"] if table == "memory" else None})
        return result
    finally: c.close()


def read(state_dir, item: str, *, collection: str = "docs", host_id: str | None = None, max_lines: int = 40, start_line: int = 1) -> str:
    max_lines = max(1, min(int(max_lines), 200)); c = _db(state_dir)
    start_line = max(1, int(start_line))
    try:
        if collection == "docs": row = c.execute("SELECT body FROM docs WHERE url=?", (validate_url(item),)).fetchone()
        elif collection == "memory":
            if not host_id: raise ValueError("host_id is required for memory read")
            row = c.execute("SELECT body FROM memory WHERE path=? AND host_id=?", (item, host_id)).fetchone()
        else: raise ValueError("collection must be docs or memory")
        if not row: raise KeyError("indexed item not found")
        return "\n".join(row["body"].splitlines()[start_line - 1:start_line - 1 + max_lines])[:MAX_READ_CHARS]
    finally: c.close()


def status(state_dir) -> dict:
    c = _db(state_dir)
    try:
        return {"docs": c.execute("SELECT count(*) FROM docs").fetchone()[0], "memory": c.execute("SELECT count(*) FROM memory").fetchone()[0], "doc_versions": [dict(r) for r in c.execute("SELECT url,sha256,fetched_at,codex_version FROM docs ORDER BY url LIMIT ?", (MAX_RESULTS,)).fetchall()]}
    finally: c.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--state-dir", required=True)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("refresh"); r.add_argument("--sources", required=True); r.add_argument("--codex-version", default="unknown")
    m = sub.add_parser("memory"); m.add_argument("--root", required=True); m.add_argument("--host-id", required=True); m.add_argument("files", nargs="+")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--collection", default="docs"); s.add_argument("--host-id"); s.add_argument("--limit", type=int, default=10)
    q = sub.add_parser("read"); q.add_argument("item"); q.add_argument("--collection", default="docs"); q.add_argument("--host-id"); q.add_argument("--max-lines", type=int, default=40); q.add_argument("--start-line", type=int, default=1)
    sub.add_parser("status"); a = ap.parse_args(argv)
    if a.command == "refresh": out = refresh_docs(a.state_dir, a.sources, codex_version=a.codex_version)
    elif a.command == "memory": out = index_memory(a.state_dir, a.root, a.files, host_id=a.host_id)
    elif a.command == "search": out = search(a.state_dir, a.query, collection=a.collection, host_id=a.host_id, limit=a.limit)
    elif a.command == "read": out = read(a.state_dir, a.item, collection=a.collection, host_id=a.host_id, max_lines=a.max_lines, start_line=a.start_line)
    else: out = status(a.state_dir)
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, UnicodeError) as exc:
        # Keep operational errors bounded and avoid echoing source data or
        # potentially sensitive paths/URLs.
        print(f"cac_context: {type(exc).__name__}", file=sys.stderr)
        sys.exit(2)
