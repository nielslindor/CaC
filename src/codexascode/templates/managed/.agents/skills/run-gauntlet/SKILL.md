---
name: run-gauntlet
description: Challenge an uncertain solution with falsification, deterministic checks and independent review.
---

State the question, hypotheses and observable acceptance criterion in the current change record. Record sources and classify evidence as observed, source-reported or inferred. Select the cheapest discriminating test before asking additional models.

Run `cac gauntlet --root .`; add `--tests` when a Python unittest suite exists. This is the deterministic leg only. Ask the investigator to find a falsifier and the reviewer to challenge actual implementation and evidence. Add a security auditor for relevant trust-boundary changes. Reviewers stay read-only. Give any repair worker exclusive ownership.

Repair one supported cause, repeat affected tests, reconcile review findings, and have the primary run the actual acceptance path. At most three repair rounds per hypothesis. On exhaustion, record eliminated explanations, residual risk and a concrete changed hypothesis or blocker. Never convert missing evidence into a pass.
