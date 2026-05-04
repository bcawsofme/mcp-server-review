# Release Notes And Ownership Tools

Use these tools to draft release notes, find code owners, search docs, and map
commits to project tickets.

## Prerequisites

- `gh` authenticated for GitHub PR search.
- Local repository checkout for CODEOWNERS, docs, and git history tools.

## Tools

### `release_notes_collect_merged_prs`

Collects merged PRs through GitHub search.

Example:

```json
{
  "repo": "OWNER/REPO",
  "search": "is:pr is:merged merged:>=2026-05-01",
  "limit": 100
}
```

### `release_notes_group_by_label`

Groups PR objects by label. This tool expects PR objects from another tool call
or client-provided context.

Example:

```json
{
  "pull_requests": [
    {
      "number": 123,
      "title": "Add health probes",
      "labels": [{ "name": "infra" }]
    }
  ]
}
```

### `codeowners_for_paths`

Finds CODEOWNERS rules that match paths.

Example:

```json
{
  "paths": ["app/server/index.ts", "infra/k8s/deployment.yaml"]
}
```

### `docs_search`

Searches local documentation files.

Example:

```json
{
  "query": "release checklist",
  "limit": 10
}
```

### `project_extract_ticket_refs`

Extracts ticket references from commit subjects since a base ref.

Example:

```json
{
  "base": "origin/main",
  "pattern": "[A-Z]+-\\d+"
}
```

## Example Prompt

```text
Use release notes and ownership tools to draft internal release notes from
merged PRs this week. Group by label and include likely code owners.
```
