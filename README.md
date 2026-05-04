# Build And Release MCP Server

A small stdio MCP server for build, release, and GitHub pull request
operations. It uses standard local CLIs such as `gh`, `git`, `kubectl`, and
`docker`, so it has no third-party Python runtime dependencies.

## What It Does

The server gives an MCP client build and release tools across CI diagnostics,
release readiness, deployment inspection, GitHub Actions hardening, dependency
review, Kubernetes status, feature flags, database migrations, observability,
release notes, CODEOWNERS, docs search, ticket extraction, and PR review.

## Server Boundary

This is intentionally one build and release server, with PR review as one tool
group. That boundary makes sense while the tools share the same repository,
GitHub, CI, release, and deployment context.

Split this into multiple MCP servers if a tool group needs different
permissions, write access, separate hosting, or a different operational owner.
Good future split points would be Kubernetes operations, observability, or
project management integrations.

PR review is one tool group:

- `pr_overview`: PR metadata, body, review state, checks, branches, and counts.
- `pr_files`: changed files with additions and deletions.
- `pr_diff`: full PR diff, truncated to a configurable byte limit.
- `pr_review_threads`: review threads, defaulting to unresolved inline comments.

Prompts:

- `review_pr`: guides a model through a bug-focused PR review.
- `release_readiness`: guides a model through a build and release readiness
  review.

The model still performs the review. This server only supplies structured PR
context through narrow tools.

## Requirements

- Python 3.11+
- GitHub CLI (`gh`)
- Authenticated `gh` session:

```sh
gh auth login -h github.com
gh auth status
```

## Run Locally

From this directory:

```sh
python3 -m build_release_mcp
```

By default, commands run in the current working directory. If your MCP client
starts servers from another directory, set `BUILD_RELEASE_MCP_REPO_ROOT`:

```sh
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/your/repo python3 -m build_release_mcp
```

## MCP Client Config

Use an absolute path to this checkout:

```json
{
  "mcpServers": {
    "build-release": {
      "command": "python3",
      "args": ["-m", "build_release_mcp"],
      "cwd": "/path/to/build-release-mcp-server",
      "env": {
        "BUILD_RELEASE_MCP_REPO_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

Some clients do not support `cwd`; in that case point directly at the module:

```json
{
  "mcpServers": {
    "build-release": {
      "command": "python3",
      "args": ["/path/to/build-release-mcp-server/build_release_mcp/server.py"],
      "env": {
        "BUILD_RELEASE_MCP_REPO_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

## Test A GitHub PR

You do not need a GitHub Actions workflow for local PR review.

1. Clone the repository that contains the PR.
2. Authenticate GitHub CLI:

```sh
gh auth login -h github.com
```

3. Configure your MCP client to run this server and set
   `BUILD_RELEASE_MCP_REPO_ROOT` to the cloned repository.
4. Ask your MCP client something like:

```text
Use the review_pr prompt for https://github.com/OWNER/REPO/pull/123.
Focus on correctness bugs and missing tests.
```

The MCP client will call this server for PR metadata, changed files, diffs, and
review threads. The model then uses that context to produce review findings.

## Automation Options

There are three practical ways to use this with a team.

### Team-Local Use

Each developer installs this MCP server in their own MCP-capable client and
reviews PRs on demand.

This is the simplest mode:

- No GitHub Actions workflow is needed.
- No shared AI secrets are needed in CI.
- The server uses the developer's local `gh` authentication.
- The model can combine PR context with local repo context from the developer's
  checkout.

Use this when you want a review assistant that developers run manually before
or during human review.

### GitHub Actions Bot

A GitHub Actions workflow can run on PR events, invoke an AI review runner, and
post the result back to the PR.

In this mode the flow is:

```text
pull_request event
  -> GitHub Actions job
  -> review runner script
  -> this MCP server fetches PR context
  -> model reviews the context
  -> runner posts a PR comment or review
```

The workflow needs:

- `contents: read` permission to read repository contents.
- `pull-requests: write` or `issues: write` permission to post review output.
- A scoped model API key, stored as a GitHub Actions secret.
- A runner script that can talk to MCP, call a model, and post results.

Example workflow shape:

```yaml
name: AI PR Review

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run AI PR review
        env:
          GH_TOKEN: ${{ github.token }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENAI_MODEL: ${{ vars.OPENAI_MODEL || 'gpt-5' }}
          BUILD_RELEASE_MCP_REPO_ROOT: ${{ github.workspace }}
        run: |
          python3 -m build_release_mcp.review_runner \
            "${{ github.event.pull_request.html_url }}" \
            --post-comment
```

This repository includes that workflow at
`.github/workflows/ai-pr-review.yml` and the runner at
`build_release_mcp/review_runner.py`.

To enable it in a repository:

1. Add an `OPENAI_API_KEY` repository secret.
2. Optionally add an `OPENAI_MODEL` repository variable. It defaults to
   `gpt-5`.
3. Make sure GitHub Actions is enabled for the repository.

Use this when you want consistent automated review coverage on every PR. Keep
the bot's feedback scoped to correctness, security, tests, and regressions so
it does not create noisy style comments.

Security note: be careful with forked PRs. Do not run untrusted PR code with
secrets. Prefer reading diffs and metadata only, or design a sandbox
deliberately. Avoid `pull_request_target` unless you understand the security
tradeoffs. The included workflow runs only for non-draft PRs from the same
repository, so it does not expose model API secrets to forked PRs.

### Hosted Service

A hosted service or GitHub App can run the review process centrally for many
repositories.

This is the most operationally mature option:

- Teams install a GitHub App instead of copying workflow files everywhere.
- Permissions can be managed centrally.
- Review policy, prompts, model selection, and logging can be standardized.
- Usage and cost controls can be enforced in one place.
- The service can coordinate multiple MCP servers, not just this PR-review one.

Use this when you want organization-wide automation, auditability, and a single
place to manage upgrades.

## Expanding Beyond PR Review

This server now includes a generated build and release tool catalog. The tools
are read-only and use standard local CLIs or local repository scans:

- `gh` for GitHub PRs, checks, workflows, deployments, and release notes.
- `git` for comparisons, changed files, tags, and ticket refs.
- `kubectl` for Kubernetes deployment, pod, event, image, and rollout status.
- `docker` for local image inspection and manifest reads.
- `PROMETHEUS_BASE_URL` for Prometheus instant queries.
- Local file scans for workflows, dependency manifests, lockfiles, migration
  files, feature flags, CODEOWNERS, and docs.

Detailed docs:

- [Tool Groups](docs/tool-groups/README.md)
- [PR Review](docs/tool-groups/pr-review.md)
- [CI Diagnostics](docs/tool-groups/ci-diagnostics.md)
- [Release Readiness](docs/tool-groups/release-readiness.md)
- [Deployment Status](docs/tool-groups/deployment-status.md)
- [GitHub Actions Hardening](docs/tool-groups/github-actions.md)
- [Dependency And Supply Chain](docs/tool-groups/dependencies.md)
- [Kubernetes Release Support](docs/tool-groups/kubernetes.md)
- [Feature Flags](docs/tool-groups/feature-flags.md)
- [Database Migrations](docs/tool-groups/database.md)
- [Observability](docs/tool-groups/observability.md)
- [Release Notes And Ownership](docs/tool-groups/release-notes-ownership.md)

These tools are meant as a starting point. For production use, replace or
extend the CLI-backed implementations with your team's source of truth for
deployment state, feature flags, observability, vulnerability scanning, and
project management.

## Tool Examples

If the MCP client supports direct tool calls, use:

```json
{
  "pr": "https://github.com/OWNER/REPO/pull/123"
}
```

or:

```json
{
  "repo": "OWNER/REPO",
  "pr": 123
}
```

## Review Runner

The review runner calls the MCP server, sends the collected PR context to the
OpenAI Responses API, and prints a Markdown review.

Run locally:

```sh
OPENAI_API_KEY=... \
OPENAI_MODEL=gpt-5 \
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/repo \
python3 -m build_release_mcp.review_runner https://github.com/OWNER/REPO/pull/123
```

Post the result as a PR comment:

```sh
OPENAI_API_KEY=... \
GH_TOKEN=... \
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/repo \
python3 -m build_release_mcp.review_runner https://github.com/OWNER/REPO/pull/123 --post-comment
```

Environment variables:

- `OPENAI_API_KEY`: required.
- `OPENAI_MODEL`: optional, defaults to `gpt-5`.
- `OPENAI_BASE_URL`: optional, defaults to `https://api.openai.com/v1`.
- `BUILD_RELEASE_MCP_REPO_ROOT`: repository checkout used by `gh`, `git`, and
  local scans.
- `PR_REVIEW_MCP_REPO_ROOT`: deprecated compatibility alias for
  `BUILD_RELEASE_MCP_REPO_ROOT`.
- `AI_REVIEW_MAX_DIFF_BYTES`: optional diff limit, defaults to `180000`.
- `AI_REVIEW_MAX_OUTPUT_TOKENS`: optional model output limit, defaults to
  `1800`.

## Smoke Test

This verifies the server protocol without calling GitHub:

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"prompts/list","params":{}}' \
  | python3 -m build_release_mcp
```

## Notes

- The server does not expose arbitrary shell execution.
- `repo` is optional when the server is started inside a git checkout with a
  GitHub `origin` remote.
- Large diffs are truncated by default to keep model context manageable.
- The old `pr_review_mcp` module name and `pr-review-mcp` console scripts are
  still available as compatibility aliases.
