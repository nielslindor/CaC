# Specification

Generated CI must reconstruct local declared state with cac apply before cac verify. It must preserve explicit GitHub identity checks and omit remote-creation authorization. A packaged test must cross a real Git clone boundary, then verify reconstructed state and idempotency.
