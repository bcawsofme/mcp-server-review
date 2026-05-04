# Hosted Service

The hosted service turns this project into a GitHub webhook receiver. GitHub
sends pull request events to the service, the service verifies the webhook
signature, queues a background review job, runs the existing review runner, and
posts the result back to the PR.

This is the simplest hosted implementation. It uses `GH_TOKEN` for GitHub API
access instead of implementing a full GitHub App installation-token flow.

## Flow

```text
GitHub pull_request webhook
  -> POST /webhooks/github
  -> HMAC signature verification
  -> action/repo/fork/draft filtering
  -> background review job
  -> MCP PR tools collect context
  -> OpenAI Responses API reviews context
  -> gh pr comment posts result
```

## Run

```sh
GITHUB_WEBHOOK_SECRET=... \
GH_TOKEN=... \
OPENAI_API_KEY=... \
HOSTED_SERVICE_ALLOWED_REPOS=OWNER/REPO \
python3 -m build_release_mcp.hosted_service
```

The service listens on `0.0.0.0:8080` by default.

## Endpoints

### `GET /health/live`

Returns `200` when the process is alive.

### `GET /health/ready`

Returns `200` when required environment variables are present.

Required:

- `GITHUB_WEBHOOK_SECRET`
- `OPENAI_API_KEY`
- `GH_TOKEN`

### `POST /webhooks/github`

GitHub webhook endpoint.

Configure the webhook with:

- Payload URL: `https://YOUR_HOST/webhooks/github`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: Pull requests

The service handles these PR actions:

- `opened`
- `synchronize`
- `reopened`
- `ready_for_review`

It ignores draft PRs and fork PRs by default.

### `GET /jobs/<job_id>`

Returns in-memory job status for a queued review.

## Environment Variables

- `GITHUB_WEBHOOK_SECRET`: required webhook HMAC secret.
- `GH_TOKEN`: required token used by `gh` to read PRs and post comments.
- `OPENAI_API_KEY`: required model API key.
- `OPENAI_MODEL`: optional, defaults to `gpt-5`.
- `OPENAI_BASE_URL`: optional, defaults to `https://api.openai.com/v1`.
- `HOSTED_SERVICE_ALLOWED_REPOS`: optional comma-separated allowlist such as
  `owner/repo,owner/other-repo`.
- `HOSTED_SERVICE_ALLOW_FORKS`: optional, defaults to `false`.
- `HOSTED_SERVICE_HOST`: optional, defaults to `0.0.0.0`.
- `HOSTED_SERVICE_WORKERS`: optional, defaults to `1`.
- `PORT`: optional, defaults to `8080`.
- `BUILD_RELEASE_MCP_REPO_ROOT`: optional checkout path used as the working
  directory for local scans and `gh`.
- `AI_REVIEW_MAX_DIFF_BYTES`: optional, defaults to `180000`.
- `AI_REVIEW_MAX_OUTPUT_TOKENS`: optional, defaults to `1800`.

## Deployment Notes

For a real hosted service, put this behind HTTPS and a reverse proxy or platform
load balancer. Do not expose it without webhook signature verification.

Start with a narrow `HOSTED_SERVICE_ALLOWED_REPOS` allowlist. Use a token with
only the permissions needed to read PRs and write PR comments.

This implementation stores job state in memory. If you need durable job history,
multiple replicas, retries, or audit trails, move the queue and job store to a
database or managed queue.

## Future GitHub App Version

The next maturity step is replacing `GH_TOKEN` with a GitHub App flow:

1. Verify webhook signatures the same way.
2. Read the installation ID from the webhook payload.
3. Mint an installation access token for that repo.
4. Run `gh` or GitHub API calls with that installation token.

That makes org-wide installation and permission management cleaner than a shared
PAT-style token.
