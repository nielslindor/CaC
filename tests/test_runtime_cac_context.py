import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from codexascode.runtime import cac_context


class ContextIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_metadata_and_unchanged(self):
        src = {"sources": [{"url": "https://developers.openai.com/codex/", "title": "Codex"}]}
        calls = []
        def fetch(url):
            calls.append(url)
            return b"line one\nline two\nline three"
        self.assertEqual(cac_context.refresh_docs(self.state, src, fetcher=fetch, codex_version="1" )["changed"], 1)
        self.assertEqual(cac_context.refresh_docs(self.state, src, fetcher=fetch, codex_version="1" )["changed"], 0)
        self.assertEqual(cac_context.status(self.state)["docs"], 1)
        row = cac_context._db(self.state).execute("SELECT sha256,fetched_at,codex_version FROM docs").fetchone()
        self.assertEqual(row["sha256"], __import__("hashlib").sha256(b"line one\nline two\nline three").hexdigest())
        self.assertTrue(row["fetched_at"]); self.assertEqual(row["codex_version"], "1")

    def test_search_and_read_bounds(self):
        src = {"sources": [{"url": "https://help.openai.com/en/articles/1", "title": "Help"}]}
        cac_context.refresh_docs(self.state, src, fetcher=lambda _: b"needle\n" + b"x\n" * 100, codex_version="v")
        self.assertEqual(len(cac_context.search(self.state, "needle", limit=999)), 1)
        self.assertEqual(len(cac_context.read(self.state, src["sources"][0]["url"], max_lines=2, start_line=2).splitlines()), 2)
        self.assertEqual(cac_context.search(self.state, "needle")[0]["line"], 1)

    def test_denied_urls_and_paths(self):
        with self.assertRaises(ValueError): cac_context.validate_url("http://developers.openai.com/x")
        with self.assertRaises(ValueError): cac_context.validate_url("https://example.com/x")
        root = self.root / "memory"; root.mkdir(); (root / "a.txt").write_text("secret")
        with self.assertRaises(ValueError): cac_context.index_memory(self.state, root, ["../outside"], host_id="host-a")
        (root / "link.txt").symlink_to(root / "a.txt")
        with self.assertRaises(ValueError): cac_context.index_memory(self.state, root, ["link.txt"], host_id="host-a")
        (root / ".env").write_text("TOKEN=secret")
        with self.assertRaises(ValueError): cac_context.index_memory(self.state, root, [".env"], host_id="host-a")
        (root / "cache.db").write_bytes(b"db")
        with self.assertRaises(ValueError): cac_context.index_memory(self.state, root, ["cache.db"], host_id="host-a")

    def test_memory_is_host_separated_and_provenance_bound(self):
        root = self.root / "memory"; root.mkdir(); (root / "a.txt").write_text("alpha\nline2\nline3")
        cac_context.index_memory(self.state, root, ["a.txt"], host_id="host-a")
        cac_context.index_memory(self.state, root, ["a.txt"], host_id="host-b")
        self.assertEqual(cac_context.status(self.state)["memory"], 2)
        self.assertIn("alpha", cac_context.read(self.state, "a.txt", collection="memory", host_id="host-a"))
        self.assertEqual(cac_context.search(self.state, "alpha", collection="memory", host_id="host-b")[0]["host_id"], "host-b")
        row = cac_context._db(self.state).execute("SELECT scope,provenance FROM memory WHERE host_id='host-a'").fetchone()
        self.assertEqual(row["scope"], "host-local"); self.assertIn("a.txt", row["provenance"])


if __name__ == "__main__": unittest.main()
