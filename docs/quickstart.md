# Quickstart

Use this guide for local setup, MCP client configuration, and basic validation.

## Requirements

- Python 3.11+
- GitHub CLI (`gh`)
- Authenticated `gh` session:

```sh
gh auth login -h github.com
gh auth status
```

## Run Locally

From this checkout:

```sh
python3 -m build_release_mcp
```

By default, commands run in the current working directory. If your MCP client
starts servers from another directory, set `BUILD_RELEASE_MCP_REPO_ROOT`:

```sh
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/your/repo python3 -m build_release_mcp
```

## MCP Client Config

Use an absolute path to this checkout:

```json
{
  "mcpServers": {
    "build-release": {
      "command": "python3",
      "args": ["-m", "build_release_mcp"],
      "cwd": "/path/to/build-release-mcp-server",
      "env": {
        "BUILD_RELEASE_MCP_REPO_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

Some clients do not support `cwd`; in that case point directly at the module:

```json
{
  "mcpServers": {
    "build-release": {
      "command": "python3",
      "args": ["/path/to/build-release-mcp-server/build_release_mcp/server.py"],
      "env": {
        "BUILD_RELEASE_MCP_REPO_ROOT": "/path/to/your/repo"
      }
    }
  }
}
```

## Test A GitHub PR

You do not need a GitHub Actions workflow for local PR review.

1. Clone the repository that contains the PR.
2. Authenticate GitHub CLI.
3. Configure your MCP client to run this server and set
   `BUILD_RELEASE_MCP_REPO_ROOT` to the cloned repository.
4. Ask your MCP client:

```text
Use the review_pr prompt for https://github.com/OWNER/REPO/pull/123.
Focus on correctness bugs and missing tests.
```

The MCP client calls this server for PR metadata, changed files, diffs, check
runs, CODEOWNERS matches, and review threads. The model then uses that context
to produce review findings.

## Review Runner

The review runner calls the MCP server, sends the collected PR context to the
OpenAI Responses API, and prints a Markdown review.

Run locally:

```sh
OPENAI_API_KEY=... \
OPENAI_MODEL=gpt-5 \
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/repo \
python3 -m build_release_mcp.review_runner https://github.com/OWNER/REPO/pull/123
```

Post the result as a PR comment:

```sh
OPENAI_API_KEY=... \
GH_TOKEN=... \
BUILD_RELEASE_MCP_REPO_ROOT=/path/to/repo \
python3 -m build_release_mcp.review_runner https://github.com/OWNER/REPO/pull/123 --post-comment
```

Environment variables:

- `OPENAI_API_KEY`: required.
- `OPENAI_MODEL`: optional, defaults to `gpt-5`.
- `OPENAI_BASE_URL`: optional, defaults to `https://api.openai.com/v1`.
- `BUILD_RELEASE_MCP_REPO_ROOT`: repository checkout used by `gh`, `git`, and
  local scans.
- `AI_REVIEW_MAX_DIFF_BYTES`: optional diff limit, defaults to `180000`.
- `AI_REVIEW_MAX_OUTPUT_TOKENS`: optional model output limit, defaults to
  `1800`.

## Smoke Test

This verifies the server protocol without calling GitHub:

```sh
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"prompts/list","params":{}}' \
  | python3 -m build_release_mcp
```

Run unit tests:

```sh
python3 -m unittest discover -s tests
```
