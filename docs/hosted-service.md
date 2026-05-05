# Hosted Service

The hosted service turns this project into a GitHub webhook receiver. GitHub
sends pull request events to the service, the service verifies the webhook
signature, queues a background review job, runs the existing review runner, and
posts the result back to the PR.

The service supports either a `GH_TOKEN`/`GITHUB_TOKEN` or GitHub App
installation tokens. GitHub App auth is preferred for multi-repo hosting.

## Flow

```text
GitHub pull_request webhook
  -> POST /webhooks/github
  -> HMAC signature verification
  -> action/repo/fork/draft filtering
  -> SQLite idempotency check
  -> background review job
  -> optional repo config from .build-release-mcp.yml
  -> MCP PR tools collect context
  -> OpenAI Responses API reviews context
  -> previous bot comment is updated, or a new comment is posted
```

## Run

```sh
GITHUB_WEBHOOK_SECRET=... \
GITHUB_APP_ID=... \
GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github-app.pem \
OPENAI_API_KEY=... \
HOSTED_SERVICE_ALLOWED_REPOS=OWNER/REPO \
python3 -m build_release_mcp.hosted_service
```

The service listens on `0.0.0.0:8080` by default.

For local testing, `GH_TOKEN=...` is also supported.

## Endpoints

### `GET /health/live`

Returns `200` when the process is alive.

### `GET /health/ready`

Returns `200` when required environment variables are present.

Required:

- `GITHUB_WEBHOOK_SECRET`
- `OPENAI_API_KEY`
- `GH_TOKEN` / `GITHUB_TOKEN`, or GitHub App credentials

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

Returns SQLite-backed job status for a queued review.

## Environment Variables

- `GITHUB_WEBHOOK_SECRET`: required webhook HMAC secret.
- `GH_TOKEN` or `GITHUB_TOKEN`: optional token used by `gh` to read PRs and
  post comments. Useful for local testing.
- `GITHUB_APP_ID`: GitHub App ID. Required for GitHub App auth.
- `GITHUB_APP_PRIVATE_KEY`: GitHub App private key text. Use `\n` escapes if
  storing it as a single-line environment variable.
- `GITHUB_APP_PRIVATE_KEY_FILE`: path to a PEM private key file. Preferred over
  `GITHUB_APP_PRIVATE_KEY` for deployment.
- `OPENAI_API_KEY`: required model API key.
- `OPENAI_MODEL`: optional, defaults to `gpt-5`.
- `OPENAI_BASE_URL`: optional, defaults to `https://api.openai.com/v1`.
- `HOSTED_SERVICE_ALLOWED_REPOS`: optional comma-separated allowlist such as
  `owner/repo,owner/other-repo`.
- `HOSTED_SERVICE_ALLOW_FORKS`: optional, defaults to `false`.
- `HOSTED_SERVICE_HOST`: optional, defaults to `0.0.0.0`.
- `HOSTED_SERVICE_WORKERS`: optional, defaults to `1`.
- `HOSTED_SERVICE_ENABLE_MINOR_FIXES`: optional, defaults to `false`. Enables
  the hosted worker's minor-fix path only when repository config also opts in.
- `HOSTED_SERVICE_DB`: optional SQLite DB path, defaults to
  `/tmp/build-release-mcp/jobs.sqlite3`.
- `PORT`: optional, defaults to `8080`.
- `BUILD_RELEASE_MCP_REPO_ROOT`: optional checkout path used as the working
  directory for local scans and `gh`.
- `AI_REVIEW_MAX_DIFF_BYTES`: optional, defaults to `180000`.
- `AI_REVIEW_MAX_OUTPUT_TOKENS`: optional, defaults to `1800`.

## GitHub App Setup

Create a GitHub App with:

- Webhook URL: `https://YOUR_HOST/webhooks/github`
- Webhook secret: same value as `GITHUB_WEBHOOK_SECRET`
- Repository permissions:
  - Contents: read
  - Pull requests: read/write
  - Issues: read/write
  - Metadata: read
- Subscribe to Pull request events.

Install the app on the repositories you want to review. The webhook payload
contains an installation ID; the service uses that ID to mint a short-lived
installation token for each job.

The GitHub App path requires `openssl` at runtime to sign the JWT using the app
private key.

## Repository Config

Each target repository can define `.build-release-mcp.yml`:

```yaml
model: gpt-5

pr_review:
  enabled: true
  minor_fixes_enabled: false
  max_diff_bytes: 180000
  ignored_paths:
    - docs/**
    - "*.md"
```

Supported keys:

- `model`: default model for review.
- `pr_review.enabled`: disable automated PR review when `false`.
- `pr_review.minor_fixes_enabled`: allow the hosted service to run the minor-fix
  agent when `HOSTED_SERVICE_ENABLE_MINOR_FIXES=true`.
- `pr_review.max_diff_bytes`: max diff bytes collected for the model.
- `pr_review.ignored_paths`: path globs to omit from the changed-file summary.

An example is included at `.build-release-mcp.example.yml`.

## Idempotency

The SQLite job store deduplicates by:

- GitHub webhook delivery ID.
- Repository + PR number + PR head SHA.

This prevents duplicate reviews when GitHub retries a delivery or when multiple
events arrive for the same PR commit.

## Comment Updates

Review comments include a hidden marker. When the service posts a new result,
it first looks for an existing marker comment and updates it in place. If no
marker comment exists, it creates a new PR comment.

The hosted worker now stores structured findings in SQLite. Each run reconciles
the current model findings against previous findings for the PR:

- New findings are marked `open`.
- Findings still present on a later commit stay `open`.
- Missing findings are marked `resolved`.
- Findings manually marked `ignored` stay ignored.

The PR comment emphasizes new findings for the reviewed commit, notes resolved
findings, and reports remaining open or ignored counts.

## Minor Fixes

The hosted minor-fix path is disabled by default. It runs only when both are
true:

- `HOSTED_SERVICE_ENABLE_MINOR_FIXES=true`
- `.build-release-mcp.yml` sets `pr_review.minor_fixes_enabled: true`

When enabled and a review produces new findings, the worker invokes the same
minor-fix runner used by the manual workflow. The runner still validates the
model response with `git apply --check`, refuses dirty worktrees, blocks
workflow-file edits, commits successful changes, pushes the checked-out PR
branch, and posts a separate minor-fix status comment.

## Deployment Notes

For a real hosted service, put this behind HTTPS and a reverse proxy or platform
load balancer. Do not expose it without webhook signature verification.

Start with a narrow `HOSTED_SERVICE_ALLOWED_REPOS` allowlist. Use a token with
only the permissions needed to read PRs and write PR comments.

This implementation uses an in-process queue. SQLite makes job state durable,
but multiple service replicas should use a real queue or ensure only one worker
process consumes jobs.

## Docker

Build:

```sh
docker build -t build-release-mcp-server .
```

Run:

```sh
docker run --rm -p 8080:8080 \
  -e GITHUB_WEBHOOK_SECRET=... \
  -e GITHUB_APP_ID=... \
  -e GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github-app.pem \
  -e OPENAI_API_KEY=... \
  -e HOSTED_SERVICE_ALLOWED_REPOS=OWNER/REPO \
  -v "$PWD/secrets:/run/secrets:ro" \
  build-release-mcp-server
```
