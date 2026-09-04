# Providers and infrastructure scope

| Provider | v0.1 behavior | Deliberate limits |
| --- | --- | --- |
| Filesystem | Create directories and managed text files; update unchanged managed files; inspect drift. | No deletion, force overwrite, executable shell resources or symlink traversal. |
| Git | Initialize a local repository with a declared initial branch; verify repository identity. | No implicit commits, pushes, branch replacement or destructive rollback. |
| GitHub | Inspect declared owner/name and visibility; explicitly create and attach origin; read back identity and visibility. | No visibility changes, credentials, organization administration or automatic uploads. |
| Other Git hosts | Use the created Git repository and configure a reviewed remote through normal Git tooling. | No first-party remote provisioning adapter yet. |
| Cloud and configuration tools | Store provider definitions under infra/ and apply the same lifecycle and agent review. | No native VM, network or database provisioning in this release. |

For an OpenTofu/Terraform or Ansible adapter, first create an SDLC change with an exact target, cost and credential boundary, state backend, provider version policy, read-only plan, apply authorization, post-apply readback, rollback strategy and disposable integration test. Keep remote state and secrets out of the public repository. Credentials stay with the provider's normal authentication mechanism.

The separation is intentional: CaC's first shipped unit is the reproducible agent workspace that can safely develop and operate such modules. Adding a provider must produce real tested resource behavior before documentation lists it as supported.
