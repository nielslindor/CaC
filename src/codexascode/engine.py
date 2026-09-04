"""Safe, local reconciliation for ``cac/v1`` Workspace manifests.

This module deliberately has no network or shell interpolation surface.  It
only creates declared directories and files, records content hashes for files
it owns, and can initialise an otherwise standalone local Git repository.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
from typing import Any

try:  # fcntl is present on the supported local Unix platforms.
    import fcntl
except ImportError:  # pragma: no cover - kept for a clear portable error.
    fcntl = None  # type: ignore[assignment]


STATE_VERSION = 1
STATE_DIRECTORY = ".cac"
STATE_FILENAME = "state.json"
LOCK_FILENAME = "apply.lock"


class EngineError(ValueError):
    """The manifest or local filesystem cannot be reconciled safely."""


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and strictly validate a Workspace manifest from JSON."""

    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineError(f"cannot load manifest {source}: {exc}") from exc
    return _validate_manifest(value)


def plan(manifest: dict[str, Any], root: str | os.PathLike[str]) -> dict[str, Any]:
    """Return the read-only reconciliation plan for *manifest* at *root*."""

    checked = _validate_manifest(manifest)
    root_path = _safe_root(root)
    return _make_plan(checked, root_path)


def apply(manifest: dict[str, Any], root: str | os.PathLike[str]) -> dict[str, Any]:
    """Apply a preflighted plan, returning its summary and useful state.

    Filesystem conflicts are reported in the returned plan rather than being
    partially applied.  Unsafe paths and malformed state raise ``EngineError``.
    """

    checked = _validate_manifest(manifest)
    root_path = _safe_root(root)
    initial = _make_plan(checked, root_path)
    if initial["conflicts"]:
        return {**initial, "state": _state_result("conflicted")}

    # The first preflight avoids creating a lock/state directory for a known
    # conflict.  Re-plan while locked before changing desired files.
    _make_root_directory(root_path)
    lock_path = _safe_state_path(root_path, LOCK_FILENAME)
    _ensure_state_directory(root_path)
    _require_regular_file(lock_path, allow_missing=True)
    if fcntl is None:  # pragma: no cover
        raise EngineError("exclusive local apply locks are unavailable")

    try:
        lock_handle = open(lock_path, "a+b")
    except OSError as exc:
        raise EngineError(f"cannot open apply lock: {exc}") from exc
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        final = _make_plan(checked, root_path)
        if final["conflicts"]:
            return {**final, "state": _state_result("conflicted")}

        state, state_exists = _read_state(root_path)
        changed = bool(final["changes"])
        _apply_filesystem_changes(checked, root_path, state)
        _apply_git_change(checked, root_path, final)

        desired_hashes = {
            item["path"]: _content_hash(item["content"])
            for item in checked["spec"]["files"]
        }
        # A missing state file is itself reconciled on first apply.  Do not
        # rewrite it during an identical repeat apply.
        if (not state_exists) or state.get("files") != desired_hashes:
            _write_state(root_path, desired_hashes)
            changed = True
        return {
            **final,
            "changed": changed,
            "state": _state_result("applied" if changed else "unchanged"),
        }
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()


def verify(manifest: dict[str, Any], root: str | os.PathLike[str]) -> dict[str, Any]:
    """Read-only check that declared managed files still match manifest state."""

    checked = _validate_manifest(manifest)
    root_path = _safe_root(root)
    drift: list[dict[str, str]] = []
    if not root_path.exists():
        return {"ok": False, "drift": [{"path": ".", "reason": "root-missing"}]}
    _reject_symlink_or_nonregular(root_path, expect_directory=True)
    state, state_exists = _read_state(root_path)
    for directory in checked["spec"]["directories"]:
        target = _safe_target(root_path, directory)
        if not target.is_dir():
            drift.append({"path": directory, "reason": "directory-missing"})
    git_changes: list[dict[str, str]] = []
    git_conflicts: list[dict[str, str]] = []
    _plan_git(checked, root_path, git_changes, git_conflicts)
    drift.extend({"path": item["path"], "reason": item["action"]} for item in git_changes)
    drift.extend(git_conflicts)

    declared_files = {entry["path"]: entry for entry in checked["spec"]["files"]}
    for path, entry in declared_files.items():
        target = _safe_target(root_path, path)
        observed = _file_digest_or_reason(target)
        desired = _content_hash(entry["content"])
        if observed != desired:
            drift.append({"path": path, "reason": observed if observed.startswith("!") else "content-differs"})
    return {"ok": not drift, "drift": drift, "ownership_state_present": state_exists}


def _validate_manifest(value: Any) -> dict[str, Any]:
    manifest = _object(value, "manifest", {"apiVersion", "kind", "metadata", "spec"})
    if manifest.get("apiVersion") != "cac/v1":
        raise EngineError("manifest.apiVersion must be 'cac/v1'")
    if manifest.get("kind") != "Workspace":
        raise EngineError("manifest.kind must be 'Workspace'")
    metadata = _object(manifest.get("metadata"), "metadata", {"name"})
    _nonempty_string(metadata.get("name"), "metadata.name")
    spec = _object(manifest.get("spec"), "spec", {"git", "directories", "files", "github"}, optional={"github"})

    git = _object(spec.get("git"), "spec.git", {"enabled", "defaultBranch"})
    if type(git.get("enabled")) is not bool:
        raise EngineError("spec.git.enabled must be a boolean")
    _nonempty_string(git.get("defaultBranch"), "spec.git.defaultBranch")
    branch = git["defaultBranch"]
    if branch.startswith(("-", ".")) or branch.endswith((".", "/", ".lock")) or any(char in branch for char in " \t\r\n\x00~^:?*[\\") or ".." in branch or "@{" in branch or "//" in branch or branch == "@":
        raise EngineError("spec.git.defaultBranch must be a valid branch name")

    directories = _string_list(spec.get("directories"), "spec.directories")
    files_value = spec.get("files")
    if not isinstance(files_value, list):
        raise EngineError("spec.files must be a list")
    files: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for directory in directories:
        normalized = _manifest_path(directory, "spec.directories")
        _add_unique_path(seen, normalized)
    normalized_directories = [_manifest_path(item, "spec.directories") for item in directories]
    for index, item in enumerate(files_value):
        file_entry = _object(item, f"spec.files[{index}]", {"path", "content"})
        path = _manifest_path(file_entry.get("path"), f"spec.files[{index}].path")
        content = file_entry.get("content")
        if not isinstance(content, str):
            raise EngineError(f"spec.files[{index}].content must be a string")
        _add_unique_path(seen, path)
        files.append({"path": path, "content": content})
    _reject_file_ancestors(files)
    _reject_file_directory_collisions(files, normalized_directories)

    github: dict[str, str] | None = None
    if "github" in spec:
        github_value = _object(spec["github"], "spec.github", {"repository", "visibility"})
        repository = _nonempty_string(github_value.get("repository"), "spec.github.repository")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
            raise EngineError("spec.github.repository must be owner/name")
        visibility = github_value.get("visibility")
        if not isinstance(visibility, str) or visibility not in {"public", "private"}:
            raise EngineError("spec.github.visibility must be 'public' or 'private'")
        github = {"repository": repository, "visibility": visibility}

    result: dict[str, Any] = {
        "apiVersion": "cac/v1",
        "kind": "Workspace",
        "metadata": {"name": metadata["name"]},
        "spec": {
            "git": {"enabled": git["enabled"], "defaultBranch": git["defaultBranch"]},
            "directories": normalized_directories,
            "files": files,
        },
    }
    if github is not None:
        result["spec"]["github"] = github
    return result


def _object(value: Any, label: str, keys: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EngineError(f"{label} must be an object")
    optional = optional or set()
    actual = set(value)
    if actual - keys:
        raise EngineError(f"{label} has unknown fields: {', '.join(sorted(actual - keys))}")
    missing = keys - optional - actual
    if missing:
        raise EngineError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EngineError(f"{label} must be a non-empty string")
    if "\x00" in value:
        raise EngineError(f"{label} contains a NUL byte")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EngineError(f"{label} must be a list of strings")
    return value


def _manifest_path(value: Any, label: str) -> str:
    path = _nonempty_string(value, label)
    if "\\" in path:
        raise EngineError(f"{label} must use portable '/' separators")
    pure = PurePosixPath(path)
    if pure.is_absolute() or path != pure.as_posix() or not pure.parts or any(part in {"", ".", ".."} for part in path.split("/")) or any(ord(c) < 32 for c in path) or ":" in path:
        raise EngineError(f"{label} must be a safe relative path")
    if any(part.casefold() in {".git", STATE_DIRECTORY} for part in pure.parts):
        raise EngineError(f"{label} targets protected path")
    return pure.as_posix()


def _add_unique_path(seen: dict[str, str], path: str) -> None:
    folded = path.casefold()
    if folded in seen:
        raise EngineError(f"duplicate manifest path: {path} and {seen[folded]}")
    seen[folded] = path


def _reject_file_ancestors(files: list[dict[str, str]]) -> None:
    paths = {item["path"].casefold() for item in files}
    for item in files:
        parts = item["path"].split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index]).casefold()
            if ancestor in paths:
                raise EngineError(f"file path is an ancestor of another file: {item['path']}")


def _reject_file_directory_collisions(files: list[dict[str, str]], directories: list[str]) -> None:
    for file_entry in files:
        file_path = file_entry["path"].casefold()
        for directory in directories:
            directory_path = directory.casefold()
            if directory_path.startswith(file_path + "/"):
                raise EngineError(
                    f"file path is an ancestor of declared directory: {file_entry['path']}"
                )


def _safe_root(root: str | os.PathLike[str]) -> Path:
    root_path = Path(root).absolute()
    # Do not resolve: resolving would hide an ancestor symlink.
    current = Path(root_path.anchor)
    for part in root_path.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            _reject_symlink_or_nonregular(current, expect_directory=True)
    return root_path


def _safe_target(root: Path, relative: str) -> Path:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            _reject_symlink_or_nonregular(current, expect_directory=(part != PurePosixPath(relative).parts[-1]))
    return current


def _reject_symlink_or_nonregular(path: Path, *, allow_missing: bool = False, expect_directory: bool = False) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if allow_missing:
            return
        raise
    if stat.S_ISLNK(mode):
        raise EngineError(f"symlink is not allowed: {path}")
    if expect_directory and not stat.S_ISDIR(mode):
        raise EngineError(f"directory required: {path}")
    if not expect_directory and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise EngineError(f"non-regular path is not allowed: {path}")


def _require_regular_file(path: Path, *, allow_missing: bool = False) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        if allow_missing:
            return
        raise
    if not stat.S_ISREG(mode):
        raise EngineError(f"regular file required: {path}")


def _safe_state_path(root: Path, name: str) -> Path:
    state_dir = root / STATE_DIRECTORY
    if state_dir.exists() or state_dir.is_symlink():
        _reject_symlink_or_nonregular(state_dir, expect_directory=True)
    path = state_dir / name
    if path.exists() or path.is_symlink():
        _require_regular_file(path)
    return path


def _read_state(root: Path) -> tuple[dict[str, Any], bool]:
    if not root.exists():
        return {"version": STATE_VERSION, "files": {}}, False
    state_path = _safe_state_path(root, STATE_FILENAME)
    if not state_path.exists():
        return {"version": STATE_VERSION, "files": {}}, False
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineError(f"invalid reconciliation state: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"version", "files"}:
        raise EngineError("invalid reconciliation state schema")
    if value.get("version") != STATE_VERSION or not isinstance(value.get("files"), dict):
        raise EngineError("unsupported reconciliation state")
    files: dict[str, str] = {}
    for path, digest in value["files"].items():
        normalized = _manifest_path(path, "state file path")
        if normalized != path or not isinstance(digest, str) or len(digest) != 64:
            raise EngineError("invalid reconciliation state file hash")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise EngineError("invalid reconciliation state file hash") from exc
        files[path] = digest
    return {"version": STATE_VERSION, "files": files}, True


def _make_plan(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    changes: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    if root.exists():
        _reject_symlink_or_nonregular(root, expect_directory=True)
    else:
        changes.append({"path": ".", "action": "create-root"})
    state, state_exists = _read_state(root)
    if not state_exists:
        changes.append({"path": f"{STATE_DIRECTORY}/{STATE_FILENAME}", "action": "initialize-state"})

    for directory in manifest["spec"]["directories"]:
        target = _safe_target(root, directory) if root.exists() else root / directory
        if not target.exists() and not target.is_symlink():
            changes.append({"path": directory, "action": "create-directory"})
        elif target.is_symlink():
            raise EngineError(f"symlink is not allowed: {target}")
        elif not target.is_dir():
            conflicts.append({"path": directory, "reason": "directory-blocked"})

    for entry in manifest["spec"]["files"]:
        relative = entry["path"]
        target = _safe_target(root, relative) if root.exists() else root / relative
        desired = _content_hash(entry["content"])
        recorded = state["files"].get(relative)
        if not target.exists() and not target.is_symlink():
            if recorded is not None:
                conflicts.append({"path": relative, "reason": "managed-file-missing"})
            else:
                changes.append({"path": relative, "action": "create-file"})
            continue
        if target.is_symlink():
            raise EngineError(f"symlink is not allowed: {target}")
        if not target.is_file():
            conflicts.append({"path": relative, "reason": "file-blocked"})
            continue
        observed = _hash_path(target)
        if recorded is None:
            if observed == desired:
                changes.append({"path": relative, "action": "adopt-file"})
            else:
                conflicts.append({"path": relative, "reason": "unmanaged-file-differs"})
        elif observed == desired and observed != recorded:
            changes.append({"path": relative, "action": "adopt-file"})
        elif observed != recorded:
            conflicts.append({"path": relative, "reason": "managed-file-modified"})
        elif desired != observed:
            changes.append({"path": relative, "action": "update-file"})

    for relative in state["files"]:
        if relative not in {entry["path"] for entry in manifest["spec"]["files"]}:
            changes.append({"path": relative, "action": "release-ownership"})
    _plan_git(manifest, root, changes, conflicts)
    return {"changes": changes, "conflicts": conflicts, "changed": bool(changes) and not bool(conflicts)}


def _plan_git(manifest: dict[str, Any], root: Path, changes: list[dict[str, str]], conflicts: list[dict[str, str]]) -> None:
    if not manifest["spec"]["git"]["enabled"]:
        return
    if not root.exists():
        ancestor = next((p for p in root.parents if p.exists()), None)
        if ancestor is not None and _git_toplevel(ancestor) is not None:
            raise EngineError("refusing to initialise inside a parent Git repository")
        changes.append({"path": ".git", "action": "initialize-git"})
        return
    git_dir = root / ".git"
    if git_dir.exists() or git_dir.is_symlink():
        _reject_symlink_or_nonregular(git_dir, expect_directory=True)
        info = git_dir / "info"
        if info.exists() or info.is_symlink():
            _reject_symlink_or_nonregular(info, expect_directory=True)
            _require_regular_file(info / "exclude", allow_missing=True)
    top = _git_toplevel(root)
    if top is None:
        if git_dir.exists():
            raise EngineError("existing .git is not a valid repository")
        if _contains_nested_git(root):
            raise EngineError("refusing to initialise a repository around a nested repository")
        changes.append({"path": ".git", "action": "initialize-git"})
        return
    # Git canonicalizes macOS /var paths to /private/var.  ``resolve`` here is
    # only an identity comparison after the lexical root path was checked.
    if top.resolve() != root.resolve():
        raise EngineError("refusing to initialise inside a parent Git repository")
    # defaultBranch applies at initialization; normal feature branches and CI
    # detached checkouts are valid desired repository state.


def _git_toplevel(root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).absolute()


def _git_branch(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _contains_nested_git(root: Path) -> bool:
    for current, directories, _ in os.walk(root, followlinks=False):
        if Path(current) == root:
            directories[:] = [item for item in directories if item != STATE_DIRECTORY]
            continue
        if ".git" in directories or ".git" in _:
            return True
    return False


def _make_root_directory(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EngineError(f"cannot create workspace root: {exc}") from exc
    _safe_root(root)


def _ensure_state_directory(root: Path) -> None:
    state_dir = root / STATE_DIRECTORY
    if state_dir.exists() or state_dir.is_symlink():
        _reject_symlink_or_nonregular(state_dir, expect_directory=True)
        return
    try:
        state_dir.mkdir()
    except OSError as exc:
        raise EngineError(f"cannot create state directory: {exc}") from exc


def _apply_filesystem_changes(manifest: dict[str, Any], root: Path, state: dict[str, Any]) -> None:
    for directory in manifest["spec"]["directories"]:
        _make_parent_directories(root, directory)
        target = _safe_target(root, directory)
        if not target.exists():
            target.mkdir()
    for entry in manifest["spec"]["files"]:
        relative = entry["path"]
        target = _safe_target(root, relative)
        if target.exists():
            continue
        _make_parent_directories(root, relative)
        _write_file_atomic(target, entry["content"].encode("utf-8"))
    # Preflight already established that every update is safe and owned.
    for entry in manifest["spec"]["files"]:
        target = _safe_target(root, entry["path"])
        desired = _content_hash(entry["content"])
        if target.exists() and _hash_path(target) != desired:
            _write_file_atomic(target, entry["content"].encode("utf-8"))


def _make_parent_directories(root: Path, relative: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            _reject_symlink_or_nonregular(current, expect_directory=True)
        else:
            current.mkdir()


def _write_file_atomic(path: Path, data: bytes) -> None:
    _reject_symlink_or_nonregular(path, allow_missing=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".cac-tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise EngineError(f"cannot write {path}: {exc}") from exc


def _apply_git_change(manifest: dict[str, Any], root: Path, result: dict[str, Any]) -> None:
    if not manifest["spec"]["git"]["enabled"]:
        return
    if any(item["action"] == "initialize-git" for item in result["changes"]):
        branch = manifest["spec"]["git"]["defaultBranch"]
        command = ["git", "init", "-b", branch, os.fspath(root)]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise EngineError(f"git initialization failed: {completed.stderr.strip()}")
    git_dir = root / ".git"
    if git_dir.exists():
        _reject_symlink_or_nonregular(git_dir, expect_directory=True)
        info = git_dir / "info"
        if not info.exists():
            info.mkdir()
        _reject_symlink_or_nonregular(info, expect_directory=True)
        exclude = git_dir / "info" / "exclude"
        _require_regular_file(exclude, allow_missing=True)
        _ensure_git_exclude(exclude)


def _ensure_git_exclude(path: Path) -> None:
    line = f"{STATE_DIRECTORY}/\n"
    existing = b""
    if path.exists():
        existing = path.read_bytes()
    if line.encode("utf-8") in {item + b"\n" for item in existing.splitlines()}:
        return
    with path.open("ab") as handle:
        if existing and not existing.endswith(b"\n"):
            handle.write(b"\n")
        handle.write(line.encode("utf-8"))


def _write_state(root: Path, hashes: dict[str, str]) -> None:
    state_path = _safe_state_path(root, STATE_FILENAME)
    payload = json.dumps(
        {"files": hashes, "version": STATE_VERSION},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    _write_file_atomic(state_path, payload)


def _state_result(status: str) -> dict[str, str]:
    return {"status": status, "path": f"{STATE_DIRECTORY}/{STATE_FILENAME}"}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise EngineError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def _file_digest_or_reason(path: Path) -> str:
    if path.is_symlink():
        return "!symlink"
    if not path.exists():
        return "!missing"
    if not path.is_file():
        return "!not-file"
    return _hash_path(path)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.EROFS}:
            raise
    finally:
        os.close(descriptor)
