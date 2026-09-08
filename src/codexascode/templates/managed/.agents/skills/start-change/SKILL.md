---
name: start-change
description: Create or resume linked SDLC records before a substantive project change.
---

Read `WORKBOARD.md`, the user's latest intent and relevant project policy. Reuse an existing change for the same outcome. Otherwise run `cac change new ID --title "Observable outcome"` in the repository, using a short lowercase hyphenated ID. Fill intent, specification and plan with actual decisions and acceptance tests. Update `change.json` according to its schema, then run `cac change check ID --stage planned` before implementation.

Give workers explicit disjoint ownership. After implementation, record real test and independent review evidence against the source digest reported by `cac change check`. Run the verified gate, then record release, rollback and operations evidence before the released gate. Pending placeholders cannot pass. The primary owns the workboard and final acceptance.

CaC treats Plan → Design → Build → Test → Deploy → Maintain as a loop. When the fleet scaffold is enabled, use the artifact map in `docs/SDLC.md`; each stage reads the previous evidence and records its outcome. Preserve the user's accepted intent and authorization; do not invent extra approvals from generic playbooks. Scope the process to the change rather than adding ceremony to unrelated tasks.

For a fleet rollout, select this change in `fleet.json.sdlc.change_id`, record the gauntlet in `docs/changes/<id>/gauntlet.json`, and run `cac sdlc --root .` after the verified gate. Updating the source invalidates earlier evidence digests: rerun affected checks and refresh the selected record honestly. Runtime incidents under the host's fleet state `incidents/` are inputs to new changes, not approved fixes. Keep host-local evidence private unless explicitly promoted.
