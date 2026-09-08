# Verification

Observed 2026-09-08: 99 regression tests pass. Twelve installed command checks outside the checkout pass: provider command discovery, fleet bootstrap, repeat workspace apply, verification, and refusal of the draft fleet lifecycle. Two wheel builds with SOURCE_DATE_EPOCH=315532800 are identical. The installed preview planned and applied a real enrolled host without managed changes; native configuration and skills readback returned native_verified. Doctor reported healthy, with no drift, and explicitly limited its claim to this host.

Independent read-only review found no concrete trust-boundary blocker after the manifest race repair. A proposed process-spawn failure was eliminated by inspecting the try boundary and a regression test; actual notification-write failure cleanup was added. Saved-plan tests use a real Git remote, changed source, ownership and environment preconditions; invalidation happens before native writes.

Real macOS receiving-host observation and public release are unfulfilled release gates. Fixture tests cover repeat Linux/macOS service installation; they cannot substitute for a second host. Fresh-task proof belongs to the earlier native SDLC rollout and is not inferred from this preview receipt.
