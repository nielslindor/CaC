from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from codexascode.engine import EngineError, apply, load_manifest, plan, verify


def manifest(*, content: str = "first", directories: list[str] | None = None, git: bool = False) -> dict:
    return {
        "apiVersion": "cac/v1",
        "kind": "Workspace",
        "metadata": {"name": "example"},
        "spec": {
            "git": {"enabled": git, "defaultBranch": "main"},
            "directories": directories or ["docs/changes"],
            "files": [{"path": "AGENTS.md", "content": content}],
        },
    }


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        # On macOS tempfile commonly returns /var/...; canonicalizing the test
        # root keeps the engine's deliberately strict ancestor-symlink rule.
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "workspace"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_first_apply_is_idempotent_and_git_ignores_state(self) -> None:
        first = apply(manifest(git=True), self.root)
        self.assertEqual("applied", first["state"]["status"])
        self.assertEqual("first", (self.root / "AGENTS.md").read_text())
        state_path = self.root / ".cac" / "state.json"
        original_state = state_path.read_bytes()
        original_file = (self.root / "AGENTS.md").read_bytes()

        second = apply(manifest(git=True), self.root)
        self.assertFalse(second["changed"])
        self.assertEqual("unchanged", second["state"]["status"])
        self.assertEqual(original_state, state_path.read_bytes())
        self.assertEqual(original_file, (self.root / "AGENTS.md").read_bytes())
        status = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertNotIn(".cac", status.stdout)

    def test_managed_file_updates_but_local_edit_is_refused(self) -> None:
        apply(manifest(content="first"), self.root)
        updated = apply(manifest(content="second"), self.root)
        self.assertTrue(updated["changed"])
        self.assertEqual("second", (self.root / "AGENTS.md").read_text())
        (self.root / "AGENTS.md").write_text("local")
        result = apply(manifest(content="third"), self.root)
        self.assertEqual("conflicted", result["state"]["status"])
        self.assertEqual("local", (self.root / "AGENTS.md").read_text())
        self.assertEqual("managed-file-modified", result["conflicts"][0]["reason"])

    def test_preflight_conflict_does_not_create_other_files(self) -> None:
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("unowned")
        requested = manifest()
        requested["spec"]["files"].append({"path": "new.txt", "content": "new"})
        result = apply(requested, self.root)
        self.assertTrue(result["conflicts"])
        self.assertFalse((self.root / "new.txt").exists())

    def test_plan_and_verify_detect_missing_tracked_file_without_mutation(self) -> None:
        apply(manifest(), self.root)
        (self.root / "AGENTS.md").unlink()
        requested = manifest()
        result = plan(requested, self.root)
        self.assertEqual("managed-file-missing", result["conflicts"][0]["reason"])
        verification = verify(requested, self.root)
        self.assertFalse(verification["ok"])
        self.assertIn("!missing", {item["reason"] for item in verification["drift"]})

    def test_invalid_paths_duplicates_and_poisoned_state_fail_safely(self) -> None:
        unsafe = manifest()
        unsafe["spec"]["files"][0]["path"] = "../outside"
        with self.assertRaises(EngineError):
            plan(unsafe, self.root)
        duplicate = manifest(directories=["Docs"])
        duplicate["spec"]["files"].append({"path": "docs", "content": "x"})
        with self.assertRaises(EngineError):
            plan(duplicate, self.root)
        file_parent = manifest(directories=["AGENTS.md/child"])
        with self.assertRaises(EngineError):
            plan(file_parent, self.root)
        self.root.mkdir()
        (self.root / ".cac").mkdir()
        (self.root / ".cac" / "state.json").write_text(json.dumps({"version": 1, "files": {".git/x": "0" * 64}}))
        with self.assertRaises(EngineError):
            plan(manifest(), self.root)

    def test_symlink_escape_is_rejected(self) -> None:
        self.root.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "docs").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(EngineError):
            apply(manifest(), self.root)

    def test_symlinked_state_directory_is_rejected(self) -> None:
        self.root.mkdir()
        outside = self.base / "outside-state"
        outside.mkdir()
        (self.root / ".cac").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(EngineError):
            apply(manifest(), self.root)

    def test_nonregular_state_and_lock_paths_are_rejected(self) -> None:
        self.root.mkdir()
        (self.root / ".cac").mkdir()
        (self.root / ".cac" / "state.json").mkdir()
        with self.assertRaises(EngineError):
            apply(manifest(), self.root)
        (self.root / ".cac" / "state.json").rmdir()
        (self.root / ".cac" / "apply.lock").mkdir()
        with self.assertRaises(EngineError):
            apply(manifest(), self.root)

    def test_parent_or_nested_repository_is_not_hijacked(self) -> None:
        parent = self.base / "parent"
        parent.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(parent)], check=True, capture_output=True)
        child = parent / "child"
        with self.assertRaises(EngineError):
            apply(manifest(git=True), child)

        independent = self.base / "independent"
        independent.mkdir()
        nested = independent / "nested"
        nested.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(nested)], check=True, capture_output=True)
        with self.assertRaises(EngineError):
            apply(manifest(git=True), independent)

    def test_load_manifest_rejects_unknown_schema(self) -> None:
        path = self.base / "manifest.json"
        value = manifest()
        value["unexpected"] = True
        path.write_text(json.dumps(value))
        with self.assertRaises(EngineError):
            load_manifest(path)


if __name__ == "__main__":
    unittest.main()
