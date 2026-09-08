import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from codexascode.runtime.cac_coordination import CoordinationStore, LeaseConflict, LeaseDenied


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.remote = root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.a = CoordinationStore(str(self.remote), root / "cache-a")
        self.b = CoordinationStore(str(self.remote), root / "cache-b")

    def tearDown(self):
        self.tmp.cleanup()

    def test_credentials_symlink_and_noop_boundaries(self):
        from codexascode.runtime.cac_coordination import CoordinationError
        with self.assertRaises(CoordinationError):
            CoordinationStore('https://user:secret@example.com/repo',Path(self.tmp.name).resolve()/'bad')
        link=Path(self.tmp.name).resolve()/'link';link.symlink_to(self.a.cache_dir,target_is_directory=True)
        with self.assertRaises(CoordinationError):
            CoordinationStore(str(self.remote),link/'nested')
        self.assertIsNone(self.a._mutate(lambda state:None))
        self.assertIsNone(self.a._head()[0])

    def claim(self, store, resource="repo/worktree"):
        return store.claim(resource, host_id="host-a", task_id="task-1", agent_id="agent-1",
                            project="project", worktree="/tmp/worktree", branch="main",
                            source_revision="abc123", duration_seconds=30)

    def test_claim_renew_release_and_token_is_not_remote(self):
        result = self.claim(self.a)
        token = result["lease_token"]
        self.assertTrue(token)
        self.assertNotIn(token, json.dumps(self.b.list_leases()))
        renewed = self.b.renew("repo/worktree", token, duration_seconds=30)
        self.assertEqual(renewed["resource"], "repo/worktree")
        self.assertTrue(self.a.release("repo/worktree", token)["released"])
        self.assertEqual(self.b.list_leases(), [])

    def test_active_claim_is_denied_and_wrong_token_cannot_release(self):
        self.claim(self.a)
        with self.assertRaises(LeaseDenied):
            self.claim(self.b)
        with self.assertRaises(LeaseDenied):
            self.b.release("repo/worktree", "wrong-token")

    def test_expiry_is_stale_and_can_be_reclaimed(self):
        old = self.a.claim("short", host_id="h", task_id="t", agent_id="a", project="p",
                           worktree="w", branch="b", source_revision="r", duration_seconds=1)
        time.sleep(1.2)
        listing = self.b.list_leases()
        self.assertEqual(listing[0]["status"], "stale")
        new = self.b.claim("short", host_id="h2", task_id="t2", agent_id="a2", project="p",
                           worktree="w", branch="b", source_revision="r", duration_seconds=30)
        with self.assertRaises(LeaseDenied):
            self.a.renew("short", old["lease_token"])
        self.assertEqual(new["lease"]["host_id"], "h2")

    def test_stale_writer_fails_force_with_lease(self):
        self.claim(self.a)
        old_sha, state = self.a._head()
        self.claim(self.b, "other")
        # Build a competing update from the stale snapshot and attempt its CAS push.
        state["receipts"] = {"h": {"revision": "r", "observed_at": "now", "status": "ok",
                                    "codex_version": "v", "effective": {}}}
        with self.assertRaises(LeaseConflict):
            self.a._push(old_sha, state)

    def test_receipts_are_bounded_and_schema_safe(self):
        self.a.put_receipt("host-a", revision="rev", observed_at=None, status="ok",
                           codex_version="1.0", effective={"installed": True})
        receipt = self.b.get_receipts(limit=1)[0]
        self.assertEqual(receipt["host_id"], "host-a")
        self.assertEqual(receipt["effective"], {"installed": True})
        with self.assertRaises(LeaseDenied):
            self.a.put_receipt("bad", revision="r", observed_at=None, status="ok",
                               codex_version="v", effective={"secret": "value"})

    def test_successive_independent_updates_preserve_commit_history(self):
        self.claim(self.a, "one")
        self.claim(self.b, "two")
        sha = subprocess.run(["git", "ls-remote", str(self.remote), "refs/heads/cac-coordination"],
                             check=True, capture_output=True, text=True).stdout.split()[0]
        count = subprocess.run(["git", "--git-dir", str(self.remote), "rev-list", "--count", sha],
                               check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(count, "2")

    def test_discovery_shares_names_and_sha256_only(self):
        digest = "a" * 64
        self.a.put_discovery("host-a", {"skill/demo": digest})
        found = self.b.list_discoveries(limit=1)[0]
        self.assertEqual(found["skills"], {"skill/demo": digest})
        with self.assertRaises(LeaseDenied):
            self.a.put_discovery("host-b", {"skill": "local path"})


if __name__ == "__main__":
    unittest.main()
