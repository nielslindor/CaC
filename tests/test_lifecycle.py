import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from codexascode.lifecycle import check_change, create_change, source_digest, validate_change


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def _complete(self, stage="released"):
        self.assertEqual(create_change(self.root, "Demo", "demo"), 0)
        record = self.root / "docs" / "changes" / "demo"
        for name, text in {
            "intent.md": "Observed problem and desired outcome.\n",
            "spec.md": "Acceptance criterion: command returns zero.\n",
            "plan.md": "Implement the smallest repair and run the test.\n",
            "verification.md": "Observed focused test pass.\n",
            "release.md": "Published release reference and rollback route.\n",
        }.items():
            (record / name).write_text(text, encoding="utf-8")
        data = json.loads((record / "change.json").read_text())
        data["stage"] = stage
        data["evidence"].update({
            "acceptance_criteria": ["command returns zero"],
            "verification": [{"command": "python -m unittest", "result": "pass"}],
            "independent_review": ["reviewer found no release blocker"],
            "release_reference": "v0.1.0",
            "rollback_operations": ["restore the prior tagged release"],
            "unresolved_blocking_findings": [],
            "source_tree_digest": source_digest(self.root),
        })
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        return record

    def test_new_is_draft_and_repeat_does_not_clobber(self):
        self.assertEqual(create_change(self.root, "Demo change", "demo"), 0)
        intent = self.root / "docs/changes/demo/intent.md"
        intent.write_text("my authored intent\n", encoding="utf-8")
        self.assertEqual(create_change(self.root, "Demo change", "demo"), 0)
        self.assertEqual(intent.read_text(encoding="utf-8"), "my authored intent\n")
        self.assertTrue(validate_change(self.root, "demo", "draft")[0])
        self.assertFalse(validate_change(self.root, "demo", "planned")[0])

    def test_complete_record_passes_verified_and_released(self):
        self._complete()
        self.assertTrue(validate_change(self.root, "demo", "verified")[0])
        self.assertTrue(validate_change(self.root, "demo", "released")[0])

    def test_pending_and_blocker_fail_required_gates(self):
        record = self._complete("verified")
        data = json.loads((record / "change.json").read_text())
        data["evidence"]["verification"] = []
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(validate_change(self.root, "demo", "verified")[0])
        data["evidence"]["verification"] = ["focused test passed"]
        data["evidence"]["unresolved_blocking_findings"] = ["known safety blocker"]
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(validate_change(self.root, "demo", "verified")[0])

    def test_draft_schema_is_strict_without_completion_requirements(self):
        self.assertEqual(create_change(self.root, "Demo", "demo"), 0)
        record = self.root / "docs/changes/demo"
        data = json.loads((record / "change.json").read_text())
        del data["evidence"]["unresolved_blocking_findings"]
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(validate_change(self.root, "demo", "draft")[0])
        data["evidence"]["unresolved_blocking_findings"] = []
        data["evidence"]["acceptance_criteria"] = [{"command": "TODO"}]
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(validate_change(self.root, "demo", "draft")[0])

    def test_invalid_stage_types_and_unsafe_paths_do_not_raise(self):
        self.assertEqual(create_change(self.root, "x", "../escape"), 2)
        self.assertEqual(validate_change(self.root, "missing", ["verified"])[0], False)
        self.assertEqual(create_change(self.root, "Demo", "demo"), 0)
        record = self.root / "docs/changes/demo"
        data = json.loads((record / "change.json").read_text())
        data["stage"] = ["draft"]
        (record / "change.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(validate_change(self.root, "demo", "draft")[0])

    def test_digest_prunes_generated_trees_and_is_clone_stable(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("print('ok')\n")
        baseline = source_digest(self.root)
        for directory, filename in [
            (".git", "config"), (".venv", "huge"), ("build", "artifact"),
            ("dist", "wheel"), ("pkg.egg-info", "PKG-INFO"), ("docs/changes/x", "change.json"),
        ]:
            path = self.root / directory
            path.mkdir(parents=True, exist_ok=True)
            (path / filename).write_text("local and generated\n")
        (self.root / ".DS_Store").write_text("local")
        self.assertEqual(baseline, source_digest(self.root))

    def test_check_always_reports_safe_digest_and_handles_unsafe_root(self):
        self.assertEqual(create_change(self.root, "Demo", "demo"), 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(check_change(self.root, "demo", "planned"), 1)
        self.assertRegex(json.loads(output.getvalue())["source_tree_digest"], r"^[0-9a-f]{64}$")
        target = self.root / "target"
        target.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(target, target_is_directory=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(check_change(linked, "demo", "planned"), 1)
        self.assertIsNone(json.loads(output.getvalue())["source_tree_digest"])


if __name__ == "__main__":
    unittest.main()
