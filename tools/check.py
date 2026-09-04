"""Run the same deterministic development checks used by CI."""

from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
environment = dict(os.environ)
environment["PYTHONPATH"] = str(root / "src")
for args in ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
             [sys.executable, "-m", "codexascode", "gauntlet", "--root", str(root), "--json"]):
    result = subprocess.run(args, cwd=root, env=environment)
    if result.returncode:
        raise SystemExit(result.returncode)
