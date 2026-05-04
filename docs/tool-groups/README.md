# Tool Groups

The server exposes PR review tools plus a build and release operations catalog.
The model performs the reasoning; these tools provide structured context.

## Quick Selection

Use this table to choose a group.

| Need | Start With |
| --- | --- |
| Review a GitHub pull request | [PR Review](pr-review.md) |
| Understand why CI failed | [CI Diagnostics](ci-diagnostics.md) |
| Decide whether a release is safe | [Release Readiness](release-readiness.md) |
| Check what is deployed | [Deployment Status](deployment-status.md) |
| Harden GitHub Actions workflows | [GitHub Actions Hardening](github-actions.md) |
| Inspect dependency and image risk | [Dependency And Supply Chain](dependencies.md) |
| Inspect Kubernetes rollout state | [Kubernetes Release Support](kubernetes.md) |
| Check feature flag references | [Feature Flags](feature-flags.md) |
| Review migration risk | [Database Migrations](database.md) |
| Check metrics or warning events | [Observability](observability.md) |
| Draft release notes or find owners | [Release Notes And Ownership](release-notes-ownership.md) |

## Common Inputs

Many tools accept these optional arguments:

- `repo`: GitHub repository as `owner/name`. If omitted, `gh` uses the current
  checkout.
- `base`: Git base ref for comparisons, often `origin/main` or a release tag.
- `namespace`: Kubernetes namespace.
- `limit`: Maximum number of GitHub records to read.

## Runtime Assumptions

- `BUILD_RELEASE_MCP_REPO_ROOT` points to the repository being inspected.
- `gh` is installed and authenticated for GitHub-backed tools.
- `kubectl` is installed and configured for Kubernetes-backed tools.
- `docker` is installed for image inspection tools.
- `PROMETHEUS_BASE_URL` is set for Prometheus-backed tools unless `base_url`
  is passed directly.

## Safety Model

The catalog is intentionally read-only. It can inspect PRs, workflows, commits,
Kubernetes objects, Docker image metadata, files, and metrics. It does not
trigger deployments, restart workloads, mutate tickets, or change repository
settings.
