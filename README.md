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

## What it has actually done

Target fork: https://github.com/amrupapz/superset

| Issue | Devin session | Pull request | Outcome |
| --- | --- | --- | --- |
| [#1 remove orphaned `ExampleComponent` POC](https://github.com/amrupapz/superset/issues/1) | [session](https://app.devin.ai/sessions/d6e49f1b5aba47cd916d5cdafca769ed) | [#3](https://github.com/amrupapz/superset/pull/3) (open) | `done` |
| [#2 test the `useIsMobile` lifecycle](https://github.com/amrupapz/superset/issues/2) | [session](https://app.devin.ai/sessions/e3177eecf75c4fac8f39d0e3459ab4a9) | [#4](https://github.com/amrupapz/superset/pull/4) (open) | `done` |

Both PRs are left unmerged for review. Full details, including the exact
verification each session ran and sample `/metrics` output, are in
[`evidence/`](evidence/README.md). See also
[known limitations](#known-limitations).

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
             │       (prompt + structured_output_schema + max_acu_limit)
             ▼
        Devin session ──── opens PR on the repo
             │  GET /v3/organizations/{org_id}/sessions/{devin_id}
             │       (status, status_detail, pull_requests,
             │        structured_output, acus_consumed)
             ▼
   SQLite (tasks) ──► issue comment (PR + session link + verification)
             │
             ▼
   /dashboard · /metrics · structured JSON logs
```

State per issue: `running → done | blocked | failed`. Never more than
`MAX_CONCURRENT` live sessions, and never two sessions for the same issue.

**A completed session is not a success.** `done` requires both
`structured_output.status == "fixed"` **and** a real pull-request URL (taken from
the session's `pull_requests`, falling back to `structured_output.pr_url`). A
session that reaches `status_detail=finished` without a PR is recorded as
`blocked` and reported on the issue as needing a human; `status=error`, or
`suspended` before finishing (e.g. hitting the ACU ceiling), is `failed`.

Devin v3 states the orchestrator reasons about: `new`, `claimed`, `running`,
`resuming` are in flight (unless `status_detail == "finished"`); `exit`, `error`
and `suspended` are settled.

## Quickstart (no credentials, 60 seconds)

```bash
cp .env.example .env    # DRY_RUN=true is already the default
docker compose up --build
```

Open http://localhost:8000/dashboard. In dry-run the Devin and GitHub calls are
replaced with canned responses that walk through the real state machine, so the
poller, the store, the metrics and the dashboard are all genuinely exercised.

```bash
# or without compose
docker build -t devin-remediation-orchestrator .
docker run -p 8000:8000 -e DRY_RUN=true -e DB_PATH=/tmp/demo.db \
  devin-remediation-orchestrator
curl -s localhost:8000/metrics
```

Sample output of a complete dry-run cycle is committed under `evidence/`.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The suite covers webhook HMAC verification (valid, invalid, missing signature),
repository and label filtering, duplicate issue/session prevention, the v3
request shape (URL, bearer auth, `max_acu_limit`), successful completion with a
PR, a finished session without a PR, errored/suspended sessions, and a mock
end-to-end issue → session → PR → metrics cycle. CI (`.github/workflows/ci.yml`)
runs the suite and builds the Docker image on every push and pull request.

## Live run (Devin v3)

Put real values in `.env`:

| Variable | Meaning |
| --- | --- |
| `DEVIN_API_KEY` | **service-user** API key (prefix `cog_`); v3 organization endpoints reject personal keys |
| `DEVIN_ORG_ID` | organization the sessions belong to (prefix `org-`) |
| `MAX_ACU_PER_SESSION` | hard ACU ceiling sent as `max_acu_limit` on every session |
| `GITHUB_TOKEN` | fine-grained PAT with Contents / Issues / Pull requests RW on the target repo |
| `GITHUB_REPO` | `owner/repo` to watch |
| `BASE_BRANCH` | branch PRs target |
| `TRIGGER_LABEL` | label that marks an issue as approved for autonomous remediation |
| `POLL_INTERVAL` | seconds between issue/session polls |
| `MAX_CONCURRENT` | cap on simultaneous Devin sessions |
| `HOURS_SAVED_PER_ISSUE` | assumption used by the hours-saved metric, shown on the dashboard |
| `WEBHOOK_SECRET` | optional; enables HMAC signature verification on the webhook |

Set `DRY_RUN=false` and `docker compose up`. Labelling an issue `devin-ready` is
the only action a human takes. Credentials are read from the environment only —
they are never logged, echoed on the dashboard, or written to the database.

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

## What / How / Why / When

**What.** Maintenance backlog: dead code, missing coverage, lint and dependency
debt. Individually cheap, collectively a quarter of engineering time, and always
last in the queue. The unit of work is a well-specified issue nobody will pick up.

**How.** Labelling an issue `devin-ready` is the entire human workflow. A webhook
(with a poller as a resilient fallback) hands the issue to the orchestrator, which
creates one ACU-capped Devin session per issue with the acceptance criteria and a
required structured-output schema, tracks it to a settled state, and reports back
on the issue with the PR, the session link, the exact verification commands and
reviewer risk notes. `/dashboard` and `/metrics` show throughput, success rate,
median time-to-PR, ACUs consumed and the queue of runs that need a human.

**Why Devin specifically.** These fixes are not textual. Issue #1 required
checking whether a component was registered anywhere before deleting it; issue #2
required reading a hook, discovering the existing test helper could not fire
`change` events, and writing a `MediaQueryList` double for the Safari `<14`
fallback path. Both required running the repo's own lint, type-check and jest
suites and reporting the output. A script can open a PR; it cannot decide that
the acceptance criteria are wrong and report `blocked` instead — which this
system treats as a first-class, correct outcome.

**When / rollout.** Start with one repo and one label, human review on every PR.
Add event sources (Snyk, Dependabot, Jira, CI failures) and per-repo playbooks;
gate auto-merge on risk class. Track PRs merged per week, review-to-merge time,
revert rate and ACUs per merged PR — if ACUs per merged PR is flat while merged
PRs per week rises, the system is compounding.

## Known limitations

- Apache Superset's GitHub Actions workflows are not enabled on the fork, so the
  remediation PRs (#3, #4) have **zero** CI checks. Verification was run locally
  inside the Devin sessions and pasted into the PR bodies; no green CI is claimed.
- The live v3 credentials available in this environment returned HTTP 403 against
  `/v3/organizations/{org_id}/sessions`, so the two live sessions in `evidence/`
  were created through the earlier v1 integration. The v3 client is covered by
  request-shape tests and the dry-run path, but has not been exercised against a
  live v3-authorized service-user key.
- SQLite plus in-process threads: single instance only. Horizontal scaling needs
  Postgres and an external queue.
- Webhook deliveries are authenticated and filtered by repository, event, action
  and label, but not replay-protected beyond the per-issue deduplication.
- `HOURS_SAVED_PER_ISSUE` is an assumption, not a measurement; the dashboard
  prints it next to the derived number for that reason.
- The dry-run Devin client returns a placeholder PR URL
  (`https://github.com/example/superset/pull/1`) — dry-run evidence is labelled as
  such and must not be read as a real pull request.

## Next steps

- Snyk/Dependabot/Jira as additional event sources.
- Approval gates for high-risk changes (auto-merge low-risk, require review above
  a risk threshold).
- Per-repo playbooks so the prompt carries repo conventions.
- Auto-retry by messaging the session when CI fails on its PR.
