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
             │  POST /v3/organizations/{org_id}/sessions
             ▼
        Devin session ──── opens PR on the repo
             │  GET /v3/organizations/{org_id}/sessions/{id}
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
| `DEVIN_API_KEY` | service-user token (`cog_...`) for the current Devin API |
| `DEVIN_ORG_ID` | Devin organization ID (`org-...`) used by the v3 API |
| `DEVIN_MAX_ACU` | hard ACU limit for each launched session |
| `GITHUB_TOKEN` | fine-grained PAT with Contents / Issues / Pull requests RW on the target repo |
| `GITHUB_REPO` | `owner/repo` to watch |
| `BASE_BRANCH` | branch PRs target |
| `TRIGGER_LABEL` | label that marks an issue as approved for autonomous remediation |
| `POLL_INTERVAL` | seconds between issue/session polls |
| `MAX_CONCURRENT` | cap on simultaneous Devin sessions |
| `HOURS_SAVED_PER_ISSUE` | assumption used by the hours-saved metric, shown on the dashboard |
| `WEBHOOK_SECRET` | required for webhook delivery in live mode; enables HMAC verification |

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
  success rate, median time-to-PR, ACUs consumed, and estimated engineer-hours
  saved (assumption printed on screen).
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
- **Current Devin API.** Live calls use the organization-scoped v3 API and
  service-user keys. Completion is detected from `status=running` plus
  `status_detail=finished`, as specified by the [v3 session response contract](https://docs.devin.ai/api-reference/v3/sessions/get-organizations-session).
  See Devin's [migration guide](https://docs.devin.ai/api-reference/getting-started/migration-guide)
  to create the required service user.

## Proven end-to-end result

Two real `devin-ready` issues in the Superset fork produced two open,
mergeable pull requests. The issue comments link each API-launched Devin session
and record its verification commands. See [the evidence report](evidence/final-live-remediations.md).

| Issue | Devin output |
| --- | --- |
| [#1 Remove orphaned ExampleComponent](https://github.com/amrupapz/superset/issues/1) | [PR #3](https://github.com/amrupapz/superset/pull/3) |
| [#2 Test useIsMobile lifecycle](https://github.com/amrupapz/superset/issues/2) | [PR #4](https://github.com/amrupapz/superset/pull/4) |

## Verification

```bash
pip install -r requirements-dev.txt
pytest -q
docker build -t devin-remediation-orchestrator .
```

The same checks run in GitHub Actions. For the presentation, use the
[five-minute Loom runbook](docs/LOOM_SCRIPT.md).

## Next steps

- Snyk/Dependabot/Jira as additional event sources.
- Approval gates for high-risk changes (auto-merge low-risk, require review above
  a risk threshold).
- Per-repo playbooks so the prompt carries repo conventions.
- Auto-retry by messaging the session when CI fails on its PR.
