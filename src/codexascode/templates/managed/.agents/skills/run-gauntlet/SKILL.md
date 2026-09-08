---
name: run-gauntlet
description: Challenge an uncertain solution with falsification, deterministic checks and independent review.
---

State the question, hypotheses and observable acceptance criterion in the current change record. Record sources and classify evidence as observed, source-reported or inferred. Select the cheapest discriminating test before asking additional models.

Run `cac gauntlet --root .`; add `--tests` when a Python unittest suite exists. The command uses the owner-selected profile in `cac-policy.json`; use `--profile public` when a public publication check is intended. Personal content is allowed by the workspace profile. This is the deterministic leg only. Ask the investigator to find a falsifier and the reviewer to challenge actual implementation and evidence. Add a security auditor for relevant trust-boundary changes. Reviewers stay read-only. Give any repair worker exclusive ownership.

Repair one supported cause, repeat affected tests, reconcile review findings, and have the primary run the actual acceptance path. At most three repair rounds per hypothesis. On exhaustion, record eliminated explanations, residual risk and a concrete changed hypothesis or blocker. Never convert missing evidence into a pass.

For native fleet deployment, also maintain `docs/changes/<id>/gauntlet.json`: schema_version 1, hypotheses with id, question, attempts (test, evidence, result), and resolution. Results are pass, fail or inconclusive. A resolved hypothesis requires its final attempt to pass; the deployment gate rejects blocked or inconclusive outcomes. Keep at most three attempts under one hypothesis; preserve exhausted evidence and open a genuinely different hypothesis when new evidence changes the explanation. Never rename the same hypothesis merely to reset the limit.

Use `cac sdlc --root .` to check the selected change and current source digest. The schema proves record consistency, not truth or independent judgment. Independent review and actual receiving-host observation remain distinct evidence. A recurring incident must produce a regression case or a documented reason a deterministic check is unsuitable; changed checks need review so a repair cannot pass by weakening its own test.

A disproved cause may remain with resolution `eliminated`, a final failing falsifier and a nonempty `conclusion` explaining the counterevidence. Eliminated causes do not count as success: at least one resolved passing outcome is required, and blocked/inconclusive hypotheses still prevent rollout.
