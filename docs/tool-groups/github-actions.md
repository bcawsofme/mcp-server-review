# GitHub Actions Hardening Tools

Use these tools to inspect workflow configuration and flag common release
engineering risks.

## Prerequisites

- `gh` authenticated for `actions_list_workflows`.
- Local repository checkout for file scan tools.

## Tools

### `actions_list_workflows`

Lists GitHub Actions workflows and their state.

Example:

```json
{
  "repo": "OWNER/REPO"
}
```

### `actions_get_workflow_permissions`

Extracts `permissions` blocks from local workflow files.

Example:

```json
{}
```

### `actions_detect_unpinned_actions`

Finds `uses:` references that are not pinned to full commit SHAs.

Example:

```json
{}
```

## Example Prompt

```text
Use GitHub Actions hardening tools to review workflow permissions and unpinned
actions. Focus on supply-chain and token-permission risk.
```
