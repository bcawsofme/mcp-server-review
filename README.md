# PR Review MCP Server

A small stdio MCP server that exposes focused GitHub pull request review tools.
It uses the GitHub CLI (`gh`) instead of a GitHub SDK, so it has no third-party
Python runtime dependencies.

## What It Does

The server gives an MCP client these tools:

- `pr_overview`: PR metadata, body, review state, checks, branches, and counts.
- `pr_files`: changed files with additions and deletions.
- `pr_diff`: full PR diff, truncated to a configurable byte limit.
- `pr_review_threads`: review threads, defaulting to unresolved inline comments.

It also exposes a `review_pr` prompt that guides a model through a bug-focused
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
          PR_URL: ${{ github.event.pull_request.html_url }}
        run: |
          python3 scripts/ai_pr_review.py "$PR_URL"
```

Use this when you want consistent automated review coverage on every PR. Keep
the bot's feedback scoped to correctness, security, tests, and regressions so
it does not create noisy style comments.

Security note: be careful with forked PRs. Do not run untrusted PR code with
secrets. Prefer reading diffs and metadata only, or design a sandbox
deliberately. Avoid `pull_request_target` unless you understand the security
tradeoffs.

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

This server is intentionally narrow, but the same pattern works for other MCP
servers. A good MCP server wraps one domain with safe, typed tools instead of
giving the model broad shell access.

Useful MCP server ideas:

- **CI diagnostics**: read failed workflow runs, fetch logs, summarize root
  causes, and suggest fixes.
- **Issue triage**: summarize new issues, detect duplicates, classify severity,
  and suggest owners or labels.
- **Release notes**: collect merged PRs since the last tag and draft customer
  or engineering release notes.
- **Dependency review**: inspect dependency diffs, licenses, known advisories,
  and package manager lockfile changes.
- **Test intelligence**: map changed files to likely tests, detect missing test
  coverage, and recommend targeted commands.
- **Code ownership**: map changed files to CODEOWNERS, teams, Slack channels,
  or internal domain owners.
- **Docs lookup**: expose internal docs, ADRs, runbooks, and API references as
  searchable MCP resources.
- **Deployment context**: read deployment status, environment versions, feature
  flags, and recent incidents.
- **Observability**: query logs, metrics, traces, and dashboards through narrow
  read-only tools.
- **Security review**: scan diffs for secrets, risky auth changes, permission
  changes, and unsafe config.
- **Database review**: inspect migrations, compare schema changes, and flag
  risky locking or backfill patterns.
- **Project management**: connect PRs to tickets, acceptance criteria, release
  trains, and rollout plans.

These can be separate MCP servers or separate tools in a larger internal MCP
bundle. Separate servers are usually easier to permission, test, and reason
about.

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
