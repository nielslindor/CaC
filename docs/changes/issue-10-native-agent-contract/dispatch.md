# Issue #10 — native custom-agent validation

Canonical outcome: https://github.com/nielslindor/CaC/issues/10

The owner selected implementation of the existing issue. This initial branch file is a dispatch record, not a completed implementation or passing test claim.

## Outcome and owned files
Make supported custom-agent configurations pass and malformed or unsupported fields fail with useful diagnostics. One worker owns the narrow validator change in src/codexascode/gauntlet.py, relevant fixtures/tests, and directly required managed-source parity changes. Other fleet, release, publication-security and dependency work stays outside this branch.

## Required source checks
Read AGENTS.md, WORKBOARD.md, AGENT-WORKFLOW.md, the start-change skill and the issue. Verify the declared native compatibility baseline and current official OpenAI agent/configuration documentation before choosing the schema. Separate upstream validity from optional owner policy. Reproduce against the actual branch code before modifying it.

## Acceptance
Cover supported model, reasoning, MCP and skill settings with positive fixtures; invalid sandbox enums, types, nested values and unsupported keys with negative fixtures. Keep generated model inheritance and owner settings intact. Do not accept arbitrary unknown fields. Run focused regressions, python tools/check.py and a clean installed-wheel check. Report any native probe or independent-review gap separately.

## Boundaries and return
Public toolkit content only: no private-instance source, personal/workplace data, credentials, model-provider changes, live host modifications, deployment or release. Follow the existing SDLC; no new orchestration framework. Push implementation and actual test evidence to this branch, not main. Do not force-push, merge, close issues or spawn recursive workers. Return exact source revision, diff, commands/results and remaining verification in this PR.
