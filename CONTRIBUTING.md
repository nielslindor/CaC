# Contributing

Read AGENTS.md, AGENT-WORKFLOW.md and WORKBOARD.md. Open an issue for a material feature or provider boundary change. Small fixes still need a clear problem, regression evidence and reviewer context.

Create or reuse a change record, fill intent/specification/plan, then pass the planned gate. Implement the smallest supported change. Use multiple agents for independent investigation, disjoint implementation and review when useful; the primary owns integration and acceptance. No worker changes the workboard or publishes a release.

Run `python tools/check.py` in the installed development environment. For packaging changes, build a wheel and exercise `tools/smoke.py` against an environment installed from that wheel. Add tests for meaningful behavior and failure boundaries, not assertions that mirror static implementation details.

Submit a pull request with the concrete before/after behavior, source change record, exact validation, review findings and material limitations. Never include personal/workplace files, credentials, private infrastructure details or copied proprietary prompts. Contributors certify they have the right to submit their changes under the MIT license.
