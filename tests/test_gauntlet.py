import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codexascode.gauntlet import run_gauntlet
from codexascode.lifecycle import create_change, source_digest


class GauntletTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_clean_scaffold_private_ip_and_nul_binary(self):
        (self.root / "config.json").write_text('{"name":"demo"}\n')
        (self.root / "partial.txt").write_text("10.2.3\n")
        self.assertEqual(run_gauntlet(self.root)["status"], "pass")
        (self.root / "full.txt").write_text("10." + "2.3.4\n")
        failed = run_gauntlet(self.root)
        self.assertIn("private-ip", {item["rule"] for item in failed["failures"]})
        (self.root / "full.txt").unlink()
        (self.root / "nul.txt").write_bytes(b"valid utf8\x00but binary")
        failed = run_gauntlet(self.root)
        self.assertIn("unexpected-binary", {item["rule"] for item in failed["failures"]})

    def test_profiles_persisted_override_and_credentials(self):
        (self.root / "local.txt").write_text("/" + "Users" + "/example/private " + "10." + "2.3.4\n")
        self.assertEqual(run_gauntlet(self.root)["profile"], "public")
        self.assertEqual(run_gauntlet(self.root)["status"], "fail")
        (self.root / "cac-policy.json").write_text(json.dumps({"schema_version": 1, "profile": "workspace"}))
        workspace = run_gauntlet(self.root)
        self.assertEqual(workspace["profile"], "workspace")
        self.assertEqual(workspace["status"], "pass")
        (self.root / "token.txt").write_text("ghp_" + "x" * 24)
        self.assertIn("token", {item["rule"] for item in run_gauntlet(self.root)["failures"]})
        self.assertEqual(run_gauntlet(self.root, profile="public")["profile"], "public")

    def test_invalid_policy_fails_closed_even_with_override(self):
        invalid_values = (
            '{"schema_version": 2, "profile": "workspace"}',
            '{"schema_version": 1, "profile": "workspace", "extra": true}',
            '{"schema_version": true, "profile": "workspace"}',
            '{"schema_version": 1, "profile": []}',
        )
        for value in invalid_values:
            (self.root / "cac-policy.json").write_text(value)
            result = run_gauntlet(self.root, profile="public")
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["failures"], [{"rule": "policy", "path": "cac-policy.json"}])
            self.assertIsNone(result["profile"])

        policy = self.root / "cac-policy.json"
        policy.unlink()
        policy.mkdir()
        result = run_gauntlet(self.root, profile="public")
        self.assertEqual(result["failures"], [{"rule": "policy", "path": "cac-policy.json"}])
        policy.rmdir()
        target = self.root / "policy-target.json"
        target.write_text('{"schema_version": 1, "profile": "public"}')
        policy.symlink_to(target)
        result = run_gauntlet(self.root, profile="workspace")
        self.assertEqual(result["failures"], [{"rule": "policy", "path": "cac-policy.json"}])

    def test_workspace_binary_and_absolute_markdown_link_are_not_scanned(self):
        (self.root / "cac-policy.json").write_text('{"schema_version": 1, "profile": "workspace"}')
        (self.root / "document.bin").write_bytes(b"binary\x00secret")
        (self.root / "readme.md").write_text("[outside](" + "/" + "Users" + "/example/private/file.txt)\n")
        result = run_gauntlet(self.root)
        self.assertEqual(result["status"], "pass")
        checks = {(item["rule"], item["path"], item["status"]) for item in result["checks"]}
        self.assertIn(("binary-content", "document.bin", "not-scanned"), checks)
        self.assertIn(("markdown-link", "readme.md", "not-checked"), checks)

    def test_workspace_binary_structured_files_still_fail_parse(self):
        (self.root / "cac-policy.json").write_text('{"schema_version": 1, "profile": "workspace"}')
        (self.root / "broken.json").write_bytes(b'{"broken":\x00')
        reviewer = self.root / ".codex/agents/reviewer.toml"
        reviewer.parent.mkdir(parents=True)
        reviewer.write_bytes(b'name = "reviewer"\x00')
        result = run_gauntlet(self.root)
        self.assertEqual(result["status"], "fail")
        parse_paths = {item["path"] for item in result["failures"] if item["rule"] == "parse"}
        self.assertIn("broken.json", parse_paths)
        self.assertIn(".codex/agents/reviewer.toml", parse_paths)

    def test_symlink_root_docs_and_ignored_egg_info(self):
        outside = self.root / ".venv" / "outside"
        outside.mkdir(parents=True)
        (outside / "secret.txt").write_text("sk-" + "x" * 24)
        link_root = self.root / "linked-root"
        link_root.symlink_to(outside, target_is_directory=True)
        self.assertEqual(run_gauntlet(link_root)["failures"][0]["rule"], "root")
        link_root.unlink()
        nested_target = self.root / "nested-target" / "workspace"
        nested_target.mkdir(parents=True)
        nested_link = self.root / "nested-link"
        nested_link.symlink_to(nested_target.parent, target_is_directory=True)
        self.assertEqual(run_gauntlet(nested_link / "workspace")["failures"][0]["rule"], "root")
        nested_link.unlink()

        docs = self.root / "docs"
        docs_target = self.root / "docs-target"
        docs_target.mkdir()
        docs.symlink_to(docs_target, target_is_directory=True)
        result = run_gauntlet(self.root)
        self.assertIn("symlink", {item["rule"] for item in result["failures"]})
        self.assertNotIn("token", {item["rule"] for item in result["failures"]})
        docs.unlink()
        egg = self.root / "pkg.egg-info"
        egg.mkdir()
        (egg / "bad.json").write_text("{")
        self.assertEqual(run_gauntlet(self.root)["status"], "pass")

    def test_agent_schema_applies_to_template_paths(self):
        agent = self.root / "src/template/.codex/agents/reviewer.toml"
        agent.parent.mkdir(parents=True)
        agent.write_text('name = "reviewer"\ndescription = "reviews"\ndeveloper_instructions = "read only"\nsandbox_mode = "read-only"\n')
        self.assertEqual(run_gauntlet(self.root)["status"], "pass")
        agent.write_text('name = "reviewer"\ndescription = "reviews"\nunknown = "no"\n')
        result = run_gauntlet(self.root)
        self.assertIn("agent-config", {item["rule"] for item in result["failures"]})

    def test_historical_lifecycle_digest_does_not_compare_current_tree(self):
        self.assertEqual(create_change(self.root, "Demo", "demo"), 0)
        record = self.root / "docs/changes/demo"
        for name in ("intent.md", "spec.md", "plan.md", "verification.md", "release.md"):
            (record / name).write_text("Completed evidence text.\n")
        data = json.loads((record / "change.json").read_text())
        data["stage"] = "verified"
        data["evidence"].update({
            "acceptance_criteria": ["criterion"],
            "verification": ["test passed"],
            "independent_review": ["reviewed"],
            "source_tree_digest": "0" * 64,
        })
        (record / "change.json").write_text(json.dumps(data))
        (self.root / "new-source.txt").write_text("a later change\n")
        result = run_gauntlet(self.root)
        self.assertEqual(result["status"], "pass")
        self.assertEqual("pass", next(item["status"] for item in result["checks"] if item["rule"] == "lifecycle"))

    def test_tests_flag_propagates_failure_and_timeout(self):
        (self.root / "tests").mkdir()
        with patch("codexascode.gauntlet.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            result = run_gauntlet(self.root, run_tests=True)
        self.assertIn("tests", {item["rule"] for item in result["failures"]})
        with patch("codexascode.gauntlet.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 120)):
            result = run_gauntlet(self.root, run_tests=True)
        self.assertIn("tests-timeout", {item["rule"] for item in result["failures"]})

    def test_bad_json_and_markdown_symlink_link_fail_without_traversal(self):
        (self.root / "bad.json").write_text("{")
        outside = self.root / "outside.md"
        outside.write_text("outside")
        target = self.root / "target.md"
        target.symlink_to(outside)
        (self.root / "readme.md").write_text("[bad](target.md)\n")
        result = run_gauntlet(self.root)
        rules = {item["rule"] for item in result["failures"]}
        self.assertIn("parse", rules)
        self.assertIn("markdown-link", rules)
        self.assertIn("symlink", rules)

    def test_file_read_error_is_structured_failure(self):
        (self.root / "unreadable.txt").write_text("ordinary text")
        with patch("codexascode.gauntlet.source_digest", return_value="0" * 64), patch.object(Path, "read_bytes", side_effect=PermissionError("denied")):
            result = run_gauntlet(self.root)
        self.assertIn("io", {item["rule"] for item in result["failures"]})


if __name__ == "__main__":
    unittest.main()
