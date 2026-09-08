#!/usr/bin/env python3
"""Small Git-backed coordination leases for independent CaC hosts.

The coordination ref is deliberately separate from the project's normal branch.
Participants exchange the claim token out of band; only its SHA-256 digest is
written to the remote state.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


STATE_REF = "refs/heads/cac-coordination"
STATE_FILE = "coordination.json"
SCHEMA_VERSION = 1
MAX_TEXT = 512
MAX_EFFECTIVE_KEYS = 64


class CoordinationError(RuntimeError):
    """An expected coordination failure."""


class LeaseConflict(CoordinationError):
    pass


class LeaseDenied(CoordinationError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _safe_remote(remote: str) -> str:
    try:
        parts = urlsplit(remote)
        if parts.username is None and parts.password is None:
            return remote
        host = parts.hostname or "remote"
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    except ValueError:
        return "<remote>"


def _safe_detail(detail: str, remote: str) -> str:
    detail = detail.replace(remote, _safe_remote(remote))
    return re.sub(r"(https?://)[^/\s@]+@", r"\1<credentials>@", detail)


def _bounded(value: str, name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise LeaseDenied(f"{name} must be non-empty text of at most {limit} characters")
    return value


def _run(args: list[str], cwd: Path, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise CoordinationError("Git operation timed out") from exc
    except OSError as exc:
        raise CoordinationError(f"unable to run Git: {exc}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        detail = re.sub(r"(https?://)[^/\s@]+@", r"\1<credentials>@", detail)
        raise CoordinationError(f"Git operation failed: {detail[:400]}")
    return result


@dataclass
class CoordinationStore:
    remote: str
    cache_dir: Path | None = None
    state_ref: str = STATE_REF

    def __post_init__(self) -> None:
        self.remote = str(self.remote)
        parts=urlsplit(self.remote)
        if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise CoordinationError("remote must not contain credentials or query parameters")
        if self.cache_dir is None:
            key = hashlib.sha256(self.remote.encode()).hexdigest()[:20]
            self.cache_dir = Path.home() / ".cache" / "cac" / "coordination" / key
        self.cache_dir = Path(self.cache_dir).absolute()
        if any(p.is_symlink() for p in [self.cache_dir,*self.cache_dir.parents,self.cache_dir/".git"]):
            raise CoordinationError("coordination cache must not be a symlink")
        if self.state_ref == "refs/heads/main" or not self.state_ref.startswith("refs/heads/cac-"):
            raise CoordinationError("state ref must be a refs/heads/cac-* ref")
        self.cache_dir.parent.mkdir(parents=True, exist_ok=True)
        if not (self.cache_dir / ".git").exists():
            if self.cache_dir.exists() and any(self.cache_dir.iterdir()):
                raise CoordinationError(f"cache directory is not an empty Git repository: {self.cache_dir}")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            result = _run(["git", "init", str(self.cache_dir)], Path.cwd())
            if result.returncode:
                raise CoordinationError("could not initialize coordination cache")
            _run(["git", "remote", "add", "origin", self.remote], self.cache_dir)
        else:
            current = _run(["git", "remote", "get-url", "origin"], self.cache_dir).stdout.strip()
            if current != self.remote:
                raise CoordinationError("coordination cache belongs to a different remote")

        self.cache_dir.chmod(0o700)

    @contextlib.contextmanager
    def _lock(self):
        lock_path = self.cache_dir.parent / (self.cache_dir.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if lock_path.is_symlink():raise CoordinationError("lock must not be a symlink")
        with lock_path.open("a+", encoding="utf-8") as handle:
            os.chmod(lock_path,0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _head_unlocked(self) -> tuple[str | None, dict[str, Any]]:
        ls = _run(["git", "ls-remote", "origin", self.state_ref], self.cache_dir)
        fields = ls.stdout.strip().split()
        old = fields[0] if fields else None
        if old:
            fetched = _run(["git", "fetch", "--quiet", "origin", self.state_ref], self.cache_dir)
            del fetched
            old = _run(["git", "rev-parse", "FETCH_HEAD"], self.cache_dir).stdout.strip()
            size=int(_run(["git","cat-file","-s",f"FETCH_HEAD:{STATE_FILE}"],self.cache_dir).stdout)
            if size>1024*1024:raise CoordinationError("coordination state exceeds limit")
            raw = _run(["git", "show", f"FETCH_HEAD:{STATE_FILE}"], self.cache_dir).stdout
            try:
                state = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CoordinationError("coordination ref contains invalid JSON") from exc
            if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
                raise CoordinationError("coordination ref has an unsupported schema")
            state.setdefault("leases", {})
            state.setdefault("receipts", {})
            state.setdefault("discoveries", {})
            return old, state
        return None, {"schema_version": SCHEMA_VERSION, "leases": {}, "receipts": {}, "discoveries": {}}

    def _push_unlocked(self, old: str | None, state: dict[str, Any]) -> None:
        payload = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode()
        if len(payload)>1024*1024:raise CoordinationError("coordination state exceeds limit")
        # hash-object receives the bounded payload directly and never touches the worktree.
        proc = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=self.cache_dir, input=payload,
                              text=False, capture_output=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=30)
        if proc.returncode:
            raise CoordinationError("Git operation failed while writing coordination state")
        blob = proc.stdout.decode().strip()
        # mktree receives one deterministic entry and does not inspect the worktree/index.
        proc = subprocess.run(["git", "mktree"], cwd=self.cache_dir,
                              input=f"100644 blob {blob}\t{STATE_FILE}\n", text=True,
                              capture_output=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=30)
        if proc.returncode:
            raise CoordinationError("Git operation failed while building coordination tree")
        tree = proc.stdout.strip()
        commit_cmd = ["git", "-c", "user.name=CaC Coordination", "-c", "user.email=cac-coordination@localhost",
                      "commit-tree", tree]
        if old:
            commit_cmd.extend(["-p", old])
        commit_cmd.extend(["-m", "Update coordination leases"])
        commit = _run(commit_cmd, self.cache_dir).stdout.strip()
        lease = f"{self.state_ref}:{old or ''}"
        result = _run(["git", "push", "origin", f"{commit}:{self.state_ref}", f"--force-with-lease={lease}"], self.cache_dir, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise LeaseConflict(f"coordination update lost a race on {_safe_remote(self.remote)}: {_safe_detail(detail, self.remote)[:300]}")

    def _head(self) -> tuple[str | None, dict[str, Any]]:
        with self._lock():
            return self._head_unlocked()

    def _push(self, old: str | None, state: dict[str, Any]) -> None:
        with self._lock():
            self._push_unlocked(old, state)

    def _mutate(self, fn: Any) -> Any:
        with self._lock():
            old, state = self._head_unlocked()
            before=json.dumps(state,sort_keys=True)
            value = fn(state)
            if json.dumps(state,sort_keys=True)!=before:self._push_unlocked(old, state)
            return value

    def claim(self, resource: str, *, host_id: str, task_id: str, agent_id: str,
              project: str, worktree: str, branch: str, source_revision: str,
              duration_seconds: int = 300) -> dict[str, Any]:
        resource = _bounded(resource, "resource")
        host_id, task_id, agent_id = (_bounded(v, n) for v, n in ((host_id, "host_id"), (task_id, "task_id"), (agent_id, "agent_id")))
        project, worktree, branch, source_revision = (_bounded(v, n) for v, n in ((project, "project"), (worktree, "worktree"), (branch, "branch"), (source_revision, "source_revision")))
        if duration_seconds <= 0 or duration_seconds > 86400:
            raise LeaseDenied("duration_seconds must be positive")
        token = secrets.token_urlsafe(32)
        now = _now()
        lease = {"host_id": host_id, "task_id": task_id, "agent_id": agent_id,
                 "project": project, "worktree": worktree, "branch": branch,
                 "source_revision": source_revision, "claimed_at": _stamp(now),
                 "heartbeat_at": _stamp(now), "expires_at": _stamp(now + timedelta(seconds=duration_seconds)),
                 "lease_token_hash": _token_hash(token)}

        def update(state: dict[str, Any]) -> dict[str, Any]:
            current = state["leases"].get(resource)
            if current and _parse_stamp(current["expires_at"]) > now:
                raise LeaseDenied(f"resource is actively leased: {resource}")
            state["leases"][resource] = lease
            return {"resource": resource, "lease": lease, "lease_token": token}

        return self._mutate(update)

    def renew(self, resource: str, token: str, *, duration_seconds: int = 300) -> dict[str, Any]:
        resource, token = _bounded(resource, "resource"), _bounded(token, "token", 1024)
        if duration_seconds <= 0 or duration_seconds > 86400:
            raise LeaseDenied("duration_seconds must be positive")
        now = _now()

        def update(state: dict[str, Any]) -> dict[str, Any]:
            lease = state["leases"].get(resource)
            if not lease or lease.get("lease_token_hash") != _token_hash(token):
                raise LeaseDenied("invalid lease token")
            if _parse_stamp(lease["expires_at"]) <= now:
                raise LeaseDenied("lease has expired")
            lease["heartbeat_at"] = _stamp(now)
            lease["expires_at"] = _stamp(now + timedelta(seconds=duration_seconds))
            return {"resource": resource, "lease": lease}

        return self._mutate(update)

    def release(self, resource: str, token: str) -> dict[str, Any]:
        resource, token = _bounded(resource, "resource"), _bounded(token, "token", 1024)
        def update(state: dict[str, Any]) -> dict[str, Any]:
            lease = state["leases"].get(resource)
            if not lease or lease.get("lease_token_hash") != _token_hash(token):
                raise LeaseDenied("invalid lease token")
            del state["leases"][resource]
            return {"resource": resource, "released": True}
        return self._mutate(update)

    def list_leases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            raise LeaseDenied("limit must be positive")
        _old, state = self._head()
        now = _now()
        items = []
        for resource, lease in sorted(state["leases"].items())[:limit]:
            item = dict(lease)
            item["resource"] = resource
            item["status"] = "active" if _parse_stamp(lease["expires_at"]) > now else "stale"
            item.pop("lease_token_hash", None)
            items.append(item)
        return items

    def put_receipt(self, host_id: str, *, revision: str, observed_at: str | None,
                    status: str, codex_version: str, effective: dict[str, bool]) -> dict[str, Any]:
        """Publish bounded host health metadata; values are intentionally allow-listed."""
        host_id, revision, status, codex_version = (_bounded(v, n) for v, n in ((host_id, "host_id"), (revision, "revision"), (status, "status"), (codex_version, "codex_version")))
        if observed_at is not None: observed_at = _bounded(observed_at, "observed_at")
        if not isinstance(effective, dict) or len(effective) > MAX_EFFECTIVE_KEYS or any(not isinstance(k, str) or len(k) > 64 or not re.fullmatch(r"[A-Za-z0-9_.-]+", k) or not isinstance(v, bool) for k, v in effective.items()):
            raise LeaseDenied("effective must be a mapping of boolean values")
        receipt = {"revision": revision, "observed_at": observed_at or _stamp(_now()),
                   "status": status, "codex_version": codex_version,
                   "effective": dict(sorted(effective.items()))}
        def update(state: dict[str, Any]) -> dict[str, Any]:
            state.setdefault("receipts", {})[host_id] = receipt
            return {"host_id": host_id, "receipt": receipt}
        return self._mutate(update)

    def get_receipts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            raise LeaseDenied("limit must be positive")
        _old, state = self._head()
        result = []
        for host_id, receipt in sorted(state.get("receipts", {}).items())[:limit]:
            result.append(dict({"host_id": host_id}, **receipt))
        return result

    def put_discovery(self, host_id: str, skills: dict[str, str]) -> dict[str, Any]:
        """Publish only skill names and content digests discovered on a host."""
        host_id = _bounded(host_id, "host_id")
        if not isinstance(skills, dict) or len(skills) > 512:
            raise LeaseDenied("skills must be a bounded name-to-sha256 mapping")
        clean: dict[str, str] = {}
        for name, digest in skills.items():
            if not isinstance(name, str) or len(name) > 128 or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", name):
                raise LeaseDenied("skill names contain unsupported characters")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise LeaseDenied("skill entries must be SHA-256 digests")
            clean[name] = digest.lower()
        discovery = {"skills": dict(sorted(clean.items())), "observed_at": _stamp(_now())}
        def update(state: dict[str, Any]) -> dict[str, Any]:
            state.setdefault("discoveries", {})[host_id] = discovery
            return {"host_id": host_id, "discovery": discovery}
        return self._mutate(update)

    def list_discoveries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            raise LeaseDenied("limit must be positive")
        _old, state = self._head()
        return [dict({"host_id": host}, **item) for host, item in sorted(state.get("discoveries", {}).items())[:limit]]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Coordinate cross-host work with Git-backed leases")
    p.add_argument("--remote", required=True, help="private Git remote URL or path")
    p.add_argument("--cache-dir", type=Path, help="local cache repository outside the active worktree")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("claim"); c.add_argument("resource");
    for name in ("host-id", "task-id", "agent-id", "project", "worktree", "branch", "source-revision"):
        c.add_argument(f"--{name}", required=True)
    c.add_argument("--duration", type=int, default=300)
    r = sub.add_parser("renew"); r.add_argument("resource"); r.add_argument("--token", required=True); r.add_argument("--duration", type=int, default=300)
    x = sub.add_parser("release"); x.add_argument("resource"); x.add_argument("--token", required=True)
    l = sub.add_parser("list"); l.add_argument("--limit", type=int, default=100)
    h = sub.add_parser("receipt-put"); h.add_argument("host_id"); h.add_argument("--revision", required=True); h.add_argument("--observed-at"); h.add_argument("--status", required=True); h.add_argument("--codex-version", required=True); h.add_argument("--effective", default="{}", help="JSON object of boolean flags")
    g = sub.add_parser("receipt-list"); g.add_argument("--limit", type=int, default=100)
    d = sub.add_parser("discovery-put"); d.add_argument("host_id"); d.add_argument("--skills", required=True, help="JSON object mapping skill names to SHA-256")
    q = sub.add_parser("discovery-list"); q.add_argument("--limit", type=int, default=100)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = CoordinationStore(args.remote, args.cache_dir)
        if args.command == "claim":
            result = store.claim(args.resource, host_id=args.host_id, task_id=args.task_id, agent_id=args.agent_id,
                                 project=args.project, worktree=args.worktree, branch=args.branch,
                                 source_revision=args.source_revision, duration_seconds=args.duration)
        elif args.command == "renew": result = store.renew(args.resource, args.token, duration_seconds=args.duration)
        elif args.command == "release": result = store.release(args.resource, args.token)
        elif args.command == "list": result = {"leases": store.list_leases(limit=args.limit)}
        elif args.command == "receipt-put":
            try: effective = json.loads(args.effective)
            except json.JSONDecodeError as exc: raise LeaseDenied("--effective must be valid JSON") from exc
            result = store.put_receipt(args.host_id, revision=args.revision, observed_at=args.observed_at,
                                       status=args.status, codex_version=args.codex_version, effective=effective)
        elif args.command == "receipt-list": result = {"receipts": store.get_receipts(limit=args.limit)}
        elif args.command == "discovery-put":
            try: skills = json.loads(args.skills)
            except json.JSONDecodeError as exc: raise LeaseDenied("--skills must be valid JSON") from exc
            result = store.put_discovery(args.host_id, skills)
        else: result = {"discoveries": store.list_discoveries(limit=args.limit)}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except CoordinationError as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
