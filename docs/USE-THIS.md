# Agent bootstrap contract

Use this repository as a toolkit to create a **separate destination workspace**. The toolkit checkout maintains the product; the instance contains the user's project state. Do not turn the public toolkit into the user's private workspace.

1. Read the current request, repository README and relevant AGENTS.md. Determine the target directory and project name from available context. Ask only for missing scope that changes destination or publishing visibility. Default to a local Git repository when remote intent is absent.
2. Verify Python 3.11+ and Git. Install this pinned release into a virtual environment or with pipx. Do not change global agent configuration, models, credentials or permission policies. A normal install from an inspected source checkout is preferable to piping a downloaded script into a shell.
3. Run `cac init --root TARGET --name PROJECT`. It creates a manifest, managed configuration, editable seed documents and a Git repository. Existing conflicting files cause a refusal. It never force-overwrites.
4. Run `cac plan --root TARGET`, `cac verify --root TARGET`, and `cac gauntlet --root TARGET --json`. A repeated `cac apply --root TARGET` must return no changes. Verify `.git` and the actual generated files. Open the destination with the chosen editor or agent host.
5. If remote creation is authorized, add `spec.github` to the manifest with `repository` and explicit `visibility`, inspect the plan, then run `cac apply --allow-remote`. Reconcile existing origin and visibility conflicts explicitly. This creates the remote and attaches origin; commit and push only the reviewed in-scope content with appropriate user authorization.
6. Start the actual requested outcome using the destination's SDLC. Assign useful independent lanes to its native roles, wait for results, reconcile findings, and run the closest real acceptance path. If roles are configured but no agent has run, say configured. If the host cannot spawn agents, say so and use a separate human reviewer; do not fabricate collaboration.

For a substantive failure, use the gauntlet: hypothesis, falsifier, decisive observation, bounded repair, regression check, independent review, integrated acceptance. Preserve the current outcome through interruptions in the existing workboard and change record. Do not create parallel task systems.

Report the destination, repository identity and visibility, actual verification result, remaining limitation and next concrete action. No secrets or personal context belong in the public toolkit, release notes or upstream issues.
