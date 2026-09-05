# Owner-selected content checks

The workspace owner chooses its purpose, content and authorized destinations. Personal project information and private infrastructure settings are valid workspace content. Generated instructions are editable defaults. The public toolkit's own publication boundary does not become a universal restriction on its users.

`cac-policy.json` persists the local checking profile:

```json
{"schema_version": 1, "profile": "workspace"}
```

New workspaces select `workspace`. This toolkit's public repository explicitly selects `public`. Existing installations without a policy file retain the previous public checking behavior until their owner chooses a profile. If managed by the manifest, edit the policy file's desired content in `cac.json`, then apply and verify.

| Check | workspace | public |
| --- | --- | --- |
| Personal machine paths and private network addresses | Allowed | Reported for publication review |
| Ordinary binary documents | Allowed; content reported as not scanned | Rejected by the text-only publication checker |
| Absolute local links in Markdown | External target reported as not checked; never opened | Rejected as outside the repository |
| Credential-like text | Reported without echoing matched values | Reported without echoing matched values |
| Malformed JSON/TOML, unsafe links and lifecycle evidence | Checked | Checked |

`cac gauntlet --profile public` selects publication checks for that invocation. `--profile workspace` selects workspace checks. Overrides do not bypass invalid persisted policy. No profile is inferred from the remote visibility; a declaration of private visibility is not authorization to share information.

The scanner cannot prove arbitrary data is safe to publish and does not inspect binary document contents. Choose appropriate document and secret-handling tools for the actual project. Use services with the authorization and scope established by the owner, and preserve the intended audience when publishing.
