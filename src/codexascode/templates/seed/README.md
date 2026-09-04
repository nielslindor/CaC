# {{name}}

A workspace managed with [CodexasCode](https://github.com/nielslindor/CaC), initialized with toolkit {{version}}.

Start an agent here and say: "Read AGENTS.md and WORKBOARD.md. Use the SDLC and multiple agents for my next outcome."

`cac plan` previews desired changes. `cac apply` reconciles managed configuration. `cac verify` checks actual state. `cac gauntlet` checks repository hygiene and lifecycle records. `cac change new first-change --title "My first outcome"` starts a substantive change.

`cac.json` is the source of truth for managed configuration. Edit its file contents before applying updates. README, WORKBOARD and records under docs/changes are initial seed files and may be edited normally. Local `.cac/` holds disposable ownership hashes; it is never committed. Back up ordinary work with Git commits and an appropriate remote.

Git was initialized locally. Creating a remote does not automatically publish files. Set `spec.github` in cac.json to an object with `repository` (OWNER/NAME) and explicit `visibility` (private or public), review `cac plan`, then run `cac apply --allow-remote` to create it and attach origin. Review what will be committed before pushing.

Open this directory in Codex or VS Code. Trust project instructions only after reviewing them. The configured agent roles inherit your model and permissions; they run only when the host actually dispatches them. Check OPERATIONS.md for recovery.
