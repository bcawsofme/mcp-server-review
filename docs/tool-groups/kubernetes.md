# Kubernetes Release Support Tools

Use these tools to inspect Kubernetes state during release preparation,
deployment verification, or incident triage.

## Prerequisites

- `kubectl` installed.
- Current kube context points at the intended cluster.

## Tools

### `k8s_get_deployments`

Reads deployments as JSON.

Example:

```json
{
  "namespace": "production"
}
```

### `k8s_get_pods`

Reads pods, optionally filtered by label selector.

Example:

```json
{
  "namespace": "production",
  "selector": "app=my-service"
}
```

### `k8s_get_events`

Reads Kubernetes events sorted by timestamp.

Example:

```json
{
  "namespace": "production"
}
```

### `k8s_rollout_status`

Reads rollout status for a deployment. This is read-only; it does not restart or
modify the deployment.

Example:

```json
{
  "namespace": "production",
  "deployment": "my-service"
}
```

## Example Prompt

```text
Use Kubernetes tools to check whether my-service rolled out cleanly in
production. Summarize pod readiness, recent warning events, and rollout status.
```
