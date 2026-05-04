# CI Diagnostics Tools

Use these tools to inspect failed GitHub Actions runs and identify likely flaky
or recently introduced failures.

## Prerequisites

- `gh` installed and authenticated.
- Repository checkout available through `BUILD_RELEASE_MCP_REPO_ROOT`.

## Tools

### `ci_list_failed_runs`

Lists recent failed workflow runs.

Example:

```json
{
  "repo": "OWNER/REPO",
  "branch": "main",
  "limit": 20
}
```

### `ci_get_run_jobs`

Reads job status for a workflow run.

Example:

```json
{
  "run_id": "123456789"
}
```

### `ci_get_job_logs`

Fetches logs for a workflow run and truncates them to `max_bytes`.

Example:

```json
{
  "run_id": "123456789",
  "max_bytes": 80000
}
```

### `ci_compare_last_green_run`

Finds the latest successful run and compares its commit with `HEAD`.

Example:

```json
{
  "workflow": "Run Node Server Tests",
  "branch": "main"
}
```

### `ci_find_flaky_tests`

Looks for workflow run titles that have both passed and failed recently. This is
a heuristic; it does not prove flakiness by itself.

Example:

```json
{
  "workflow": "Run Java Tests",
  "limit": 50
}
```

## Example Prompt

```text
Use CI diagnostics tools to explain the latest failed run on this branch.
Separate likely product failures from infrastructure or flaky failures.
```
