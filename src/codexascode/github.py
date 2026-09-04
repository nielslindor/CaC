"""Optional GitHub provider. Create only; never change visibility or push files."""

import json
import re
import shutil
import subprocess


class GitHubError(ValueError):
    pass


def _run(args, *, root=None, missing=False):
    try:
        result = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubError(f"{args[0]} unavailable or timed out") from exc
    if result.returncode:
        if missing and "(HTTP 404)" in result.stderr:
            return None
        raise GitHubError(f"{args[0]} operation failed; check authentication, permissions and network")
    return result.stdout


def validate(config):
    if not isinstance(config, dict) or set(config) != {"repository", "visibility"}:
        raise GitHubError("github requires repository and visibility")
    repository = config["repository"]
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise GitHubError("repository must be OWNER/NAME")
    if config["visibility"] not in ("private", "public"):
        raise GitHubError("visibility must be explicitly private or public")


def inspect(config):
    validate(config)
    if not shutil.which("gh"):
        raise GitHubError("GitHub CLI is required for the declared GitHub resource")
    output = _run(["gh", "api", "repos/" + config["repository"]], missing=True)
    if output is None:
        return {"action": "create", "repository": config["repository"], "visibility": config["visibility"]}
    actual = json.loads(output)
    if not isinstance(actual, dict) or not isinstance(actual.get("full_name"), str) or type(actual.get("private")) is not bool or not isinstance(actual.get("html_url"), str):
        raise GitHubError("GitHub returned an invalid repository response")
    if actual.get("full_name", "").lower() != config["repository"].lower():
        raise GitHubError("GitHub returned a different repository; refusing redirect")
    visibility = "private" if actual.get("private") else "public"
    if visibility != config["visibility"]:
        raise GitHubError("Existing repository visibility differs; no visibility change was made")
    if actual.get("archived"):
        raise GitHubError("Declared repository is archived")
    return {"action": "noop", "repository": actual["full_name"], "visibility": visibility, "url": actual["html_url"]}


def check_origin(config, root):
    """Read-only preflight; an absent origin is safe to add."""
    validate(config)
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise GitHubError("Workspace path must not traverse a symlink")
    git_dir = root / ".git"
    if git_dir.is_symlink() or (git_dir.exists() and not git_dir.is_dir()):
        raise GitHubError("Workspace .git must be a real directory")
    if not git_dir.exists():
        return
    output = _run(["git", "remote"], root=root)
    if "origin" not in output.splitlines():
        return
    actual = _run(["git", "remote", "get-url", "origin"], root=root).strip()
    repo = config["repository"].lower()
    allowed = {f"https://github.com/{repo}", f"https://github.com/{repo}.git", f"git@github.com:{repo}.git"}
    if actual.lower() not in allowed:
        raise GitHubError("Existing origin points elsewhere; no remote was changed")


def apply(config, root, *, allow_remote=False):
    check_origin(config, root)
    if not (root / ".git").is_dir():
        raise GitHubError("Initialize the local Git repository before remote apply")
    result = inspect(config)
    if result["action"] == "create":
        if not allow_remote:
            raise GitHubError("Creating the declared GitHub repository requires --allow-remote")
        _run(["gh", "repo", "create", config["repository"], "--" + config["visibility"]])
        result = inspect(config)
        if result["action"] != "noop":
            raise GitHubError("Repository creation could not be verified; inspect before retrying")
        result["created"] = True
    remotes = _run(["git", "remote"], root=root).splitlines()
    if "origin" not in remotes:
        _run(["git", "remote", "add", "origin", "https://github.com/" + config["repository"] + ".git"], root=root)
        result["origin_added"] = True
    check_origin(config, root)
    return result
