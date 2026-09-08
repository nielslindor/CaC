# Native CaC SDLC

The operating model follows [Anthropic’s AI-native SDLC playbook](https://claude.com/blog/the-ai-native-sdlc-playbook). The adopted ideas are an artifact-driven loop, institutional guidance in versioned skills, deterministic enforcement behind guidance, independent feedback, and operational findings returning as new intent. The following is CaC's implementation contract, not a copy of Claude-specific settings.

## Stage and evidence ownership

| Stage | CaC input and output | Acceptance responsibility |
| --- | --- | --- |
| Plan | User request or incident → intent.md | Primary preserves user outcome, constraints and existing authorization |
| Design | intent.md → spec.md | Contracts, risks and observable acceptance criteria |
| Build | spec.md → plan.md → isolated code/worktree | Named ownership, implementation order, affected tests and rollback |
| Test | Changed behavior → verification.md and gauntlet.json | Decisive checks, independent review, preserved failure evidence |
| Deploy | Selected verified change → native receipt | Source-bound gate before managed writes; actual target readback |
| Maintain | Observed failure → local incident intent → next change | Triage and scoped repair; regression evidence returns to Test |

`WORKBOARD.md` owns project outcomes. Git change records own implementation evidence. Coordination owns current leases and job results. Native host receipts own deployment observations. These records link to each other; none substitutes for another. Full chat and native memory remain host-local.

## Executable gate

Set `fleet.json.sdlc.change_id` to the change being deployed. Complete the toolkit planned and verified gates. Run `cac sdlc --root .` using the interpreter with the pinned toolkit installed. The selected change must be verified or released, its recorded digest must match current source, and the structured gauntlet must have a resolved passing outcome with no blocked hypotheses. Disproved causes may be retained as eliminated with a final failed falsifier and an explanatory conclusion. Existing lifecycle checks require verification and independent-review evidence. The gate runs in CI and the installed controller before native resource writes.

Example gauntlet record shape:

```json
{
  "schema_version": 1,
  "hypotheses": [{
    "id": "receiving-host",
    "question": "Does the target load the committed configuration?",
    "attempts": [{"test": "native readback", "evidence": "verification.md: receiving-host observation", "result": "pass"}],
    "resolution": "resolved"
  }]
}
```

Records must describe actual observations. Strings and schema validation cannot authenticate a reviewer or prove usefulness. Earlier failing evidence stays in history; an exhausted hypothesis requires a documented new explanation, not a renamed retry. Changes to tests and acceptance criteria receive independent review.

## Operation and limits

The installed controller writes a deduplicated local incident under its state directory when reconciliation blocks. The incident contains an intent and bounded host/revision/error metadata. Repetition updates occurrence evidence without overwriting triage edits. Agents inspect it when beginning operational work, promote an authorized fix into `docs/changes/`, and carry it through the same gates. No arbitrary model is invoked and no incident approves its own repair.

This is a repository-owned gate, not tamper-proof enterprise governance. The owner can change the policy or code. CI branch protection, external approval systems, model behavior evals and wider fleet availability must be observed separately. Historical changes keep historical digests; only the explicitly selected deployment change is required to match current source. Controller upgrades are explicit; older controllers do not acquire this gate merely from a source push.
