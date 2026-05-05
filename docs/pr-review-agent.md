# PR Review Agent Architecture

This project is the start of a PR Review Agent. It is not yet a fully automated
fix loop, but the core review and state pieces are in place.

## Current Capabilities

The implementation can:

- Collect PR context through MCP tools.
- Run an AI review.
- Normalize findings into structured records.
- Persist finding state.
- Reconcile findings across new PR commits.
- Post or update a PR comment.
- Run a manual or hosted opt-in minor-fix workflow.

## Target Flow

```text
PR opened or updated
  -> GitHub App webhook receiver
  -> worker queue
  -> PR Review Agent
  -> MCP tools collect PR context
  -> review engine creates findings
  -> state DB tracks finding lifecycle
  -> optional fix agent creates a branch or commit
  -> GitHub API posts review output
  -> new PR commits trigger reconciliation
```

## MCP Tool Boundary

The hosted service owns orchestration, permissions, queueing, state, and GitHub
App lifecycle.

MCP is the agent tool boundary. Narrow tools expose repository, PR, CI,
ownership, and write operations to the agent without making the model
responsible for service control flow or persistence.

Examples of MCP boundary tools:

- `pr_overview`
- `pr_files`
- `pr_diff`
- `pr_check_runs`
- `pr_codeowners`
- `pr_file`
- `create_branch`
- `commit_file_change`
- `post_review_comment`
- `mark_finding_resolved`

## Implementation Boundaries

- `hosted_service.py`: webhook handling, queue orchestration, GitHub App auth,
  and hosted review/fix workflow control.
- `server.py`: MCP tool boundary for PR context, CI context, repository reads,
  branch/file writes, review comments, and finding status updates.
- `review_runner.py`: CLI runner that collects MCP context, calls the model, and
  delegates review-specific parsing/rendering.
- `review_engine.py`: review prompts, structured finding parsing, and Markdown
  rendering.
- `findings.py`: finding schema, statuses, normalization, and stable
  fingerprinting.
- `reconciliation.py`: finding lifecycle reconciliation across PR commits.
- `job_store.py`: SQLite-backed job and finding persistence.
- `github_writer.py`: GitHub PR comment create/update helpers.
- `fix_runner.py`: opt-in minor fix generation and guarded patch application.

## Core Agent Pieces

1. Context Collector
   - PR diff, changed files, check runs, CODEOWNERS, previous comments, test
     results, relevant file contents, and repository config.
2. Review Engine
   - Structured findings for real issues only: bugs, missing tests, security
     concerns, deployment or release risk, broken CI, and ownership gaps.
3. State Store
   - PR number, reviewed commit SHA, finding ID, file/line, issue summary,
     status (`open`, `resolved`, `ignored`), and fix commit when available.
4. Fix Agent
   - Safe, opt-in fixes such as small bug fixes, test updates, config fixes,
     docs updates, or changelog updates.
5. Feedback Loop
   - On every new commit, compare against previous findings, mark resolved
     items, keep unresolved items, honor ignored items, and comment only on new
     or materially changed findings.

## Implementation Status

Done:

- Add a `findings` table to `JobStore`.
- Define a `Finding` schema with stable fingerprinting.
- Make review output structured JSON internally, with Markdown generated only at
  the posting layer.
- Add finding reconciliation on new commits: `open`, `resolved`, `ignored`, and
  `new`.
- Add first-class context tools for PR checks, test result summaries,
  CODEOWNERS, and file reads.
- Move minor fixes into the hosted service as an opt-in action gated by service
  and repository config.
- Add MCP write tools after state tracking exists: `create_branch`,
  `commit_file_change`, `post_review_comment`, and `mark_finding_resolved`.

Next:

- Add test artifact parsing when projects upload machine-readable test reports.
