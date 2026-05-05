# PR Review Tools

Use these tools when an MCP client needs structured GitHub pull request context.
They are the foundation for the `review_pr` prompt and the GitHub Actions review
runner.

## Prerequisites

- `gh` installed and authenticated.
- `BUILD_RELEASE_MCP_REPO_ROOT` set to a checkout of the repository, or pass
  `repo` as `owner/name`.

## Tools

### `pr_overview`

Fetches PR metadata, body, branches, review state, checks, labels, assignees,
and summary counts.

Example:

```json
{
  "pr": "https://github.com/OWNER/REPO/pull/123"
}
```

### `pr_files`

Lists changed files with additions and deletions.

Example:

```json
{
  "repo": "OWNER/REPO",
  "pr": 123
}
```

### `pr_diff`

Fetches the PR diff and truncates it to `max_bytes`.

Example:

```json
{
  "pr": 123,
  "repo": "OWNER/REPO",
  "max_bytes": 120000
}
```

### `pr_review_threads`

Fetches review threads, defaulting to unresolved inline comments. This helps the
model avoid duplicating existing feedback.

Example:

```json
{
  "pr": 123,
  "repo": "OWNER/REPO",
  "unresolved_only": true
}
```

### `pr_check_runs`

Fetches PR head ref and GitHub check run rollup context.

Example:

```json
{
  "pr": 123,
  "repo": "OWNER/REPO"
}
```

### `pr_test_results`

Fetches PR check-run output summaries for test and CI context.

Example:

```json
{
  "pr": 123,
  "repo": "OWNER/REPO"
}
```

### `pr_codeowners`

Matches changed or provided paths against local CODEOWNERS rules.

Example:

```json
{
  "paths": ["src/app.py", "docs/readme.md"]
}
```

### `pr_file`

Reads a repository file safely, truncated to `max_bytes`.

Example:

```json
{
  "path": "src/app.py",
  "max_bytes": 60000
}
```

## Write Tools

These tools are intended for controlled agent workflows after finding state is
available.

### `create_branch`

Creates a local git branch from a ref.

```json
{
  "branch": "agent/fix-pr-123",
  "from_ref": "HEAD"
}
```

### `commit_file_change`

Writes one repository file and commits the change on the current or requested
branch.

```json
{
  "branch": "agent/fix-pr-123",
  "path": "src/app.py",
  "content": "...",
  "message": "Fix PR review finding"
}
```

### `post_review_comment`

Posts a pull request comment.

```json
{
  "pr": 123,
  "repo": "OWNER/REPO",
  "body": "Review update"
}
```

### `mark_finding_resolved`

Updates a stored finding status to `resolved`, `ignored`, or `open`.

```json
{
  "repo": "OWNER/REPO",
  "pr_number": 123,
  "finding_id": "abc123",
  "status": "resolved"
}
```

## Prompt

`review_pr` tells the model to:

1. Read PR metadata and status.
2. Inspect changed files.
3. Read unresolved review threads.
4. Read check runs and CODEOWNERS matches.
5. Read the diff.
6. Produce structured findings focused on bugs and missing tests.

Example user request:

```text
Use the review_pr prompt for https://github.com/OWNER/REPO/pull/123.
Focus on correctness bugs, rollout risk, and missing tests.
```

## Minor Fix Runner

The `build-release-mcp-fix` CLI can apply small fixes after a PR branch is
checked out:

```sh
build-release-mcp-fix 123 --instructions "Fix the failing test expectation" --post-comment
```

It collects the same PR context as the review runner, asks the model for either
`NO_CHANGES` or a unified diff, validates that diff with `git apply --check`,
commits successful changes, and can push them with `--push`.

Use the manual `AI Minor Fixes` GitHub Actions workflow when you want the bot to
patch a PR branch from GitHub.
