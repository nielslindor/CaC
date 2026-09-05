"""Deterministic public-workspace safety and SDLC checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator

from .lifecycle import source_digest, validate_change

_SKIP = {".git", ".venv", "build", "dist", ".cac", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_SKIP_FILES = {".DS_Store", ".coverage"}
_SENSITIVE = re.compile(r"(^|/)(?:\.env|id_rsa|credentials|secrets?|tokens?)(?:\.|$)", re.I)
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b")),
    ("home-absolute", re.compile(r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+")),
    ("private-ip", re.compile(rf"\b(?:10(?:\.{_OCTET}){{3}}|192\.168(?:\.{_OCTET}){{2}}|172\.(?:1[6-9]|2\d|3[01])(?:\.{_OCTET}){{2}})\b")),
]
_MD_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)(?:\s+['\"][^)]*)?\)")
_AGENT_KEYS = {"name", "description", "developer_instructions", "sandbox_mode"}
_AGENT_REQUIRED = {"name", "description", "developer_instructions"}
_POLICY_NAME = "cac-policy.json"
_PROFILES = {"workspace", "public"}


def _safe_root(root: str | Path) -> Path:
    path = Path(root)
    if not path.exists() or path.is_symlink() or not path.is_dir():
        raise ValueError("root is unsafe")
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise ValueError("root ancestor is a symlink")
    return absolute


def _ignored(parts: tuple[str, ...]) -> bool:
    return parts[:2] == ("docs", "changes") or any(part in _SKIP or part.endswith(".egg-info") for part in parts)


def _files(root: Path) -> Iterator[tuple[Path, str | None]]:
    """Yield ordinary files and discovered symlinks without entering either."""
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_current = current_path.relative_to(root)
        kept: list[str] = []
        for name in directories:
            path = current_path / name
            parts = rel_current.parts + (name,)
            if path.is_symlink():
                yield path, "symlink"
            elif _ignored(parts):
                continue
            else:
                kept.append(name)
        directories[:] = kept
        for name in filenames:
            if name in _SKIP_FILES:
                continue
            path = current_path / name
            if path.is_symlink():
                yield path, "symlink"
            elif not _ignored(path.relative_to(root).parts):
                yield path, None


def _agent_config_path(relative: Path) -> bool:
    parts = relative.parts
    return relative.suffix == ".toml" and any(parts[index:index + 2] == (".codex", "agents") for index in range(len(parts) - 1))


def _valid_agent_config(value: Any) -> bool:
    if not isinstance(value, dict) or not _AGENT_REQUIRED.issubset(value) or set(value) - _AGENT_KEYS:
        return False
    if not all(isinstance(value[key], str) and value[key].strip() for key in _AGENT_REQUIRED):
        return False
    return "sandbox_mode" not in value or (isinstance(value["sandbox_mode"], str) and value["sandbox_mode"].strip())


def _link_target_is_safe(root: Path, source: Path, link: str) -> bool:
    target_part = link.split("#", 1)[0]
    if not target_part:
        return True
    candidate = Path(os.path.normpath(os.fspath(source.parent / target_part)))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return candidate.exists() and not candidate.is_symlink()


def _policy_profile(root: Path, override: str | None) -> tuple[str | None, bool]:
    """Return the selected profile and whether the policy was valid.

    A policy is deliberately tiny and strict.  In particular, a malformed
    policy cannot be bypassed by supplying an API or CLI override.
    """
    policy = root / _POLICY_NAME
    if policy.is_symlink() or (policy.exists() and not policy.is_file()):
        return None, False
    if policy.exists():
        try:
            value = json.loads(policy.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None, False
        schema_version = value.get("schema_version") if isinstance(value, dict) else None
        policy_profile = value.get("profile") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "profile"}
            or isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != 1
            or not isinstance(policy_profile, str)
            or policy_profile not in _PROFILES
        ):
            return None, False
        selected = policy_profile
    else:
        selected = "public"
    if override is not None and (not isinstance(override, str) or override not in _PROFILES):
        return None, False
    return override or selected, True


def _lifecycle_checks(root: Path, checks: list[dict[str, str]], failures: list[dict[str, str]]) -> None:
    changes = root / "docs" / "changes"
    if changes.is_symlink():
        failures.append({"rule": "symlink", "path": "docs/changes"})
        return
    if not changes.is_dir():
        return
    try:
        entries = list(changes.iterdir())
    except OSError:
        failures.append({"rule": "io", "path": "docs/changes"})
        return
    for record_dir in entries:
        relative = f"docs/changes/{record_dir.name}"
        if record_dir.is_symlink():
            failures.append({"rule": "symlink", "path": relative})
            continue
        if not record_dir.is_dir():
            failures.append({"rule": "lifecycle", "path": relative})
            continue
        try:
            declared = json.loads((record_dir / "change.json").read_text(encoding="utf-8")).get("stage")
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
            declared = None
        stage = declared if isinstance(declared, str) and declared in {"draft", "planned", "verified", "released"} else "released"
        ok, reasons = validate_change(root, record_dir.name, stage, compare_digest=False)
        checks.append({"rule": "lifecycle", "path": relative, "status": "draft" if stage == "draft" and ok else ("pass" if ok else "fail")})
        if not ok:
            failures.extend({"rule": "lifecycle:" + reason, "path": relative} for reason in reasons)


def run_gauntlet(root: str | Path = ".", run_tests: bool = False, *, profile: str | None = None) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checks: list[dict[str, str]] = []
    try:
        root_path = _safe_root(root)
        digest = source_digest(root_path)
    except (OSError, ValueError):
        return {"status": "fail", "source_tree_digest": None, "profile": None, "checks": checks, "failures": [{"rule": "root", "path": str(root)}]}
    selected_profile, valid_policy = _policy_profile(root_path, profile)
    if not valid_policy:
        return {"status": "fail", "source_tree_digest": digest, "profile": None, "checks": checks, "failures": [{"rule": "policy", "path": _POLICY_NAME}]}
    workspace = selected_profile == "workspace"
    for path, kind in _files(root_path):
        relative = path.relative_to(root_path).as_posix()
        if kind:
            failures.append({"rule": "symlink", "path": relative})
            continue
        if not path.is_file():
            failures.append({"rule": "nonregular-file", "path": relative})
            continue
        if _SENSITIVE.search(relative):
            failures.append({"rule": "sensitive-filename", "path": relative})
        try:
            content = path.read_bytes()
        except OSError:
            failures.append({"rule": "io", "path": relative})
            continue
        if b"\0" in content:
            if workspace:
                if path.suffix in {".json", ".toml"}:
                    failures.append({"rule": "parse", "path": relative})
                else:
                    checks.append({"rule": "binary-content", "path": relative, "status": "not-scanned"})
            else:
                failures.append({"rule": "unexpected-binary", "path": relative})
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            if workspace:
                if path.suffix in {".json", ".toml"}:
                    failures.append({"rule": "parse", "path": relative})
                else:
                    checks.append({"rule": "binary-content", "path": relative, "status": "not-scanned"})
            else:
                failures.append({"rule": "unexpected-binary", "path": relative})
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for rule, pattern in _PATTERNS:
                if workspace and rule in {"home-absolute", "private-ip"}:
                    continue
                if pattern.search(line):
                    failures.append({"rule": rule, "path": relative, "line": line_number})
            if path.suffix.lower() in {".md", ".markdown"}:
                for link in _MD_LINK.findall(line):
                    if link.startswith(("#", "http://", "https://", "mailto:", "ftp://")):
                        continue
                    if Path(link.split("#", 1)[0]).is_absolute():
                        if workspace:
                            checks.append({"rule": "markdown-link", "path": relative, "status": "not-checked"})
                        else:
                            failures.append({"rule": "markdown-link", "path": relative, "line": line_number})
                        continue
                    if not _link_target_is_safe(root_path, path, link):
                        failures.append({"rule": "markdown-link", "path": relative, "line": line_number})
        if path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError:
                failures.append({"rule": "parse", "path": relative})
        elif path.suffix == ".toml":
            try:
                import tomllib
                parsed = tomllib.loads(text)
            except (ValueError, TypeError):
                failures.append({"rule": "parse", "path": relative})
                continue
            if _agent_config_path(path.relative_to(root_path)) and not _valid_agent_config(parsed):
                failures.append({"rule": "agent-config", "path": relative})
    _lifecycle_checks(root_path, checks, failures)
    if run_tests:
        tests = root_path / "tests"
        if not tests.is_dir() or tests.is_symlink():
            failures.append({"rule": "tests", "path": "tests"})
        else:
            try:
                process = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root_path, timeout=120, capture_output=True, text=True)
                checks.append({"rule": "tests", "status": "pass" if process.returncode == 0 else "fail"})
                if process.returncode:
                    failures.append({"rule": "tests", "path": "tests"})
            except subprocess.TimeoutExpired:
                checks.append({"rule": "tests", "status": "timeout"})
                failures.append({"rule": "tests-timeout", "path": "tests"})
            except OSError:
                checks.append({"rule": "tests", "status": "error"})
                failures.append({"rule": "tests", "path": "tests"})
    return {"status": "fail" if failures else "pass", "source_tree_digest": digest, "profile": selected_profile, "checks": checks, "failures": failures}


def register_subcommands(subparsers: Any) -> None:
    parser = subparsers.add_parser("gauntlet", help="run deterministic workspace checks")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--profile", choices=sorted(_PROFILES))
    def run(args: Any) -> int:
        result = run_gauntlet(args.root, args.tests, profile=args.profile)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"{result['status']}: {len(result['failures'])} failure(s)")
        return 0 if result["status"] == "pass" else 1
    parser.set_defaults(func=run)
