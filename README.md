# Devin Remediation Orchestrator

Event-driven service that turns labelled GitHub issues into merged-ready pull
requests by launching and supervising Devin sessions through the Devin API.

## The problem

Engineering backlogs accumulate work that is individually small and collectively
enormous: dead code, missing test coverage, dependency bumps, lint debt. Each item
is well understood and nobody has the hours. Scripts can only handle the
mechanical part — they cannot read a failing test, understand why a change broke a
call site, and justify the fix in a pull request.

This service closes that loop: label an issue, get a reviewed pull request.

## Architecture

```
 GitHub issue labelled `devin-ready`
             │
     ┌───────┴────────┐
     │                │
 webhook          poller (every POLL_INTERVAL s, resilient fallback)
     │                │
     └───────┬────────┘
             ▼
      Orchestrator (state machine, concurrency cap)
             │  POST /v1/sessions  (prompt + structured_output_schema)
             ▼
        Devin session ──── opens PR on the repo
             │  GET /v1/sessions/{id}  (status_enum, structured_output)
             ▼
   SQLite (tasks) ──► issue comment (PR + session link + verification)
             │
             ▼
   /dashboard · /metrics · structured JSON logs
```

State per issue: `running → done | blocked | failed`. Never more than
`MAX_CONCURRENT` live sessions, and never two sessions for the same issue.

## Quickstart (no credentials, 60 seconds)

```bash
cp .env.example .env    # DRY_RUN=true is already the default
docker compose up --build
```

Open http://localhost:8000/dashboard. In dry-run the Devin and GitHub calls are
replaced with canned responses that walk through the real state machine, so the
poller, the store, the metrics and the dashboard are all genuinely exercised.

## Live run

Put real values in `.env`:

| Variable | Meaning |
| --- | --- |
| `DEVIN_API_KEY` | https://app.devin.ai/settings/api-keys |
| `GITHUB_TOKEN` | fine-grained PAT with Contents / Issues / Pull requests RW on the target repo |
| `GITHUB_REPO` | `owner/repo` to watch |
| `BASE_BRANCH` | branch PRs target |
| `TRIGGER_LABEL` | label that marks an issue as approved for autonomous remediation |
| `POLL_INTERVAL` | seconds between issue/session polls |
| `MAX_CONCURRENT` | cap on simultaneous Devin sessions |
| `HOURS_SAVED_PER_ISSUE` | assumption used by the hours-saved metric, shown on the dashboard |
| `WEBHOOK_SECRET` | optional; enables HMAC signature verification on the webhook |

Set `DRY_RUN=false` and `docker compose up`. Labelling an issue `devin-ready` is
the only action a human takes.

### Webhook (optional)

Point a GitHub webhook at `POST /webhook/github` (content type JSON, `Issues`
events, secret = `WEBHOOK_SECRET`). The poller does the same work, so a missed
delivery or an unavailable tunnel never stalls the pipeline.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /dashboard` | live scoreboard, auto-refreshing |
| `GET /metrics` | the same numbers as JSON |
| `GET /tasks` | raw task rows |
| `POST /sync` | force one poll cycle (demo convenience) |
| `POST /webhook/github` | `issues.labeled` trigger |
| `GET /health` | liveness |

## Observability

- Dashboard tiles: issues detected, sessions launched, in flight, PRs opened,
  success rate, median time-to-PR, estimated engineer-hours saved (assumption
  printed on screen).
- A "needs a human" table lists every blocked or failed run with Devin's own
  stated reason. Failures are shown, not hidden — a session that declines to
  force an unsafe PR is a correct outcome.
- One structured JSON log line per state transition
  (`session_launched`, `session_finished`, `issue_commented`, …).

## Design notes

- **Structured output over scraping.** Every session is created with a JSON
  Schema requiring `status`, `pr_url`, `verification`, `risk_notes`, so the
  orchestrator branches on typed data instead of parsing prose.
- **The prompt carries the acceptance criteria verbatim** and explicitly permits
  `blocked` — the agent is told not to force a PR when the request is wrong.
- **Poller as primary trigger, webhook as accelerator.** Reconciling against
  GitHub state is idempotent; webhooks only reduce latency.

## Next steps

- Snyk/Dependabot/Jira as additional event sources.
- Approval gates for high-risk changes (auto-merge low-risk, require review above
  a risk threshold).
- Per-repo playbooks so the prompt carries repo conventions.
- Auto-retry by messaging the session when CI fails on its PR.
