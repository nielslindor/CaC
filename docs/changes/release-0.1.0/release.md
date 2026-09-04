# Release

Release target: v0.1.0, with a wheel, source archive and SHA-256 checksums on GitHub. The tagged workflow requires the released evidence gate and full reusable CI before publication. Recover a failed rollout by retaining the last working manifest and source version, reviewing the configuration diff, applying and verifying the intended rollback. Instances never auto-update templates. Provider resources require separate reviewed retirement; deleting the toolkit does not destroy them. Hosted publication is confirmed by release and artifact readback.
