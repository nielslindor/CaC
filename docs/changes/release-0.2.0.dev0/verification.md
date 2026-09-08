# Verification

2026-09-08: all99 product regressions pass again. A freshly built wheel passes tools/smoke.py from an independent environment: bootstrap, repeated no-op apply, edited-file refusal, false lifecycle completion refusal and fresh-clone reconciliation. Prior productisation evidence records actual Linux native saved-plan deployment, indexed context and packaged worker execution.

Independent read-only release reviewer found no concrete blocker: version/tag consistency, prerelease shell handling, reusable CI gates and honest macOS coverage all confirmed. Finished hosted artifacts will be downloaded and tested after the tag workflow succeeds; local build evidence is not substituted for that observation.

Hosted run34195775711 passed both Linux versions and packaged bootstrap, but macOS fixtures failed before their intended assertions because temporary paths traversed the operating system symlink. Canonicalize only fixture roots; runtime symlink rejection is unchanged. Subsequent hosted results determine acceptance.
