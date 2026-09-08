# Product contract

CodexasCode packages workspace management and native Codex deployment in one installed CLI. Workspace files and native deployment resources have different lifecycles; commands make the target explicit.

| User outcome | Command |
| --- | --- |
| Create a workspace with native fleet artifacts | `cac init --root ./workspace --name example --fleet` |
| Manage local workspace files | `cac plan`, `cac apply`, `cac verify` |
| Inspect local tools or deployed host | `cac doctor`, `cac doctor --fleet` |
| Start/check a change | `cac change new`, `cac change check` |
| Check hygiene and native SDLC evidence | `cac gauntlet`, `cac sdlc --root .` |
| Enroll this machine | `cac fleet join --remote URL --branch BRANCH --host HOST --project-root PATH` |
| Review/save exact native deployment | `cac fleet plan --out ./reviewed-plan.json` |
| Apply that saved plan | `cac fleet apply --plan ./reviewed-plan.json` |
| Continuously follow the enrolled branch | `cac fleet install-service` |
| Inspect known hosts and ownership | `cac fleet fleet-status` |
| Run isolated leased work | `cac work --project PATH --scope SCOPE --task ID --agent NAME -- COMMAND` |
| Enqueue or inspect named host work | `cac jobs enqueue JOB TASK`, `cac jobs list` |
| Retrieve bounded documentation/local memory | `cac context --state-dir PATH search QUERY` |

Provider state defaults to `~/.local/state/cac-fleet`; pass `--state` before provider subcommands to select another installation. Context indexes deliberately require their own explicit state path. Fleet scaffold creates a draft `fleet-bootstrap` change: no host is activated until its evidence is complete and enrollment is explicit. The generated Codex compatibility prefix is a reviewed baseline, not a promise that future versions are compatible.

Saved plans contain revisions, file paths and hashes, never file contents or environment values. They are bound to this enrollment and its current ownership state. Source, ownership or observed file changes invalidate them. Creating another plan replaces the local seal; regenerate after any conflict. Saved apply shares the same SDLC, compatibility, environment and native checks as continuous reconciliation. An applied plan is not a reusable authorization token.

Source rollback uses a reviewed Git revert with valid source-bound lifecycle evidence; native resources reconcile from that commit. Existing worktrees and generations are retained. There is no destructive automatic garbage collection. A stopped or unreachable host cannot receive a change until its controller resumes. macOS service commands are covered by fixtures, but real macOS acceptance must be recorded by a receiving host.

The package contains generic runtime code and templates only. Authentication and secret-manager provisioning remain host responsibilities. Configured jobs execute as the enrolled user and should be bounded; leases coordinate cooperating processes, not arbitrary editors. Package upgrades are explicit installations and require service restart. Normal reconciliation and diagnostics use no model calls; agent judgment remains a bounded, separately evidenced activity.

Public release acceptance requires clean installed-wheel tests, independent review, rollback evidence and receiving-host coverage. A locally built development wheel is a preview, not a published stable release.
