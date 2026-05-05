# Build And Release MCP Server

A build and release MCP server focused on powering a stateful AI PR review bot.

The main workflow collects GitHub PR context, runs an AI review, tracks
findings across commits, updates PR comments, and can optionally apply small
safe fixes. MCP is the tool boundary between the agent and GitHub/repository
operations.

The server also exposes supporting build and release tools through local CLIs
such as `gh`, `git`, `kubectl`, and `docker`, so it has no third-party Python
runtime dependencies.

## What It Does

The server gives MCP clients typed tools for:

- PR review context and controlled PR write operations.
- CI diagnostics and GitHub Actions hardening.
- Release readiness, release notes, ownership, and ticket extraction.
- Deployment, Kubernetes, image, observability, feature flag, dependency, and
  database migration checks.

PR review is the most developed workflow. It can collect PR context, run an AI
review, normalize findings, persist finding state, reconcile findings across
new PR commits, update a PR comment, and run opt-in minor fixes.

## Start Here

- [Quickstart](docs/quickstart.md): local setup, MCP client config, smoke tests,
  and unit tests.
- [Tool Groups](docs/tool-groups/README.md): all available MCP tool groups.
- [PR Review Tools](docs/tool-groups/pr-review.md): PR context, write tools,
  prompt behavior, and minor-fix runner.
- [Automation](docs/automation.md): team-local use, GitHub Actions, manual
  minor fixes, and hosted service options.
- [PR Review Agent Architecture](docs/pr-review-agent.md): implementation
  boundaries, state tracking, MCP tool boundary, and remaining roadmap.
- [Hosted Service](docs/hosted-service.md): GitHub App/webhook service,
  deployment settings, and repository config.

## Server Boundary

This is intentionally one build and release MCP server. PR review is one tool
group inside it because the tools share repository, GitHub, CI, release, and
deployment context.

Split this into multiple MCP servers when a tool group needs different
permissions, separate hosting, write access, or a different operational owner.
Good future split points are Kubernetes operations, observability, and project
management integrations.

MCP is the agent tool boundary: narrow tools expose repository, PR, CI,
ownership, and write operations to the agent without making the model
responsible for service control flow or persistence.

## Common Commands

Run the MCP server:

```sh
python3 -m build_release_mcp
```

Run a local PR review:

```sh
OPENAI_API_KEY=... \
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/repo \
python3 -m build_release_mcp.review_runner https://github.com/OWNER/REPO/pull/123
```

Run tests:

```sh
python3 -m unittest discover -s tests
```

## Notes

- The server does not expose arbitrary shell execution.
- `repo` is optional when the server starts inside a git checkout with a GitHub
  `origin` remote.
- Tool implementations are a starting point. For production use, connect them
  to your team's source of truth for deployment state, observability,
  vulnerability scanning, and project management.
