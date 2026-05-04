# Feature Flag Tools

Use these tools to find feature flag references and compare environment-style
configuration files.

## Prerequisites

- Local repository checkout.

## Tools

### `flags_scan_repo`

Scans code and config files for likely feature flag references, including
`AVANTI_FEATURE_*` style environment keys.

Example:

```json
{}
```

### `flags_compare_env_files`

Compares keys in two env-style files.

Example:

```json
{
  "left": ".env.staging",
  "right": ".env.production"
}
```

## Example Prompt

```text
Use feature flag tools to find flags touched by this release. Call out flags
that may need environment configuration before rollout.
```
