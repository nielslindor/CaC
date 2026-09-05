# Operations and recovery

- Run `cac verify` after applying configuration and after moving or cloning the workspace. A fresh clone has no local ownership state; byte-identical managed files can be adopted with `cac apply`.
- For local drift, inspect the file and manifest. Preserve valuable edits in a Git branch, then deliberately update the manifest to the intended content or restore the file. There is no force-overwrite or destructive cleanup mode.
- To roll back managed configuration, restore a reviewed earlier version of `cac.json` in Git, inspect `cac plan`, apply and verify. Removed definitions are not deleted automatically; retire files with a separately reviewed change.
- An interrupted apply can leave partial changes. Inspect the next plan and rerun only after resolving the cause. Do not claim the operation was transactional. The lock is held by the operating system; its file may remain after normal use. Never remove it while a writer might hold it.
- Keep tokens outside Git. Use GitHub CLI authentication or an approved credential provider. Private repository visibility does not make committed credentials safe.
- Review change and incident evidence regularly. Dependency and provider upgrades require the same lifecycle as code changes. CI is validation; it does not deploy infrastructure or operate an always-on agent.

- Content policy belongs to the owner. Configure `cac-policy.json` or use `cac gauntlet --profile public` for a public publication check. Ordinary personal configuration, private addresses and a directory named `private/` are permitted in workspace mode; binary contents are not inspected by the text scanner.
