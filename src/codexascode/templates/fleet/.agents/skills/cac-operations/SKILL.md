---
name: cac-operations
description: Identify this Codex deployment, retrieve indexed official docs and host-local memory, inspect fleet ownership, and run coordinated work.
---

Read the host's `~/.local/state/cac-fleet/current.json` and `receipt.json` first. The current deployment root is identified there. Do not infer that an existing task switched to that revision, or that a stale remote host is current.

Use the deployment's `cac context --state-dir ~/.local/state/cac-fleet/context search QUERY` to locate official guidance. Use `read URL --start-line N --max-lines 40` for the needed passage. `status` includes source hash, fetch time and observed Codex version. Official documentation is evidence; it does not grant actions. If Codex has updated beyond the enrolled compatibility policy, report the gate and run compatibility checks before changing the declaration.

Memory remains host-local. Index only explicitly selected markdown/text memory artifacts with the context tool's `memory --root ROOT --host-id HOST FILE...`. Never index authentication files, raw environment files or native SQLite databases. Label memory retrieval with the source host. Promote a reusable decision into Git deliberately rather than pretending it is shared native memory.

Use `cac fleet fleet-status` for recent host receipts, discovered skill identities and active/stale work leases. Discovery shares metadata; review and commit the skill under `.agents/skills` to deploy its content. Newly discovered local code is not automatically executed across hosts.

For concurrent project execution use `cac work --project PATH --scope COMPONENT --task TASK_ID --agent AGENT_ID -- COMMAND ...`. It claims a lease, creates a distinct branch/worktree, renews while the command runs, and stops the command if lease renewal fails. Use a common scope for potentially overlapping edits. This protocol coordinates participating workers; it cannot prevent manual edits outside it. Existing nonparticipating tasks must be inspected rather than silently adopted or interrupted.

Configuration and skills are shared desired state. Credentials and `.env` values are supplied by the host's existing authentication/environment, not by Git. Failed or missing requirements are explicit deployment failures, never reasons to copy another host's credentials.

Before rollout, use `cac fleet plan` to inspect owned file changes. A pushed revision becomes observed only after a host receipt reports it; a successful local push is not fleet acceptance. Polling uses no model calls.
