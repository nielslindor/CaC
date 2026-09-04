"""Verify the distributed wheel from an independent environment and directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

parser = argparse.ArgumentParser()
parser.add_argument("--wheel", required=True)
args = parser.parse_args()
wheel = Path(args.wheel).resolve()
env = dict(os.environ)
env.pop("PYTHONPATH", None)

with tempfile.TemporaryDirectory(prefix="cac-smoke-") as temporary:
    base = Path(temporary).resolve()
    runtime = base / "runtime"
    venv.EnvBuilder(with_pip=True).create(runtime)
    python = runtime / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True, cwd=base, env=env)
    workspace = base / "workspace"
    def cac(*options, success=True):
        result = subprocess.run([str(python), "-m", "codexascode", *options], cwd=base, env=env, capture_output=True, text=True)
        if (result.returncode == 0) != success:
            raise RuntimeError(f"Unexpected result for {options}: {result.stdout} {result.stderr}")
        return result
    cac("init", "--root", str(workspace), "--name", "smoke-project")
    required = [".git", "AGENTS.md", ".codex/agents/reviewer.toml", ".agents/skills/run-gauntlet/SKILL.md", ".vscode/tasks.json", ".github/workflows/verify.yml", "WORKBOARD.md", "infra/README.md"]
    assert all((workspace / path).exists() for path in required), "Missing packaged bootstrap asset"
    cac("verify", "--root", str(workspace))
    cac("gauntlet", "--root", str(workspace), "--json")
    original = (workspace / ".cac/state.json").read_bytes()
    second = json.loads(cac("apply", "--root", str(workspace)).stdout)
    assert second["changed"] is False, second
    assert original == (workspace / ".cac/state.json").read_bytes(), "State churn"
    managed = workspace / "AGENTS.md"
    expected = managed.read_bytes()
    managed.write_bytes(expected + b"\nA local edit.\n")
    cac("apply", "--root", str(workspace), success=False)
    cac("verify", "--root", str(workspace), success=False)
    assert managed.read_bytes() == expected + b"\nA local edit.\n"
    managed.write_bytes(expected)
    cac("change", "new", "smoke-change", "--root", str(workspace), "--title", "Exercise lifecycle gates")
    cac("change", "check", "smoke-change", "--root", str(workspace), "--stage", "verified", success=False)
    cac("verify", "--root", str(workspace))

    # Cross the actual hosted-repository boundary: an empty declared directory
    # disappears from Git, so the clone must be reconciled before verification.
    def git(*options, cwd):
        return subprocess.run(["git", *options], cwd=cwd, env=env, capture_output=True, text=True, check=True)
    git("-c", "user.name=CaC Smoke", "-c", "user.email=smoke@example.invalid", "add", "-A", cwd=workspace)
    git("-c", "user.name=CaC Smoke", "-c", "user.email=smoke@example.invalid", "commit", "-m", "initial smoke fixture", cwd=workspace)
    clone = (base / "clone").resolve()
    git("clone", str(workspace), str(clone), cwd=base)
    assert not (clone / "areas").exists(), "clone unexpectedly retained untracked empty directory"
    cac_clone = lambda *options, success=True: subprocess.run([str(python), "-m", "codexascode", *options], cwd=clone, env=env, capture_output=True, text=True)
    plan_clone = cac_clone("plan")
    assert plan_clone.returncode == 0 and json.loads(plan_clone.stdout)["changed"] is True, plan_clone.stdout + plan_clone.stderr
    apply_clone = cac_clone("apply")
    assert apply_clone.returncode == 0 and json.loads(apply_clone.stdout)["changed"] is True, apply_clone.stdout + apply_clone.stderr
    verify_clone = cac_clone("verify")
    assert verify_clone.returncode == 0, verify_clone.stdout + verify_clone.stderr
    gauntlet_clone = cac_clone("gauntlet", "--json")
    assert gauntlet_clone.returncode == 0, gauntlet_clone.stdout + gauntlet_clone.stderr
    repeat_plan = cac_clone("plan")
    repeat_apply = cac_clone("apply")
    assert repeat_plan.returncode == 0 and json.loads(repeat_plan.stdout)["changed"] is False, repeat_plan.stdout + repeat_plan.stderr
    assert repeat_apply.returncode == 0 and json.loads(repeat_apply.stdout)["changed"] is False, repeat_apply.stdout + repeat_apply.stderr
    assert git("status", "--porcelain", cwd=clone).stdout == "", "clone worktree is not clean after reconciliation"
    print(json.dumps({"packaged_bootstrap": "pass", "idempotency": "pass", "drift_refusal": "pass", "lifecycle_false_completion_refusal": "pass", "fresh_clone_reconciliation": "pass", "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}))
