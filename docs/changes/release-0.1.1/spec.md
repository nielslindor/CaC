# Specification

Generated CI must reconstruct local declared state with cac apply before cac verify. It must preserve explicit GitHub identity checks and omit remote-creation authorization. A packaged test must cross a real Git clone boundary, then verify reconstructed state and idempotency.

The package build backend must include the fix for GHSA-h35f-9h28-mq5c; use the currently available patched 84.0.0 pin and verify packaging in CI.
