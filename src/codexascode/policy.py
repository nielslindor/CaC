"""Validation of persisted content-check policy and local ownership boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

PROFILES = {"workspace", "public"}
_CORE_NAMES = {
    ".git", ".codex", ".agents", "docs", "changes", "cac.json", "cac-policy.json",
}


class PolicyError(ValueError):
    """A policy cannot be safely applied to this workspace."""


def _relative_root(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value or any(char in value for char in "*?[]{}"):
        raise PolicyError("local-boundary: each local root must be a non-empty POSIX path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise PolicyError("local-boundary: local roots must be strict relative paths")
    if path.parts[0] in _CORE_NAMES or path.parts[:2] == ("docs", "changes"):
        raise PolicyError("local-boundary: local root overlaps control-plane paths")
    return "/".join(path.parts)


def _git(root: Path, args: list[str], *, allow_failure: bool = False) -> tuple[int, str]:
    try:
        process = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise PolicyError("local-boundary: Git validation is unavailable") from exc
    if process.returncode:
        if not allow_failure:
            raise PolicyError("local-boundary: Git validation failed")
    return process.returncode, process.stdout


def _managed_paths(root: Path) -> tuple[set[str], set[str]]:
    manifest = root / "cac.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise PolicyError("local-boundary: manifest cac.json is missing or unsafe")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError("local-boundary: manifest cac.json is malformed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("spec"), dict):
        raise PolicyError("local-boundary: manifest cac.json is malformed")
    files = value["spec"].get("files", [])
    directories = value["spec"].get("directories", [])
    if not isinstance(files, list) or not isinstance(directories, list):
        raise PolicyError("local-boundary: manifest paths are malformed")
    managed_files: set[str] = set()
    managed_dirs: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PolicyError("local-boundary: manifest file paths are malformed")
        path = item["path"]
        if not isinstance(path, str) or not path or Path(path).is_absolute() or "\\" in path or any(char in path for char in "*?[]{}") or any(part in {"", ".", ".."} for part in path.split("/")):
            raise PolicyError("local-boundary: manifest paths are malformed")
        managed_files.add("/".join(Path(path).parts))
    for item in directories:
        if not isinstance(item, str) or not item or Path(item).is_absolute() or "\\" in item or any(char in item for char in "*?[]{}") or any(part in {"", ".", ".."} for part in item.split("/")):
            raise PolicyError("local-boundary: manifest paths are malformed")
        managed_dirs.add("/".join(Path(item).parts))
    return managed_files, managed_dirs


def _has_symlink_ancestor(root: Path, relative: str) -> bool:
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            return True
        if current.exists() and not current.is_dir() and current != root / relative:
            return True
    return False


def _validate_local_roots(root: Path, roots: Any, profile: str) -> tuple[str, ...]:
    if not isinstance(roots, list):
        raise PolicyError("local-boundary: local_roots must be a list")
    normalized = tuple(_relative_root(item) for item in roots)
    folded = tuple(item.casefold() for item in normalized)
    if len(set(folded)) != len(folded):
        raise PolicyError("local-boundary: local roots must not be duplicated")
    for index, candidate in enumerate(normalized):
        folded_candidate = folded[index]
        if any(folded_candidate == other or folded_candidate.startswith(other + "/") or other.startswith(folded_candidate + "/") for other in folded[:index]):
            raise PolicyError("local-boundary: local roots must not overlap")
        if _has_symlink_ancestor(root, candidate):
            raise PolicyError("local-boundary: local root has a symlink or unsafe ancestor")
        target = root / candidate
        if target.exists() and not target.is_dir():
            raise PolicyError("local-boundary: local root must be a directory")
    managed_files, managed_dirs = _managed_paths(root) if normalized else (set(), set())
    for candidate in normalized:
        folded_candidate = candidate.casefold()
        if any(path.casefold() == folded_candidate or path.casefold().startswith(folded_candidate + "/") or folded_candidate.startswith(path.casefold() + "/") for path in managed_files):
            raise PolicyError("local-boundary: local root overlaps a manifest-managed file")
        if any(path.casefold() == folded_candidate or path.casefold().startswith(folded_candidate + "/") for path in managed_dirs):
            raise PolicyError("local-boundary: local root overlaps a manifest-managed path")
        ignored_status, _ = _git(root, ["check-ignore", "--no-index", "--quiet", "--", candidate + "/"], allow_failure=True)
        if ignored_status != 0:
            ignored_status, _ = _git(root, ["check-ignore", "--no-index", "--quiet", "--", candidate], allow_failure=True)
        if ignored_status != 0:
            raise PolicyError("local-boundary: local root is not Git-ignored")
        tracked_status, tracked_output = _git(root, ["ls-files", "--", ":(literal)" + candidate])
        del tracked_status
        tracked = tracked_output.strip()
        if tracked:
            raise PolicyError("local-boundary: local root contains tracked files")
    if profile == "public" and normalized:
        raise PolicyError("local-boundary: public profile cannot declare local_roots")
    return normalized


def load_policy(root: str | Path, override: str | None = None) -> tuple[str, tuple[str, ...]]:
    """Return selected profile and validated local-only roots."""
    root_path = Path(root)
    policy = root_path / "cac-policy.json"
    if policy.is_symlink() or (policy.exists() and not policy.is_file()):
        raise PolicyError("policy: cac-policy.json is unsafe")
    if policy.exists():
        try:
            value = json.loads(policy.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PolicyError("policy: cac-policy.json is malformed") from exc
        if not isinstance(value, dict):
            raise PolicyError("policy: cac-policy.json is malformed")
        keys = set(value)
        if not {"schema_version", "profile"}.issubset(keys) or keys - {"schema_version", "profile", "local_roots"}:
            raise PolicyError("policy: cac-policy.json has unexpected fields")
        if type(value.get("schema_version")) is not int or value["schema_version"] != 1 or not isinstance(value.get("profile"), str) or value.get("profile") not in PROFILES:
            raise PolicyError("policy: cac-policy.json has invalid schema or profile")
        selected = value["profile"]
        roots = value.get("local_roots", [])
    else:
        selected, roots = "public", []
    if override is not None and (not isinstance(override, str) or override not in PROFILES):
        raise PolicyError("policy: invalid profile override")
    selected = override or selected
    return selected, _validate_local_roots(root_path, roots, selected)


def excluded(relative: str, roots: tuple[str, ...]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)
