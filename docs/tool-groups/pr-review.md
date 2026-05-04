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

## Prompt

`review_pr` tells the model to:

1. Read PR metadata and status.
2. Inspect changed files.
3. Read unresolved review threads.
4. Read the diff.
5. Produce severity-ordered findings focused on bugs and missing tests.

Example user request:

```text
Use the review_pr prompt for https://github.com/OWNER/REPO/pull/123.
Focus on correctness bugs, rollout risk, and missing tests.
```
