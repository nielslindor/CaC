---
name: start-change
description: Create or resume linked SDLC records before a substantive project change.
---

Read `WORKBOARD.md`, the user's latest intent and relevant project policy. Reuse an existing change for the same outcome. Otherwise run `cac change new ID --title "Observable outcome"` in the repository, using a short lowercase hyphenated ID. Fill intent, specification and plan with actual decisions and acceptance tests. Update `change.json` according to its schema, then run `cac change check ID --stage planned` before implementation.

Give workers explicit disjoint ownership. After implementation, record real test and independent review evidence against the source digest reported by `cac change check`. Run the verified gate, then record release, rollback and operations evidence before the released gate. Pending placeholders cannot pass. The primary owns the workboard and final acceptance.
