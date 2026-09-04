# Changelog

## 0.1.1

- Reconcile declared local state before verifying a generated workspace in CI, restoring empty directories omitted by Git clones.
- Exercise a real Git clone in the installed-package acceptance test, including successful reconciliation, verification and an unchanged second apply.
- Preserve the explicit boundary against remote creation in generated CI.

## 0.1.0

- Declarative workspace manifest with conflict-aware filesystem reconciliation, ownership hashes and local writer locking.
- Local Git initialization and explicit optional GitHub repository creation with identity and visibility readback.
- Packaged workspace instructions, native agent roles, workflow skills, editor tasks and CI.
- SDLC record creation, evidence gates, source digests and deterministic gauntlet checks.
- Independent review process, regression tests, clean package bootstrap validation and release artifacts.
