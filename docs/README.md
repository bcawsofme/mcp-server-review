# Documentation

This directory breaks the MCP server down by operating area. Start with
`tool-groups/README.md` when deciding which tools to use.

## Guides

- [Tool Groups](tool-groups/README.md)
- [PR Review](tool-groups/pr-review.md)
- [CI Diagnostics](tool-groups/ci-diagnostics.md)
- [Release Readiness](tool-groups/release-readiness.md)
- [Deployment Status](tool-groups/deployment-status.md)
- [GitHub Actions Hardening](tool-groups/github-actions.md)
- [Dependency And Supply Chain](tool-groups/dependencies.md)
- [Kubernetes Release Support](tool-groups/kubernetes.md)
- [Feature Flags](tool-groups/feature-flags.md)
- [Database Migrations](tool-groups/database.md)
- [Observability](tool-groups/observability.md)
- [Release Notes And Ownership](tool-groups/release-notes-ownership.md)

## Design Principles

- Tools are narrow and typed.
- Tools are read-only by default.
- Tools use standard local CLIs where possible.
- Environment-specific integrations should be added behind explicit tool
  schemas instead of exposing generic shell access.
- Tool results should be compact enough for model context.
