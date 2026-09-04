import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codexascode.bootstrap import init
from codexascode.cli import main
from codexascode import engine, github


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "project"

    def tearDown(self):
        self.temp.cleanup()

    def test_bootstrap_repeat_preserves_authored_seeds_and_all_managed_bytes(self):
        init(self.root, "example")
        before = (self.root / ".cac/state.json").stat().st_mtime_ns
        (self.root / "WORKBOARD.md").write_text("An actual user outcome.\n")
        self.assertFalse(init(self.root, "example")["changed"])
        self.assertEqual(before, (self.root / ".cac/state.json").stat().st_mtime_ns)
        self.assertEqual("An actual user outcome.\n", (self.root / "WORKBOARD.md").read_text())
        self.assertTrue((self.root / ".codex/agents/reviewer.toml").is_file())

    def test_bootstrap_resumes_interrupted_apply_and_missing_seeds(self):
        with patch("codexascode.bootstrap.apply", side_effect=OSError("simulated disk interruption")):
            with self.assertRaises(OSError):
                init(self.root, "example")
        self.assertTrue((self.root / "cac.json").is_file())
        init(self.root, "example")
        self.assertTrue((self.root / "WORKBOARD.md").is_file())
        self.assertTrue((self.root / "infra/README.md").is_file())

    def test_bootstrap_preflights_seed_conflict_without_manifest(self):
        self.root.mkdir()
        (self.root / "WORKBOARD.md").write_text("Existing project state")
        with self.assertRaises(engine.EngineError):
            init(self.root, "example")
        self.assertFalse((self.root / "cac.json").exists())

    def test_parent_repo_refused_before_manifest_is_written(self):
        subprocess.run(["git", "init", "-b", "main", str(self.base)], capture_output=True, check=True)
        with self.assertRaises(engine.EngineError):
            init(self.root, "example")
        self.assertFalse((self.root / "cac.json").exists())

    def test_fresh_clone_verifies_without_local_ownership_cache(self):
        init(self.root, "example")
        shutil.rmtree(self.root / ".cac")
        manifest = engine.load_manifest(self.root / "cac.json")
        result = engine.verify(manifest, self.root)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ownership_state_present"])

    def test_verify_checks_git_and_directories_and_allows_feature_branch(self):
        init(self.root, "example")
        manifest = engine.load_manifest(self.root / "cac.json")
        subprocess.run(["git", "-C", str(self.root), "checkout", "-b", "feature/example"], capture_output=True, check=True)
        self.assertFalse(engine.plan(manifest, self.root)["conflicts"])
        (self.root / "areas").rmdir()
        self.assertFalse(engine.verify(manifest, self.root)["ok"])
        (self.root / "areas").mkdir()
        shutil.rmtree(self.root / ".git")
        self.assertFalse(engine.verify(manifest, self.root)["ok"])

    def test_git_info_symlink_is_refused_before_managed_changes(self):
        init(self.root, "example")
        manifest = engine.load_manifest(self.root / "cac.json")
        manifest["spec"]["files"].append({"path": "new-file", "content": "hello"})
        outside = self.base / "outside"
        outside.mkdir()
        shutil.rmtree(self.root / ".git/info")
        (self.root / ".git/info").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(engine.EngineError):
            engine.apply(manifest, self.root)
        self.assertFalse((self.root / "new-file").exists())
        self.assertFalse((outside / "exclude").exists())

    def test_desired_state_can_adopt_exact_intentional_local_edit(self):
        init(self.root, "example")
        manifest = engine.load_manifest(self.root / "cac.json")
        entry = next(x for x in manifest["spec"]["files"] if x["path"] == "AGENTS.md")
        entry["content"] += "\nAn intentional new rule.\n"
        (self.root / "AGENTS.md").write_text(entry["content"])
        self.assertFalse(engine.apply(manifest, self.root)["conflicts"])
        self.assertFalse(engine.plan(manifest, self.root)["changed"])

    def test_protected_noncanonical_paths_and_bad_types_fail_cleanly(self):
        init(self.root, "example")
        original = engine.load_manifest(self.root / "cac.json")
        for path in (".", "./file", "a//b", "a/../b", "C:/file"):
            manifest = json.loads(json.dumps(original))
            manifest["spec"]["files"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(engine.EngineError):
                engine.plan(manifest, self.root)
        original["spec"]["github"] = {"repository": "example/demo", "visibility": []}
        with self.assertRaises(engine.EngineError):
            engine.plan(original, self.root)

    def test_apply_conflict_does_not_touch_github(self):
        init(self.root, "example")
        path = self.root / "cac.json"
        manifest = json.loads(path.read_text())
        manifest["spec"]["github"] = {"repository": "example/demo", "visibility": "private"}
        path.write_text(json.dumps(manifest))
        (self.root / "AGENTS.md").write_text("Local content")
        with patch.object(github, "inspect", return_value={"action": "noop"}), patch.object(github, "apply") as writer, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["apply", "--root", str(self.root)]), 1)
            writer.assert_not_called()

    def test_remote_creation_is_reported_as_a_change(self):
        init(self.root, "example")
        path = self.root / "cac.json"
        manifest = json.loads(path.read_text())
        manifest["spec"]["github"] = {"repository": "example/demo", "visibility": "private"}
        path.write_text(json.dumps(manifest))
        output = io.StringIO()
        with patch.object(github, "inspect", return_value={"action": "create"}), patch.object(github, "apply", return_value={"created": True}), contextlib.redirect_stdout(output):
            self.assertEqual(main(["apply", "--allow-remote", "--root", str(self.root)]), 0)
        self.assertTrue(json.loads(output.getvalue())["changed"])


class GitHubTests(unittest.TestCase):
    config = {"repository": "example/demo", "visibility": "private"}

    def test_wrong_visibility_and_sparse_response_fail_controlled(self):
        for response in ({"full_name": "example/demo", "private": False, "html_url": "https://github.com/example/demo"}, {"full_name": "example/demo", "private": True}, []):
            with patch.object(github.shutil, "which", return_value="gh"), patch.object(github, "_run", return_value=json.dumps(response)), self.assertRaises(github.GitHubError):
                github.inspect(self.config)

    def test_symlinked_git_is_refused_without_running_git(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td).resolve()
            root = base / "root"
            root.mkdir()
            (root / ".git").symlink_to(base / "elsewhere")
            with patch.object(github, "_run") as runner, self.assertRaises(github.GitHubError):
                github.check_origin(self.config, root)
            runner.assert_not_called()

    def test_wrong_origin_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".git").mkdir()
            with patch.object(github, "_run", side_effect=["origin\n", "https://github.com/example/other.git"]), self.assertRaises(github.GitHubError):
                github.check_origin(self.config, root)

    def test_remote_create_requires_explicit_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".git").mkdir()
            with patch.object(github, "check_origin"), patch.object(github, "inspect", return_value={"action": "create"}), patch.object(github, "_run") as runner, self.assertRaises(github.GitHubError):
                github.apply(self.config, root)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
