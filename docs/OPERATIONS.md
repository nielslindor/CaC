# Toolkit and instance operations

After installation, run `cac doctor`. It reports Python and tool availability without reading credentials. After initialization or apply, run plan and verify; zero changes plus matching state is the normal steady state. A fresh clone may adopt matching files with apply because ownership state is intentionally local.

For an upgrade, preserve the current manifest and project work in Git. Review new template and behavior changes in a branch, update the desired manifest, inspect the plan, apply, and verify. Existing instances do not silently pull newer templates or mutate themselves. Seed documents remain owned by the user.

For conflicting edits, compare the desired manifest with the actual file and current Git diff. Preserve valuable local work before deliberately reconciling it. There is no force overwrite. Restoring an earlier reviewed manifest gives a configuration rollback; restore associated application code separately through Git. Removed resources need an explicit retirement change.

The engine uses an OS-held POSIX lock. A lock filename can remain on disk after normal execution; its existence does not prove a writer is active. Do not remove a lock file while another process might hold it, because that can create two lock identities. Interrupted I/O is not transactional: inspect the next plan and observed state before retrying. Never erase the ownership cache merely to bypass a conflict.

GitHub creation performs a readback and never changes existing visibility. If a network failure makes the outcome uncertain, inspect the exact repository before retrying. Files are only uploaded by a separate reviewed Git push. Provider credentials belong in the user's credential provider, not a manifest.

To retire an instance, stop its actual external jobs, preserve records and backups, inspect provider-managed resources and use a separately authorized retirement plan. Removing the toolkit does not destroy provisioned resources. This toolkit has no always-running controller.

Release maintainers run `python tools/check.py`, build packages, test the installed wheel, inspect the public diff, and tag a verified version. The release workflow checks the matching `release-VERSION` change record, packages from that source, and uploads checksums. Observe hosted CI and the release's artifact list after publication. A green local build is not hosted release acceptance.
