# Documentation

This directory breaks the MCP server down by setup path, automation mode, agent
architecture, and tool group.

## Setup And Operation

- [Quickstart](quickstart.md)
- [Automation](automation.md)
- [Hosted Service](hosted-service.md)

## PR Review Agent

- [PR Review Agent Architecture](pr-review-agent.md)
- [PR Review Tools](tool-groups/pr-review.md)

## Tool Catalog

- [Tool Groups](tool-groups/README.md)
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
