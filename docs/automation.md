# Automation

There are four practical ways to use this project with a team.

## Team-Local Use

Each developer installs this MCP server in their MCP-capable client and reviews
PRs on demand.

Use this when you want a review assistant that developers run manually before
or during human review.

Benefits:

- No GitHub Actions workflow is needed.
- No shared AI secrets are needed in CI.
- The server uses the developer's local `gh` authentication.
- The model can combine PR context with local repo context from the developer's
  checkout.

## GitHub Actions Bot

A GitHub Actions workflow can run on PR events, invoke the review runner, and
post the result back to the PR.

Flow:

```text
pull_request event
  -> GitHub Actions job
  -> review runner script
  -> this MCP server fetches PR context
  -> model reviews the context
  -> runner posts a PR comment
```

The workflow needs:

- `contents: read` permission to read repository contents.
- `pull-requests: write` or `issues: write` permission to post review output.
- A scoped model API key stored as a GitHub Actions secret.
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
`build_release_mcp/review_runner.py`. The included workflow checks out trusted
agent code separately from the PR workspace before running the model call.

To enable it in a repository:

1. Add an `OPENAI_API_KEY` repository secret.
2. Optionally add an `OPENAI_MODEL` repository variable. It defaults to
   `gpt-5`.
3. Make sure GitHub Actions is enabled for the repository.

Security note: be careful with forked PRs. Do not run untrusted PR code with
secrets. Prefer reading diffs and metadata only, or design a sandbox
deliberately. Avoid `pull_request_target` unless you understand the security
tradeoffs. The included workflow runs only for non-draft PRs from the same
repository, so it does not expose model API secrets to forked PRs.

## Manual Minor Fixes Bot

For implementation, use the included manual workflow at
`.github/workflows/ai-minor-fixes.yml`.

This workflow is intentionally `workflow_dispatch` only. It checks out the PR
branch, asks the model for a minimal patch, validates the patch with
`git apply --check`, commits it as `Apply AI minor fixes`, pushes it to the PR
branch, and posts a status comment.

To run it:

1. Open GitHub Actions.
2. Choose `AI Minor Fixes`.
3. Enter the PR number and optional instructions.
4. Run the workflow.

Use this for small, low-risk fixes only. The runner refuses to start with a
dirty worktree and only applies a model response that is a valid unified diff.
It is not designed for broad refactors or untrusted fork PRs.

## Hosted Service

A hosted service or GitHub App can run the review process centrally for many
repositories.

Use this when you want organization-wide automation, auditability, and a single
place to manage upgrades.

Benefits:

- Teams install a GitHub App instead of copying workflow files everywhere.
- Permissions can be managed centrally.
- Review policy, prompts, model selection, and logging can be standardized.
- Usage and cost controls can be enforced in one place.
- The service can coordinate multiple MCP servers, not just this PR-review one.

This repository includes a hosted webhook service implementation. See
[Hosted Service](hosted-service.md).

The hosted service includes GitHub App token support, SQLite-backed job state,
webhook idempotency, repository-level config, update-in-place PR comments,
finding reconciliation, and opt-in minor fixes.
