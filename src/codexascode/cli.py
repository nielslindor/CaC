"""CLI entry point. JSON output is available on every reconciliation command."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from . import __version__, github
from . import engine


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def reconcile(args):
    root = Path(args.root).absolute()
    manifest_path = Path(args.manifest) if args.manifest else root / "cac.json"
    manifest = engine.load_manifest(manifest_path)
    remote = manifest["spec"].get("github")
    remote_state = None
    if remote:
        if not manifest["spec"]["git"]["enabled"]:
            raise engine.EngineError("GitHub requires local Git enabled")
        github.check_origin(remote, root)
        remote_state = github.inspect(remote)
    if args.command == "apply":
        if remote_state and remote_state["action"] == "create" and not args.allow_remote:
            raise github.GitHubError("Remote creation requires --allow-remote; run plan to review it")
        result = engine.apply(manifest, root)
        if remote and not result.get("conflicts"):
            result["github"] = github.apply(remote, root, allow_remote=args.allow_remote)
            result["changed"] = result["changed"] or bool(result["github"].get("created") or result["github"].get("origin_added"))
    elif args.command == "plan":
        result = engine.plan(manifest, root)
        if remote_state:
            result["github"] = remote_state
            result["changed"] = result["changed"] or remote_state["action"] != "noop"
    else:
        result = engine.verify(manifest, root)
        if remote_state:
            result["github"] = remote_state
            result["ok"] = result["ok"] and remote_state["action"] == "noop"
    emit(result)
    if result.get("conflicts") or result.get("ok") is False:
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cac", description="CodexasCode: declare, reconcile, verify, ship")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init", help="Create a generic agent workspace and local Git repository")
    init_parser.add_argument("--root", required=True)
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--json", action="store_true", help="JSON is the default output")
    def initialize(args):
        from .bootstrap import init
        result = init(args.root, args.name)
        emit(result)
        return 1 if result.get("conflicts") else 0
    init_parser.set_defaults(func=initialize)
    for command in ("plan", "apply", "verify"):
        p = sub.add_parser(command)
        p.add_argument("--root", default=".")
        p.add_argument("--manifest", help="Defaults to ROOT/cac.json")
        p.add_argument("--json", action="store_true", help="JSON is the default output")
        if command == "apply":
            p.add_argument("--allow-remote", action="store_true", help="Authorize creation of the declared GitHub repository")
        p.set_defaults(func=reconcile)
    doctor = sub.add_parser("doctor", help="Report local tool availability without changing configuration")
    doctor.add_argument("--json", action="store_true")
    def diagnose(args):
        result = {"version": __version__, "python": sys.version.split()[0], "git": bool(shutil.which("git")), "github_cli": bool(shutil.which("gh")), "codex": bool(shutil.which("codex"))}
        emit(result)
        return 0 if result["git"] else 1
    doctor.set_defaults(func=diagnose)
    from . import lifecycle, gauntlet
    lifecycle.register_subcommands(sub)
    gauntlet.register_subcommands(sub)
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (ValueError, OSError) as exc:
        # Errors are controlled messages; never echo manifest values or subprocess stderr.
        print(f"cac: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
