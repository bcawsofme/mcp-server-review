# Deployment Status Tools

Use these tools to understand what is currently deployed and how it compares to
the desired ref.

## Prerequisites

- `kubectl` configured for Kubernetes-backed tools.
- `gh` authenticated for GitHub deployment history.
- `git` available for ref comparison.

## Tools

### `deploy_get_environment_versions`

Reads Kubernetes deployments and returns container images.

Example:

```json
{
  "namespace": "production",
  "selector": "app.kubernetes.io/part-of=product"
}
```

### `deploy_get_current_image_tags`

Reads running pod images and returns unique image references.

Example:

```json
{
  "namespace": "staging"
}
```

### `deploy_get_recent_deployments`

Reads recent GitHub deployments.

Example:

```json
{
  "repo": "OWNER/REPO",
  "environment": "production",
  "limit": 20
}
```

### `deploy_compare_deployed_vs_main`

Compares a deployed ref to a target ref and lists changed files.

Example:

```json
{
  "deployed_ref": "abc1234",
  "target_ref": "origin/main"
}
```

## Example Prompt

```text
Use deployment status tools to compare what is deployed in staging with
origin/main. Summarize commits and changed files that have not reached staging.
```
