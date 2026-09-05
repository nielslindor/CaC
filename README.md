# CodexasCode · CaC

**Declare an agent workspace. Reproduce it. Develop and ship through a verifiable lifecycle.**

CodexasCode applies Infrastructure as Code principles to the environment where agents build software: project instructions, agent roles, workflow skills, editor tasks, repository configuration and delivery checks. Its small Python engine turns a JSON definition into a real Git workspace, detects drift and refuses to overwrite unrelated work.

Version 0.1 provides a working workspace and repository provider. It gives infrastructure modules the same SDLC, review and evidence boundaries; cloud resource provisioning belongs to purpose-built tools such as OpenTofu or Ansible. See [provider boundaries](docs/PROVIDERS.md).

## Tell your agent: “Use this”

> Use https://github.com/nielslindor/CaC at release v0.1.2. Read its AGENTS.md and docs/USE-THIS.md. Initialize a separate workspace for my project, inspect the plan, apply and verify it. Use its SDLC and multiple agents with disjoint ownership. Keep my private context out of the toolkit. Create at least a local Git repository; use my chosen host and visibility for a remote.

The agent instructions are [here](docs/USE-THIS.md). They include the actual install and acceptance path.

## Quick start

Requires **Python 3.11+ and Git** on macOS or Linux. GitHub CLI is optional. Native Windows is not supported in v0.1 because the engine uses POSIX file locks; use WSL.

```sh
git clone --branch v0.1.2 https://github.com/nielslindor/CaC.git
cd CaC
python3.11 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/cac doctor
.venv/bin/cac init --root ../my-project --name my-project
.venv/bin/cac plan --root ../my-project
.venv/bin/cac verify --root ../my-project
.venv/bin/cac gauntlet --root ../my-project --json
```

Activate the virtual environment or use its absolute `cac` executable when working in the new project. With pipx, `pipx install 'git+https://github.com/nielslindor/CaC.git@v0.1.2'` exposes `cac` directly. No API key is needed for the engine.

The first initialization creates a local Git repository. It neither commits nor uploads your files. Repeat apply returns no changes. Open the new folder in Codex or VS Code; review and trust project instructions using the host's normal controls. Native agent dispatch requires a capable host and its own authentication. The generated investigator and reviewer roles were exercised with Codex CLI 0.153.3; use a current host compatible with your selected model. The CLI itself makes no language-model calls.

## What is included

| Capability | Delivered behavior |
| --- | --- |
| Declarative desired state | A self-contained `cac.json` describes managed file contents, directories, Git and optional GitHub repository visibility. |
| Plan, apply, verify | Preview without writing; reconcile under a local writer lock; verify actual filesystem and repository state. |
| Idempotency and drift | Unchanged repeated apply preserves file and ownership-state bytes; conflicting local edits stop mutation. |
| Version control | Local Git bootstrap, optional explicit GitHub creation, review templates and CI. Git history holds definition changes and supports reviewed rollback. |
| Complete SDLC | Intent, specification, plan, implementation, verification, release and operation, with machine-checked evidence records. |
| Multiple agents | A primary owner plus implementer, investigator, reviewer and security auditor roles; bounded packages and disjoint writing ownership. |
| Gauntlet | Falsification and independent review workflow, backed by deterministic syntax, privacy, lifecycle and optional test checks. |
| Public/private separation | Generic toolkit, separately generated instances, ignored local ownership state, and no credential copying or global configuration changes. |

## Daily use

```sh
cac change new improve-onboarding --title "A new user can complete setup"
# Fill the generated intent, specification, plan and evidence fields.
cac change check improve-onboarding --stage planned
# Implement, test and independently review through the agent workflow.
cac gauntlet --json
cac change check improve-onboarding --stage verified
```

The check output reports the source digest to record after testing. `docs/changes` is excluded from that digest so evidence can be recorded without changing its subject. A gate validates the record; it does not manufacture observations or prove an agent's independence.

Managed configuration is edited in `cac.json`, then applied. README, WORKBOARD and change records are editable seed content. See [architecture and manifest](docs/ARCHITECTURE.md), [SDLC and evidence](docs/SDLC.md), [operations](docs/OPERATIONS.md), [security](SECURITY.md), and [contributing](CONTRIBUTING.md).

## Develop this toolkit

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python tools/check.py
```

The repository uses its own agent roles, SDLC records and gauntlet. CI checks Python 3.11 and 3.13 on Linux and 3.11 on macOS, builds a wheel, installs it in a clean environment and exercises the packaged bootstrap. Releases attach the wheel, source archive and SHA-256 checksums after these checks.

This is an independent open-source project. It is not an OpenAI product and does not claim NIST certification. MIT licensed.

Workspace owners choose their content policy. New instances select the `workspace` profile in `cac-policy.json`, allowing personal configuration and documents. This public toolkit selects the separate `public` profile for its own publication checks. See [content policy](docs/CONTENT-POLICY.md) for precise checks, overrides and scanner limits.
