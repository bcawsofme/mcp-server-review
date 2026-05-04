# Observability Tools

Use these tools for lightweight post-deploy verification or incident context.

## Prerequisites

- `PROMETHEUS_BASE_URL` set, or pass `base_url` directly, for Prometheus
  queries.
- `kubectl` configured for Kubernetes warning events.

## Tools

### `obs_query_prometheus`

Runs a Prometheus instant query.

Example:

```json
{
  "base_url": "https://prometheus.example.com",
  "query": "sum(rate(http_requests_total[5m]))"
}
```

### `obs_recent_k8s_warnings`

Reads recent Kubernetes warning events.

Example:

```json
{
  "namespace": "production"
}
```

## Example Prompt

```text
Use observability tools to check post-deploy health for production.
Summarize recent warning events and any error-rate signals available.
```
