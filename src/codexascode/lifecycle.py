"""Create and validate explicit SDLC change records."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_STAGES = ("planned", "verified", "released")
_RECORD_STAGES = ("draft",) + _STAGES
_MARKDOWN_FILES = ("intent.md", "spec.md", "plan.md", "verification.md", "release.md")
_FILES = _MARKDOWN_FILES + ("change.json",)
_EVIDENCE_KEYS = {"acceptance_criteria", "verification", "independent_review", "release_reference", "rollback_operations", "unresolved_blocking_findings", "source_tree_digest"}
_IGNORED_DIRECTORIES = {".git", ".cac", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"}
_IGNORED_FILES = {".DS_Store", ".coverage"}
_PLACEHOLDER = re.compile(r"\b(?:pending|todo|tbd|to be completed|not yet|replace this)\b", re.I)


def _safe_id(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value)) and value not in {".", ".."}


def _root(root: str | Path) -> Path:
    path = Path(root)
    if not path.exists() or path.is_symlink() or not path.is_dir():
        raise ValueError("root must be an existing directory and cannot be a symlink")
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise ValueError("root ancestors cannot be symlinks")
    return absolute


def _safe_record_dir(root: Path, change_id: str) -> Path:
    if not _safe_id(change_id):
        raise ValueError("unsafe change id")
    docs = root / "docs"
    base = docs / "changes"
    for path in (docs, base):
        if path.is_symlink():
            raise ValueError("record ancestors cannot be symlinks")
        if path.exists() and not path.is_dir():
            raise ValueError("record ancestors must be directories")
    target = base / change_id
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError("record path is unsafe")
    return target


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug or "change")[:90]


def _ignored_directory(parts: tuple[str, ...]) -> bool:
    return parts[:2] == ("docs", "changes") or any(part in _IGNORED_DIRECTORIES or part.endswith(".egg-info") for part in parts)


def source_digest(root: str | Path) -> str:
    """Digest source inputs while pruning generated and local-only paths."""
    root_path = _root(root)
    digest = hashlib.sha256()
    records: list[tuple[str, bytes]] = []
    for current, directories, files in os.walk(root_path, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(root_path)
        kept: list[str] = []
        for directory in directories:
            candidate = current_path / directory
            if candidate.is_symlink() or _ignored_directory(relative_current.parts + (directory,)):
                continue
            kept.append(directory)
        directories[:] = kept
        for filename in files:
            if filename in _IGNORED_FILES:
                continue
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root_path)
            if _ignored_directory(relative.parts):
                continue
            try:
                records.append((relative.as_posix(), path.read_bytes()))
            except OSError as exc:
                raise ValueError(f"cannot read source file {relative.as_posix()}: {exc}") from exc
    for name, content in sorted(records):
        digest.update(name.encode("utf-8") + b"\0" + str(len(content)).encode("ascii") + b"\0" + content)
    return digest.hexdigest()


def create_change(root: str | Path, title: str, change_id: str | None = None) -> int:
    try:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be non-empty")
        cid = change_id or _slug(title)
        root_path = _root(root)
        target = _safe_record_dir(root_path, cid)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return 0 if all((target / name).is_file() and not (target / name).is_symlink() for name in _FILES) else 2
        target.mkdir()
        placeholders = {
            "intent.md": "# Intent\n\nPending: describe the observable problem and outcome.\n",
            "spec.md": "# Specification\n\nPending: define acceptance criteria.\n",
            "plan.md": "# Plan\n\nPending: list implementation and verification steps.\n",
            "verification.md": "# Verification\n\nPending: record commands, evidence, and independent review.\n",
            "release.md": "# Release\n\nPending: record release reference, rollback, and operations.\n",
        }
        for name, body in placeholders.items():
            (target / name).write_text(body, encoding="utf-8", newline="\n")
        evidence = {"acceptance_criteria": [], "verification": [], "independent_review": [], "release_reference": None, "rollback_operations": [], "unresolved_blocking_findings": [], "source_tree_digest": None}
        record = {"schema_version": 1, "id": cid, "title": title, "stage": "draft", "files": list(_MARKDOWN_FILES), "evidence": evidence}
        (target / "change.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, ValueError):
        return 2


def _nonplaceholder_text(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return bool(text.strip()) and not _PLACEHOLDER.search(text)


def _valid_evidence_item(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip()) and not _PLACEHOLDER.search(value)
    if not isinstance(value, dict) or not value:
        return False
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or _PLACEHOLDER.search(key) or type(item) not in {str, int, float, bool}:
            return False
        if isinstance(item, str) and (not item.strip() or _PLACEHOLDER.search(item)):
            return False
    return True


def _valid_evidence_list(value: Any, *, required: bool) -> bool:
    return isinstance(value, list) and (bool(value) if required else True) and all(_valid_evidence_item(item) for item in value)


def _valid_schema(data: Any, change_id: str) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "record must be an object"
    expected = {"schema_version", "id", "title", "stage", "files", "evidence"}
    if set(data) != expected:
        return False, "record has unexpected or missing fields"
    if data["schema_version"] != 1 or data["id"] != change_id or not isinstance(data["title"], str) or not data["title"].strip():
        return False, "invalid schema or id"
    if not isinstance(data["stage"], str) or data["stage"] not in _RECORD_STAGES:
        return False, "invalid record stage"
    if data["files"] != list(_MARKDOWN_FILES):
        return False, "invalid record file list"
    evidence = data["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
        return False, "invalid evidence schema"
    for key in ("acceptance_criteria", "verification", "independent_review", "rollback_operations", "unresolved_blocking_findings"):
        if not _valid_evidence_list(evidence[key], required=False):
            return False, f"invalid evidence field: {key}"
    if evidence["release_reference"] is not None and not isinstance(evidence["release_reference"], str):
        return False, "invalid evidence field: release_reference"
    if isinstance(evidence["release_reference"], str) and _PLACEHOLDER.search(evidence["release_reference"]):
        return False, "invalid evidence field: release_reference"
    digest = evidence["source_tree_digest"]
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        return False, "invalid evidence field: source_tree_digest"
    return True, ""


def validate_change(root: str | Path, change_id: str, stage: str, *, compare_digest: bool = True) -> tuple[bool, list[str]]:
    if not isinstance(stage, str) or stage not in _RECORD_STAGES:
        return False, ["invalid stage"]
    try:
        root_path = _root(root)
        record_dir = _safe_record_dir(root_path, change_id)
        if not record_dir.is_dir():
            return False, ["record does not exist"]
        if any((record_dir / name).is_symlink() for name in _FILES):
            return False, ["record contains symlink"]
        data = json.loads((record_dir / "change.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return False, [f"invalid record: {exc}"]
    valid_schema, schema_reason = _valid_schema(data, change_id)
    if not valid_schema:
        return False, [schema_reason]
    if stage == "draft":
        return True, []
    reasons: list[str] = []
    for name in _FILES:
        if not (record_dir / name).is_file():
            reasons.append(f"missing {name}")
    evidence = data["evidence"]
    if not _nonplaceholder_text(record_dir / "intent.md"):
        reasons.append("intent is pending")
    if not _nonplaceholder_text(record_dir / "spec.md") or not _valid_evidence_list(evidence["acceptance_criteria"], required=True):
        reasons.append("acceptance criteria are pending")
    if not _nonplaceholder_text(record_dir / "plan.md"):
        reasons.append("plan is pending")
    if stage in {"verified", "released"}:
        if not _nonplaceholder_text(record_dir / "verification.md") or not _valid_evidence_list(evidence["verification"], required=True):
            reasons.append("verification evidence is pending")
        if not _valid_evidence_list(evidence["independent_review"], required=True):
            reasons.append("independent review is pending")
        digest = evidence["source_tree_digest"]
        if not isinstance(digest, str):
            reasons.append("source tree digest is missing")
        elif compare_digest and digest != source_digest(root_path):
            reasons.append("source tree digest does not match source tree")
        if evidence["unresolved_blocking_findings"]:
            reasons.append("unresolved blocking findings remain")
    if stage == "released":
        if not _nonplaceholder_text(record_dir / "release.md"):
            reasons.append("release record is pending")
        if not isinstance(evidence["release_reference"], str) or not evidence["release_reference"].strip() or _PLACEHOLDER.search(evidence["release_reference"]):
            reasons.append("release reference is missing")
        if not _valid_evidence_list(evidence["rollback_operations"], required=True):
            reasons.append("rollback or operations record is missing")
    return not reasons, reasons


def check_change(root: str | Path, change_id: str, stage: str) -> int:
    try:
        digest: str | None = source_digest(root)
    except (OSError, ValueError):
        digest = None
    try:
        ok, reasons = validate_change(root, change_id, stage)
    except (OSError, ValueError) as exc:
        ok, reasons = False, [f"invalid record: {exc}"]
    print(json.dumps({"status": "pass" if ok else "fail", "id": change_id, "stage": stage, "source_tree_digest": digest, "failures": reasons}, sort_keys=True))
    return 0 if ok else 1


def register_subcommands(subparsers: Any) -> None:
    change = subparsers.add_parser("change", help="create or check an SDLC change record")
    actions = change.add_subparsers(dest="change_action", required=True)
    new = actions.add_parser("new")
    new.add_argument("id")
    new.add_argument("--root", default=".")
    new.add_argument("--title", required=True)
    new.set_defaults(func=lambda args: create_change(args.root, args.title, args.id))
    check = actions.add_parser("check")
    check.add_argument("id")
    check.add_argument("--root", default=".")
    check.add_argument("--stage", choices=_STAGES, required=True)
    check.set_defaults(func=lambda args: check_change(args.root, args.id, args.stage))
