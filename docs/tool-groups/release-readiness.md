# Release Readiness Tools

Use these tools before cutting a release or promoting a build. They focus on
changed files, migrations, dependency changes, labels, CI state, and release
risk categories.

## Prerequisites

- `git` available in the repository checkout.
- `gh` installed and authenticated for GitHub-backed checks.

## Tools

### `release_prs_since_last_release`

Collects merged PRs. If `base` is omitted, the latest local git tag is used as
the conceptual release base.

Example:

```json
{
  "repo": "OWNER/REPO",
  "base": "v1.2.3",
  "limit": 100
}
```

### `release_check_required_labels`

Checks open PRs for required labels.

Example:

```json
{
  "required_labels": ["release-notes", "qa-reviewed"]
}
```

### `release_check_ci_status`

Reads GitHub check runs for a git ref.

Example:

```json
{
  "ref": "HEAD"
}
```

### `release_check_migrations`

Lists migration-like files changed since a base ref.

Example:

```json
{
  "base": "origin/main"
}
```

### `release_generate_risk_summary`

Categorizes changed files into risk buckets such as database, CI, dependencies,
infra, and security.

Example:

```json
{
  "base": "origin/main"
}
```

## Prompt

`release_readiness` tells the model to run the release checks in a practical
order and classify blockers versus follow-up recommendations.

Example:

```text
Use the release_readiness prompt with base origin/main.
Call out migration, dependency, CI, feature flag, and rollback risks.
```
