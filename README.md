# PR Review And Release Ops MCP Server

A small stdio MCP server that exposes focused GitHub pull request review tools.
It uses the GitHub CLI (`gh`) instead of a GitHub SDK, so it has no third-party
Python runtime dependencies.

## What It Does

The server gives an MCP client PR review tools:

- `pr_overview`: PR metadata, body, review state, checks, branches, and counts.
- `pr_files`: changed files with additions and deletions.
- `pr_diff`: full PR diff, truncated to a configurable byte limit.
- `pr_review_threads`: review threads, defaulting to unresolved inline comments.

It also includes generated build and release operations tools for CI diagnostics,
release readiness, deployment inspection, workflow hardening, dependency review,
Kubernetes status, feature flags, database migrations, observability, release
notes, CODEOWNERS, docs search, and ticket extraction.

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
python3 -m pr_review_mcp
```

By default, commands run in the current working directory. If your MCP client
starts servers from another directory, set `PR_REVIEW_MCP_REPO_ROOT`:

```sh
PR_REVIEW_MCP_REPO_ROOT=/path/to/your/repo python3 -m pr_review_mcp
```

## MCP Client Config

Use an absolute path to this checkout:

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["-m", "pr_review_mcp"],
      "cwd": "/path/to/pr-review-mcp-server",
      "env": {
        "PR_REVIEW_MCP_REPO_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

Some clients do not support `cwd`; in that case point directly at the module:

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "python3",
      "args": ["/path/to/pr-review-mcp-server/pr_review_mcp/server.py"],
      "env": {
        "PR_REVIEW_MCP_REPO_ROOT": "/path/to/your/repo"
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
   `PR_REVIEW_MCP_REPO_ROOT` to the cloned repository.
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
          PR_REVIEW_MCP_REPO_ROOT: ${{ github.workspace }}
        run: |
          python3 -m pr_review_mcp.review_runner \
            "${{ github.event.pull_request.html_url }}" \
            --post-comment
```

This repository includes that workflow at
`.github/workflows/ai-pr-review.yml` and the runner at
`pr_review_mcp/review_runner.py`.

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

### CI Diagnostics

- `ci_list_failed_runs`
- `ci_get_run_jobs`
- `ci_get_job_logs`
- `ci_compare_last_green_run`
- `ci_find_flaky_tests`

### Release Readiness

- `release_prs_since_last_release`
- `release_check_required_labels`
- `release_check_ci_status`
- `release_check_migrations`
- `release_generate_risk_summary`

### Deployment Status

- `deploy_get_environment_versions`
- `deploy_get_current_image_tags`
- `deploy_get_recent_deployments`
- `deploy_compare_deployed_vs_main`

### GitHub Actions Hardening

- `actions_list_workflows`
- `actions_get_workflow_permissions`
- `actions_detect_unpinned_actions`

### Dependency And Supply Chain

- `deps_inspect_lockfile_changes`
- `deps_check_changed_manifests`
- `deps_find_unpinned_container_images`
- `image_inspect`
- `image_get_digest`

### Kubernetes Release Support

- `k8s_get_deployments`
- `k8s_get_pods`
- `k8s_get_events`
- `k8s_rollout_status`

### Feature Flags

- `flags_scan_repo`
- `flags_compare_env_files`

### Database Migrations

- `db_list_migration_files`
- `db_detect_destructive_migrations`
- `db_changed_migrations`

### Observability

- `obs_query_prometheus`
- `obs_recent_k8s_warnings`

### Release Notes And Ownership

- `release_notes_collect_merged_prs`
- `release_notes_group_by_label`
- `codeowners_for_paths`
- `docs_search`
- `project_extract_ticket_refs`

These tools are meant as a starting point. For production use, replace or extend
the CLI-backed implementations with your team's source of truth for deployment
state, feature flags, observability, vulnerability scanning, and project
management.

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
PR_REVIEW_MCP_REPO_ROOT=/path/to/repo \
python3 -m pr_review_mcp.review_runner https://github.com/OWNER/REPO/pull/123
```

Post the result as a PR comment:

```sh
OPENAI_API_KEY=... \
GH_TOKEN=... \
PR_REVIEW_MCP_REPO_ROOT=/path/to/repo \
python3 -m pr_review_mcp.review_runner https://github.com/OWNER/REPO/pull/123 --post-comment
```

Environment variables:

- `OPENAI_API_KEY`: required.
- `OPENAI_MODEL`: optional, defaults to `gpt-5`.
- `OPENAI_BASE_URL`: optional, defaults to `https://api.openai.com/v1`.
- `PR_REVIEW_MCP_REPO_ROOT`: repository checkout used by `gh`.
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
  | python3 -m pr_review_mcp
```

## Notes

- The server does not expose arbitrary shell execution.
- `repo` is optional when the server is started inside a git checkout with a
  GitHub `origin` remote.
- Large diffs are truncated by default to keep model context manageable.
