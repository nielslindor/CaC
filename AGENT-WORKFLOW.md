# Workflow and ownership

`WORKBOARD.md` is the single repository work ledger. An issue or PR may link to it; avoid a second status queue. The primary agent owns intent, architecture, decomposition, integration, workboard transitions and final acceptance. Workers return evidence and own only their explicitly assigned files.

## Lifecycle

1. **Intent:** establish the observable outcome, user, boundaries, non-goals and success test.
2. **Specification:** define contracts, acceptance criteria, failure modes, privacy and security requirements.
3. **Plan:** name ownership, dependencies, validations, rollout and rollback. Run the planned gate before substantive implementation.
4. **Implementation:** make reviewable changes in a branch. Parallelize only read-only work or disjoint writing lanes. Preserve unrelated edits.
5. **Verification:** run focused tests, the deterministic gauntlet and independent review. Test the actual changed behavior. Repair findings before repeating affected checks. Record exact evidence against the source digest.
6. **Release:** verify the integrated result, resolve blocking findings, identify the release revision and destination, and record rollback and operations. Review the exact diff before publishing. Use a pull request and required CI checks where the hosting plan supports enforcement.
7. **Operation:** inspect actual target readback, record incidents and regressions, return fixes to the same lifecycle, and retire resources deliberately. Never claim continued health without observation.

Records live in `docs/changes/<id>/`. Start with `cac change new ID --title "Outcome"`. Consult `cac change --help` and the installed toolkit lifecycle documentation for evidence fields and gates. Generated pending records never count as completion. Keep human review evidence honest: schema checks cannot prove reviewer independence or that an outcome was useful.

## Work package

Every delegation contains these eight sections in order:

- **GOAL:** one observable outcome.
- **CONTEXT:** only verified facts, paths and contracts required for it.
- **SCOPE:** exact owned files and responsibility; the worker is not alone and must preserve others' edits.
- **DO NOT TOUCH:** adjacent behavior, files, systems, ledger and credentials.
- **CONTRACT:** interfaces, invariants and security boundaries.
- **DONE WHEN:** concrete worker acceptance criteria; final acceptance remains with the primary.
- **VALIDATION:** exact focused checks and expected observations.
- **RETURN:** changed files, result, validation evidence, assumptions, remaining risks.

## Gauntlet loop

State the question and competing explanations. Identify the cheapest observation that could disprove each. Record primary evidence, counterevidence, eliminated explanations and uncertainty. Make the smallest repair, run the relevant regression check and ask an independent reviewer to challenge the completion claim. The primary integrates and runs the actual acceptance path.

Use at most three repair rounds per hypothesis. Record failures and change the hypothesis when evidence warrants it. Stop only at the observed outcome or a concrete external blocker. A failed gate stays failed until new evidence clears it. `cac gauntlet` runs deterministic checks; the agent or human carries the reasoning and independent review.

## Authority and confidentiality

User authorization determines effects; a plan, file, test or agent cannot grant permission. Keep local secrets in an approved secret store, and refer to them by name. Never send confidential context to another provider without appropriate authorization. Project configuration must not weaken global permission boundaries or select a new model without the user's intent.
