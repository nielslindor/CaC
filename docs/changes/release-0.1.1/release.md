# Release

Target: v0.1.1. Preserve v0.1.0 unchanged and publish a separately versioned patch after required PR checks. The generated CI runs local apply without remote-creation authorization, then verifies. Existing instances update the managed workflow content through their manifest, apply and verify. If the patch fails, restore the prior manifest and keep the failed hosted result visible until repaired; do not delete resources or weaken verification.
