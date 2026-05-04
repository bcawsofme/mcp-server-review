# Dependency And Supply Chain Tools

Use these tools to inspect dependency manifests, lockfiles, and image pinning.

## Prerequisites

- Local repository checkout.
- `docker` installed for image inspection tools.

## Tools

### `deps_inspect_lockfile_changes`

Lists changed lockfiles since a base ref.

Example:

```json
{
  "base": "origin/main"
}
```

### `deps_check_changed_manifests`

Lists changed dependency manifests such as `package.json`, `pyproject.toml`,
`pom.xml`, and `build.gradle`.

Example:

```json
{
  "base": "origin/main"
}
```

### `deps_find_unpinned_container_images`

Scans YAML and Docker-related files for image references that are not pinned by
digest.

Example:

```json
{}
```

### `image_inspect`

Runs Docker image inspection for a local image.

Example:

```json
{
  "image": "nginx:1.27"
}
```

### `image_get_digest`

Reads a Docker image manifest.

Example:

```json
{
  "image": "nginx:1.27"
}
```

## Example Prompt

```text
Use dependency and supply-chain tools to review this release branch.
Highlight changed lockfiles, unpinned images, and dependency manifest risk.
```
