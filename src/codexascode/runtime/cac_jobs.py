#!/usr/bin/env python3
"""Declarative, at-most-once dispatch of allow-listed host-local jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:
    from .cac_coordination import CoordinationStore, LeaseDenied
    from .cac_work import run_work
    from .cac_fleet import safe_path, git
else:
    from .cac_coordination import CoordinationStore, LeaseDenied
    from .cac_work import run_work
    from .cac_fleet import safe_path, git

JOBS_REF = "refs/heads/cac-jobs"
MAX = 128
MAX_FILE = 1024 * 1024


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX or any(ord(c) < 32 for c in value):
        raise LeaseDenied(f"{name} is invalid or too long")
    return value


def _id(value: Any, name: str) -> str:
    value = _text(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value):
        raise LeaseDenied(f"{name} contains unsupported characters")
    return value

def _task(value: Any) -> str:
    value = _text(value, "task_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value): raise LeaseDenied("task_id contains unsupported characters")
    return value


class JobQueue:
    def __init__(self, remote: str, cache_dir: Path | None = None):
        self.store = CoordinationStore(remote, cache_dir, state_ref=JOBS_REF)

    def enqueue(self, job_name: str, target_host: str, task_id: str, generation: str) -> dict[str, Any]:
        job_name, target_host, generation = (_id(v, n) for v, n in ((job_name, "job_name"), (target_host, "target_host"), (generation, "generation")))
        task_id = _task(task_id)
        record = {"job_name": job_name, "target_host": target_host, "task_id": task_id,
                  "generation": generation, "status": "pending", "created_at": _stamp()}
        def update(state: dict[str, Any]) -> dict[str, Any]:
            jobs = state.setdefault("jobs", {})
            if len(jobs) >= 1000:
                raise LeaseDenied("job queue is full")
            if task_id in jobs:
                raise LeaseDenied("task_id is already queued")
            jobs[task_id] = record
            return dict(record)
        return self.store._mutate(update)

    def claim_next(self, host_id: str, generation: str) -> dict[str, Any] | None:
        host_id, generation = _id(host_id, "host_id"), _id(generation, "generation")
        def update(state: dict[str, Any]) -> dict[str, Any] | None:
            for task_id, job in sorted(state.setdefault("jobs", {}).items()):
                if job.get("status") == "pending" and job.get("target_host") == host_id and job.get("generation") == generation:
                    job["status"] = "running"; job["started_at"] = _stamp(); job["claimed_by"] = host_id
                    return {"task_id": task_id, **job}
            return None
        return self.store._mutate(update)

    def finish(self, task_id: str, host_id: str, status: str, *, exit_code: int | None = None) -> dict[str, Any]:
        task_id, host_id, status = _task(task_id), _id(host_id, "host_id"), _id(status, "status")
        if status not in {"completed", "failed"}:
            raise LeaseDenied("invalid terminal job status")
        def update(state: dict[str, Any]) -> dict[str, Any]:
            job = state.setdefault("jobs", {}).get(task_id)
            if not job or job.get("status") != "running" or job.get("claimed_by") != host_id:
                raise LeaseDenied("job is not owned by this running host")
            job["status"] = status; job["finished_at"] = _stamp()
            if exit_code is not None: job["exit_code"] = int(exit_code)
            return {"task_id": task_id, **job}
        return self.store._mutate(update)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or limit <= 0 or limit > 1000: raise LeaseDenied("invalid job limit")
        _old, state = self.store._head()
        return [{"task_id": task, **job} for task, job in sorted(state.get("jobs", {}).items())[:limit]]


def generation_jobs(generation: Path) -> tuple[str, dict[str, Any]]:
    generation = safe_path(generation)
    path = Path(generation) / "fleet-jobs.json"
    safe_path(path)
    if not path.is_file(): raise LeaseDenied("fleet-jobs.json is missing")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE: raise LeaseDenied("fleet-jobs.json is too large")
    digest = hashlib.sha256(raw).hexdigest()
    doc = json.loads(raw)
    if doc.get("schema_version") != 1 or not isinstance(doc.get("jobs"), dict): raise LeaseDenied("invalid fleet-jobs generation")
    clean = {}
    for name, spec in doc["jobs"].items():
        _id(name, "job_name")
        if not isinstance(spec, dict) or not isinstance(spec.get("command"), list) or not spec["command"]: raise LeaseDenied("job command must be a non-empty list")
        if len(spec["command"]) > 64 or any(not isinstance(x, str) or not x or len(x) > MAX for x in spec["command"]): raise LeaseDenied("job command is invalid")
        project = spec.get("project")
        if not isinstance(project, str) or not Path(project).is_absolute(): raise LeaseDenied("job project must be absolute")
        clean[name] = {"scope": _id(spec.get("scope"), "scope"), "project": project, "command": list(spec["command"]), "target_host": _id(spec.get("target_host"), "target_host")}
    return digest, clean


def validate_generation_path(state: Path, generation: Path) -> Path:
    state, generation = safe_path(Path(state)), safe_path(Path(generation))
    if generation.parent != state / 'generations':
        raise LeaseDenied('generation is outside the enrolled generations directory')
    actual = git('rev-parse', 'HEAD', cwd=generation)
    if generation.name != actual:
        raise LeaseDenied('generation identity does not match its checkout')
    if git('status', '--porcelain', '--untracked-files=all', cwd=generation):
        raise LeaseDenied('generation checkout has local changes')
    return generation


def run_once(state: Path, generation: Path) -> dict[str, Any] | None:
    state, generation = safe_path(Path(state)), validate_generation_path(Path(state), Path(generation))
    enrollment = json.loads((state / "enrollment.json").read_text())
    host = _id(enrollment.get("host_id"), "host_id")
    remote = enrollment.get("remote")
    revision, jobs = generation_jobs(generation)
    if not jobs:
        return None
    roots = enrollment.get('project_roots')
    if not isinstance(roots, list) or not roots:
        raise LeaseDenied('enrollment has no project roots')
    safe_roots = [safe_path(Path(root)) for root in roots if isinstance(root, str) and Path(root).is_absolute()]
    if not safe_roots:
        raise LeaseDenied('enrollment has no valid project roots')
    for spec in jobs.values():
        if spec['target_host'] != host: continue
        project = safe_path(Path(spec['project']))
        if not any(project == root or project.is_relative_to(root) for root in safe_roots):
            raise LeaseDenied('job project is outside enrolled project roots')
    queue = JobQueue(remote, state / "jobs-coordination")
    job = queue.claim_next(host, revision)
    if job is None: return None
    spec = jobs.get(job["job_name"])
    if spec is None or spec["target_host"] != host:
        queue.finish(job["task_id"], host, "failed")
        return {**job, "status": "failed"}
    try:
        result = run_work(state, Path(spec["project"]), spec["scope"], job["task_id"], "job-dispatch", spec["command"])
        status = "completed" if result.get("status") == "completed" else "failed"
        return queue.finish(job["task_id"], host, status, exit_code=result.get("exit_code"))
    except Exception:
        queue.finish(job["task_id"], host, "failed")
        raise


def _generation_arg(state: Path, value: str | None) -> Path:
    if value: return Path(value)
    current = json.loads((state / "current.json").read_text())
    selected = current.get("root") or current.get("generation") or current.get("path")
    if not isinstance(selected, str): raise LeaseDenied("current.json has no generation path")
    return Path(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/state/cac-fleet')
    parser.add_argument('--generation', help='generation root; defaults to state/current.json')
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('enqueue'); e.add_argument('job_name'); e.add_argument('task_id')
    l = sub.add_parser('list'); l.add_argument('--limit', type=int, default=100)
    sub.add_parser('run-once')
    args = parser.parse_args(argv)
    try:
        state = Path(args.state)
        enrollment = json.loads((state/'enrollment.json').read_text()); remote = enrollment['remote']; host = enrollment['host_id']
        if args.command == 'list':
            queue = JobQueue(remote, state/'jobs-coordination')
            result = {'jobs': queue.list(args.limit)}
            print(json.dumps(result, indent=2, sort_keys=True)); return 0
        generation = validate_generation_path(state, _generation_arg(state, args.generation))
        digest, definitions = generation_jobs(generation)
        if args.command == 'enqueue':
            spec = definitions.get(args.job_name)
            if spec is None: raise LeaseDenied('job is not in the selected generation')
            queue = JobQueue(remote, state/'jobs-coordination')
            result = queue.enqueue(args.job_name, spec['target_host'], args.task_id, digest)
        else: result = run_once(state, generation)
        print(json.dumps(result, indent=2, sort_keys=True)); return 1 if isinstance(result, dict) and result.get('status') == 'failed' else 0
    except Exception:
        print(json.dumps({'status':'failed','message':'job operation failed; inspect local state and queue status'})); return 1

if __name__ == '__main__':
    raise SystemExit(main())
