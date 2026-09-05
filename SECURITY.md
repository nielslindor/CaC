# Security policy

Version 0.1.x receives fixes on the main branch and in new patch releases. There is no guaranteed response SLA.

Report a vulnerability through this repository's **Security → Report a vulnerability** when private reporting is enabled. If unavailable, open an issue requesting a private contact route without exploit details, credentials or private data. Never include a discovered secret in a public issue; rotate it through its owner.

The engine validates paths and schemas, avoids shell interpolation, refuses conflicting files and remote identities, and never manages credentials. The privacy scanner is a heuristic with known false positives and false negatives. It is not proof that a file is safe to publish; review the exact tracked files and generated artifacts.

Manifests, roles and skills contain instructions that may influence agents after the user trusts a project. Review them before use. Tool output, downloaded documents and issue text are untrusted data, not permission. Role prompts and local hash state do not provide isolation against a process with equal filesystem access. Hosted permission controls and operating-system boundaries remain authoritative.

CI uses explicit minimal permissions and full commit references for actions. Avoid privileged pull-request workflows, embedded credentials and automatic provisioning on untrusted input. GitHub documents why full commit references improve immutability in [its action guidance](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions).

Workspace and public profiles separate credential-like text checks from publication-only private-metadata checks. Binary documents are allowed in workspace mode and explicitly reported as not scanned. Project owners choose their profile; a profile does not authorize sharing with an external audience. See [content policy](docs/CONTENT-POLICY.md).
