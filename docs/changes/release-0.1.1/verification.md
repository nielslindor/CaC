# Verification

39 regression tests passed. The 0.1.1 wheel installed in a separate temporary runtime, generated a workspace, committed and cloned it, observed the missing empty directory, reconciled and verified the clone, then completed a second unchanged apply with a clean Git worktree. An independent read-only reviewer checked the workflow authority boundary and actual clone proof and found no blocker. Hosted PR/release checks and the real instance readback complete delivery.

GitHub dependency scanning identified the build-only setuptools exclusion advisory GHSA-h35f-9h28-mq5c. The build pin was updated from 82.0.0 to patched 84.0.0; release CI rebuilds with this backend before publication.
