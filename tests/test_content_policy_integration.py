import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from codexascode.bootstrap import init
from codexascode.gauntlet import run_gauntlet


class ContentPolicyIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_special_files_are_not_read_as_documents_or_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            os.mkfifo(root / "cac-policy.json")
            self.assertIn("policy", {x["rule"] for x in run_gauntlet(root, profile="workspace")["failures"]})
            (root / "cac-policy.json").unlink()
            os.mkfifo(root / "document")
            self.assertIn("nonregular-file", {x["rule"] for x in run_gauntlet(root, profile="workspace")["failures"]})

    def test_generated_workspace_accepts_personal_content_and_can_check_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "workspace"
            init(root, "example")
            self.assertEqual(json.loads((root / "cac-policy.json").read_text())["profile"], "workspace")
            personal = root / "private" / "settings.json"
            personal.parent.mkdir()
            personal.write_text(json.dumps({"home": "/" + "Users" + "/example", "host": "192." + "168.20.5"}))
            (root / "document.pdf").write_bytes(b"%PDF-1.7\n" + bytes([0, 255]))
            result = run_gauntlet(root)
            self.assertEqual(result["status"], "pass", result)
            ignored = subprocess.run(["git", "check-ignore", "private/settings.json"], cwd=root, capture_output=True)
            self.assertEqual(ignored.returncode, 1)
            publication = run_gauntlet(root, profile="public")
            self.assertEqual(publication["status"], "fail")
            self.assertTrue({"home-absolute", "private-ip"}.issubset({x["rule"] for x in publication["failures"]}))
            personal.write_text(json.dumps({"token": "gh" + "p_" + "A" * 30}))
            result = run_gauntlet(root)
            self.assertEqual(result["status"], "fail")
            self.assertIn("token", {x["rule"] for x in result["failures"]})
            self.assertNotIn("A" * 30, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
