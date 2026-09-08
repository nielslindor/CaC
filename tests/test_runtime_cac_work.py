import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from codexascode.runtime.cac_work import run_work
from codexascode.runtime.cac_coordination import CoordinationStore


class WorkRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.remote = self.root / "coord.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.project = self.root / "project"; self.project.mkdir()
        subprocess.run(["git", "init", str(self.project)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "t@e"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "T"], check=True)
        (self.project / "file.txt").write_text("seed\n")
        subprocess.run(["git", "-C", str(self.project), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-m", "seed"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.project), "remote", "add", "origin", str(self.remote)], check=True)
        self.state = self.root / "state"; (self.state / "work").mkdir(parents=True)
        (self.state / "enrollment.json").write_text(json.dumps({"host_id":"host-a", "remote":str(self.remote)}))

    def tearDown(self): self.tmp.cleanup()

    def test_success_releases_lease_and_writes_safe_record(self):
        result = run_work(self.state, self.project, "scope", "task-ok", "agent", ["python3", "-c", "print('ok')"])
        self.assertEqual(result["status"], "completed")
        record = json.loads((self.state / "work/task-ok.json").read_text())
        self.assertNotIn("lease_token", record)
        self.assertEqual(CoordinationStore(str(self.remote), self.state / "coordination").list_leases(), [])
        self.assertTrue((self.state / "worktrees/task-ok").exists())

    def test_failed_command_keeps_worktree_and_replaces_running_record(self):
        result = run_work(self.state, self.project, "scope", "task-fail", "agent", ["python3", "-c", "raise SystemExit(7)"])
        self.assertEqual(result["status"], "failed")
        record = json.loads((self.state / "work/task-fail.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("lease_token", record)
        self.assertTrue((self.state / "worktrees/task-fail").exists())
        self.assertEqual(CoordinationStore(str(self.remote), self.state / "coordination").list_leases(), [])


if __name__ == "__main__": unittest.main()
