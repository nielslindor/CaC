"""Build a self-contained desired state from packaged, generic templates."""

import json
import re
from importlib.resources import files
from pathlib import Path

from . import __version__
from .engine import EngineError, apply, load_manifest, plan


def _assets(folder):
    base = files("codexascode").joinpath("templates", folder)
    def walk(node, prefix=""):
        for item in sorted(node.iterdir(), key=lambda item: item.name):
            relative = prefix + item.name
            if item.is_dir():
                yield from walk(item, relative + "/")
            else:
                yield relative, item.read_text(encoding="utf-8")
    return dict(walk(base))


def init(root, name):
    root = Path(root).absolute()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", name):
        raise EngineError("Name must be 1-64 letters, digits, dots, underscores or hyphens")
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise EngineError("Initialization refuses symlinked destinations")
    manifest_path = root / "cac.json"
    seeds = {path: content.replace("{{name}}", name).replace("{{version}}", __version__) for path, content in _assets("seed").items()}
    def validate_seed_paths():
        for relative in seeds:
            target = root / relative
            if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
                raise EngineError("Seed path must not traverse a symlink")
            if target.exists() and not target.is_file():
                raise EngineError(f"Seed path is not a regular file: {relative}")
            for parent in target.parents:
                if parent.exists() and not parent.is_dir():
                    raise EngineError(f"Seed parent is not a directory: {relative}")
    def finish_seeds():
        validate_seed_paths()
        for relative, content in seeds.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with target.open("x", encoding="utf-8") as stream:
                    stream.write(content)
    if manifest_path.is_symlink():
        raise EngineError("Manifest must not be a symlink")
    if manifest_path.exists():
        manifest = load_manifest(manifest_path)
        if manifest["metadata"]["name"] != name:
            raise EngineError("Destination already has a different workspace name")
        validate_seed_paths()
        result = apply(manifest, root)
        if not result.get("conflicts"):
            finish_seeds()
        result["initialized"] = False
        return result
    managed = _assets("managed")
    def render(content):
        return content.replace("{{name}}", name).replace("{{version}}", __version__)
    manifest = {"apiVersion": "cac/v1", "kind": "Workspace", "metadata": {"name": name}, "spec": {
        "git": {"enabled": True, "defaultBranch": "main"},
        "directories": ["docs/changes", "areas", "infra"],
        "files": [{"path": path, "content": render(content)} for path, content in managed.items()],
    }}
    preview = plan(manifest, root)
    if preview["conflicts"]:
        raise EngineError("Initialization conflicts with existing managed files; inspect with plan")
    validate_seed_paths()
    for relative, content in seeds.items():
        target = root / relative
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
            raise EngineError("Seed path must not traverse a symlink")
        if target.exists() and target.read_text(encoding="utf-8") != content:
            raise EngineError(f"Initialization would overwrite an existing seed: {relative}")
    root.mkdir(parents=True, exist_ok=True)
    # Exclusive creation makes competing bootstrap attempts fail before replacing state.
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    result = apply(manifest, root)
    if not result.get("conflicts"):
        finish_seeds()
    result["initialized"] = True
    result["workspace"] = name
    return result
