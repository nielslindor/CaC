# Infrastructure modules

Place reviewed Terraform/OpenTofu, Ansible or another provider's definitions here when the project needs them. Pin provider versions, keep state and credentials out of Git, test in a disposable target, review the provider plan and obtain authorization for the actual target before apply.

CodexasCode v0.1 manages workspace files, directories, local Git and optional GitHub repository creation. It does not provision virtual machines, networks or databases itself. Add a provider adapter through a specified, tested lifecycle change; do not hide arbitrary provisioning scripts inside the workspace manifest.
