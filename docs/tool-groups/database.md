# Database Migration Tools

Use these tools to inspect migration files and flag potentially destructive SQL.

## Prerequisites

- Local repository checkout.

## Tools

### `db_list_migration_files`

Lists migration-like files in the repository.

Example:

```json
{}
```

### `db_detect_destructive_migrations`

Scans SQL files for destructive statements such as `DROP TABLE`,
`DROP COLUMN`, `TRUNCATE TABLE`, and broad `DELETE FROM` statements.

Example:

```json
{}
```

### `db_changed_migrations`

Lists changed migration files since a base ref.

Example:

```json
{
  "base": "origin/main"
}
```

## Example Prompt

```text
Use database migration tools to review migration risk for this branch.
Separate destructive schema risk from routine additive migrations.
```
