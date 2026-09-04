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
    print(json.dumps({"packaged_bootstrap": "pass", "idempotency": "pass", "drift_refusal": "pass", "lifecycle_false_completion_refusal": "pass", "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}))
