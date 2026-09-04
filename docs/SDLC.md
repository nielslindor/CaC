# Software development lifecycle

CaC combines an iterative SDLC with secure development practices throughout the lifecycle. NIST explains that security practices must be integrated into whichever lifecycle model a team uses; its SSDF groups practices into preparation, protection, secure production and vulnerability response. This repository maps concrete controls to those groups without claiming certification. [NIST SP 800-218](https://csrc.nist.gov/pubs/sp/800/218/final)

| Phase | Required artifact or action | Acceptance boundary |
| --- | --- | --- |
| Discover and define | intent.md: outcome, audience, constraints, non-goals | Observable success is specified. |
| Specify | spec.md and structured acceptance criteria | Interfaces, risks and failure behavior are testable. |
| Plan and design | plan.md: ownership, dependencies, test and rollback plan | Planned gate passes before substantive implementation. |
| Implement | Small reviewable commits; bounded work packages | Named files have a clear writer; unrelated work is preserved. |
| Verify | Test results, actual behavior, source digest and independent review | Verified gate passes with no unresolved blocking findings. |
| Release | release.md, release reference and recovery/operations evidence | Released gate passes against the source being shipped; CI and publication readback are checked. |
| Operate and retire | Target health observations, incident corrections and reviewed retirement | Real operation is distinguished from successful installation. |

## Evidence schema

`cac change new ID --title "Outcome"` creates editable records. The draft schema is `change.json` with `schema_version`, `id`, `title`, `stage`, `files`, and an `evidence` object. Its fields are `acceptance_criteria`, `verification`, `independent_review`, `release_reference`, `rollback_operations`, `unresolved_blocking_findings`, and `source_tree_digest`.

Write concrete evidence, not a status assertion. Each verification item should identify the test or observation, result and relevant target. Each independent review should identify the role or reviewer, scope, findings and disposition. The digest is SHA-256 over source paths and contents, excluding change receipts and generated/runtime metadata. Explicit verified and released checks compare it with the current source. Historical receipts are structurally checked by the gauntlet without pretending they verify today's tree.

Use `cac change check ID --stage planned`, then verified, then released. These checks do not advance state automatically: after the check passes, the primary updates the declared stage and workboard. Draft records are visible unfinished work. Templates and empty/placeholder evidence cannot pass completion gates. A record is authored evidence, not a signed attestation; the primary and reviewers must inspect the real result.

## SSDF practice mapping

| SSDF group | CaC implementation |
| --- | --- |
| Prepare the Organization | AGENTS entry point, workflow, explicit role ownership, acceptance criteria and tooling prerequisites. |
| Protect the Software | Version control, least-privilege CI, immutable action references, public/private separation and release checksums. |
| Produce Well-Secured Software | Input validation, safe reconciliation, regression tests, independent review, privacy scan and packaged installation smoke test. |
| Respond to Vulnerabilities | SECURITY.md, incident-to-change loop, bounded gauntlet, supported-version policy and recovery guidance. |

The declarative definition, idempotent reconciliation and Git-based collaboration follow the established IaC model described by [IBM](https://www.ibm.com/think/topics/infrastructure-as-code). Codex project roles follow the current [official subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents). Role discovery still depends on the installed host and trusted-project configuration.
