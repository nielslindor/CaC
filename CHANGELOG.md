# Changelog

## 0.1.2

- Separate owner-selected workspace content checks from public publication checks.
- Permit personal paths, private network configuration and binary documents in workspace mode; retain credential-like text and integrity checks.
- Remove the generic personal-data ban, unqualified provider-sharing prohibition and blanket private-directory exclusion from generated workspaces.
- Persist profile selection in cac-policy.json; report binary contents as not scanned.

## 0.1.1

- Reconcile declared local state before verifying a generated workspace in CI, restoring empty directories omitted by Git clones.
- Exercise a real Git clone in the installed-package acceptance test, including successful reconciliation, verification and an unchanged second apply.
- Preserve the explicit boundary against remote creation in generated CI.
- Pin a patched build backend to address GHSA-h35f-9h28-mq5c, affecting source archive exclusions on macOS.

## 0.1.0

- Declarative workspace manifest with conflict-aware filesystem reconciliation, ownership hashes and local writer locking.
- Local Git initialization and explicit optional GitHub repository creation with identity and visibility readback.
- Packaged workspace instructions, native agent roles, workflow skills, editor tasks and CI.
- SDLC record creation, evidence gates, source digests and deterministic gauntlet checks.
- Independent review process, regression tests, clean package bootstrap validation and release artifacts.
