"""Deterministic public-workspace safety and SDLC checks."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator

from .lifecycle import source_digest, validate_change
from .policy import PolicyError, excluded, load_policy

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
_AGENT_KEYS = {
    "name", "description", "developer_instructions", "model",
    "model_reasoning_effort", "sandbox_mode", "mcp_servers", "skills",
}
_AGENT_REQUIRED = {"name", "description", "developer_instructions"}
_AGENT_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
_AGENT_SANDBOX_MODES = {"read-only", "workspace-write", "danger-full-access"}
_MCP_SERVER_KEYS = {
    "args", "auth", "bearer_token_env_var", "command", "cwd",
    "default_tools_approval_mode", "disabled_tools", "enabled", "enabled_tools",
    "env", "env_http_headers", "env_vars", "experimental_environment",
    "http_headers", "http_headers_helper", "oauth_resource", "oauth",
    "required", "scopes", "startup_timeout_ms", "startup_timeout_sec",
    "tool_timeout_sec", "tools", "url",
}
_MCP_APPROVAL_MODES = {"auto", "prompt", "writes", "approve"}
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


def _files(root: Path, local_roots: tuple[str, ...] = ()) -> Iterator[tuple[Path, str | None]]:
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
            elif _ignored(parts) or excluded((rel_current / name).as_posix() if rel_current.parts else name, local_roots):
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


def _agent_config_errors(value: Any) -> list[dict[str, str]]:
    """Validate the documented custom-agent compatibility surface.

    This is intentionally a compatibility check, rather than a local policy:
    model names and paths are open strings, while documented enums and nested
    TOML shapes are checked strictly so typos cannot silently pass.
    """
    errors: list[dict[str, str]] = []
    def error(field: str, message: str) -> None:
        errors.append({"field": field, "message": message})

    if not isinstance(value, dict):
        return [{"field": "agent", "message": "custom agent must be a TOML table"}]
    for key in sorted(set(value) - _AGENT_KEYS):
        error(key, "unsupported custom-agent field")
    for key in sorted(_AGENT_REQUIRED - set(value)):
        error(key, "required custom-agent field is missing")
    for key in _AGENT_REQUIRED:
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            error(key, "must be a non-empty string")
    if "model" in value and (not isinstance(value["model"], str) or not value["model"].strip()):
        error("model", "must be a non-empty string when provided")
    if "model_reasoning_effort" in value and value["model_reasoning_effort"] not in _AGENT_REASONING_EFFORTS:
        error("model_reasoning_effort", "must be one of: " + ", ".join(sorted(_AGENT_REASONING_EFFORTS)))
    if "sandbox_mode" in value and value["sandbox_mode"] not in _AGENT_SANDBOX_MODES:
        error("sandbox_mode", "must be one of: " + ", ".join(sorted(_AGENT_SANDBOX_MODES)))

    def strings(field: str, item: Any) -> None:
        if not isinstance(item, list) or not all(isinstance(v, str) and v.strip() for v in item):
            error(field, "must be an array of non-empty strings")
    def string_map(field: str, item: Any) -> None:
        if not isinstance(item, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in item.items()):
            error(field, "must be a string-to-string table")

    servers = value.get("mcp_servers")
    if servers is not None:
        if not isinstance(servers, dict):
            error("mcp_servers", "must be a table keyed by server id")
        else:
            for server_id, server in servers.items():
                prefix = f"mcp_servers.{server_id}"
                if not isinstance(server, dict):
                    error(prefix, "must be a TOML table")
                    continue
                for key in sorted(set(server) - _MCP_SERVER_KEYS):
                    error(f"{prefix}.{key}", "unsupported MCP server field")
                for key in ("url", "command", "cwd", "bearer_token_env_var", "http_headers_helper", "oauth_resource"):
                    if key in server and (not isinstance(server[key], str) or not server[key].strip()):
                        error(f"{prefix}.{key}", "must be a non-empty string")
                for key in ("enabled", "required"):
                    if key in server and not isinstance(server[key], bool):
                        error(f"{prefix}.{key}", "must be a boolean")
                for key in ("args", "enabled_tools", "disabled_tools", "scopes"):
                    if key in server:
                        strings(f"{prefix}.{key}", server[key])
                for key in ("env", "env_http_headers", "http_headers"):
                    if key in server:
                        string_map(f"{prefix}.{key}", server[key])
                if "env_vars" in server:
                    entries = server["env_vars"]
                    if not isinstance(entries, list):
                        error(f"{prefix}.env_vars", "must be an array of strings or name/source tables")
                    else:
                        for index, entry in enumerate(entries):
                            if isinstance(entry, str) and entry.strip():
                                continue
                            if not isinstance(entry, dict) or set(entry) - {"name", "source"} or not isinstance(entry.get("name"), str) or not entry["name"].strip() or entry.get("source", "local") not in {"local", "remote"}:
                                error(f"{prefix}.env_vars[{index}]", "must contain a name and optional local/remote source")
                for key in ("auth", "experimental_environment", "default_tools_approval_mode"):
                    if key in server:
                        allowed = {"auth": {"oauth", "chatgpt"}, "experimental_environment": {"local", "remote"}, "default_tools_approval_mode": _MCP_APPROVAL_MODES}[key]
                        if server[key] not in allowed:
                            error(f"{prefix}.{key}", "must be one of: " + ", ".join(sorted(allowed)))
                for key in ("startup_timeout_ms", "startup_timeout_sec", "tool_timeout_sec"):
                    if key in server and (not isinstance(server[key], (int, float)) or isinstance(server[key], bool) or not math.isfinite(server[key]) or server[key] < 0):
                        error(f"{prefix}.{key}", "must be a non-negative number")
                if "oauth" in server:
                    oauth = server["oauth"]
                    if not isinstance(oauth, dict) or set(oauth) - {"callback_port", "callback_url", "client_id"}:
                        error(f"{prefix}.oauth", "must contain only callback_port, callback_url, and client_id")
                    else:
                        for key in ("callback_url", "client_id"):
                            if key in oauth and (not isinstance(oauth[key], str) or not oauth[key].strip()):
                                error(f"{prefix}.oauth.{key}", "must be a non-empty string")
                        if "callback_port" in oauth and (not isinstance(oauth["callback_port"], int) or isinstance(oauth["callback_port"], bool) or oauth["callback_port"] <= 0):
                            error(f"{prefix}.oauth.callback_port", "must be a positive integer")
                if "tools" in server:
                    tools = server["tools"]
                    if not isinstance(tools, dict):
                        error(f"{prefix}.tools", "must be a table keyed by tool name")
                    else:
                        for tool, config in tools.items():
                            if not isinstance(config, dict) or set(config) - {"approval_mode", "output_token_limit"}:
                                error(f"{prefix}.tools.{tool}", "must contain only approval_mode and output_token_limit")
                            elif "approval_mode" in config and config["approval_mode"] not in _MCP_APPROVAL_MODES:
                                error(f"{prefix}.tools.{tool}.approval_mode", "has an invalid approval mode")
                            elif "output_token_limit" in config and (not isinstance(config["output_token_limit"], int) or isinstance(config["output_token_limit"], bool) or config["output_token_limit"] <= 0):
                                error(f"{prefix}.tools.{tool}.output_token_limit", "must be a positive integer")
    skills = value.get("skills")
    if skills is not None:
        if not isinstance(skills, dict) or set(skills) - {"config"}:
            error("skills", "must contain only config")
        elif "config" in skills:
            config = skills["config"]
            if not isinstance(config, list):
                error("skills.config", "must be an array of tables")
            else:
                for index, item in enumerate(config):
                    field = f"skills.config[{index}]"
                    if not isinstance(item, dict) or set(item) - {"enabled", "path"}:
                        error(field, "must contain only enabled and path")
                    else:
                        if "enabled" in item and not isinstance(item["enabled"], bool):
                            error(f"{field}.enabled", "must be a boolean")
                        if "path" in item and (not isinstance(item["path"], str) or not item["path"].strip()):
                            error(f"{field}.path", "must be a non-empty string")
    return errors


def _valid_agent_config(value: Any) -> bool:
    return not _agent_config_errors(value)


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
    try:
        selected, _ = load_policy(root, override)
    except PolicyError:
        return None, False
    return selected, True


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
    except (OSError, ValueError):
        return {"status": "fail", "source_tree_digest": None, "profile": None, "checks": checks, "failures": [{"rule": "root", "path": str(root)}]}
    try:
        selected_profile, local_roots = load_policy(root_path, profile)
    except (OSError, ValueError) as exc:
        message = str(exc)
        rule = "local-boundary" if "local-boundary" in message else "policy"
        return {"status": "fail", "source_tree_digest": None, "profile": None, "checks": checks, "failures": [{"rule": rule, "path": _POLICY_NAME}]}
    try:
        digest = source_digest(root_path)
    except (OSError, ValueError):
        return {"status": "fail", "source_tree_digest": None, "profile": None, "checks": checks, "failures": [{"rule": "root", "path": str(root)}]}
    workspace = selected_profile == "workspace"
    for path, kind in _files(root_path, local_roots):
        relative = path.relative_to(root_path).as_posix()
        if excluded(relative, local_roots):
            continue
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
            if _agent_config_path(path.relative_to(root_path)):
                for diagnostic in _agent_config_errors(parsed):
                    failures.append({"rule": "agent-config", "path": relative, "kind": "compatibility", **diagnostic})
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
