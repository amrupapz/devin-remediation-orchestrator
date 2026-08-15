# Loom script (target: 4:30)

## 0:00–0:45 — What

“Engineering backlogs fill with valuable but chronically deferred work: dead
code, missing tests, and dependency hygiene. I built an event-driven remediation
service. An engineer expresses intent by adding `devin-ready`; the service turns
that issue into a supervised Devin session and an evidence-rich pull request.”

Show Superset issues #1 and #2.

## 0:45–2:10 — How

Show the README architecture, then briefly open `app/orchestrator.py` and
`app/devin.py`.

“A signed GitHub webhook accelerates the trigger, while an idempotent poller is
the resilient fallback. The orchestrator deduplicates issue numbers, caps
concurrency, and creates an organization-scoped Devin v3 session with the issue
acceptance criteria, repository, ACU limit, and a required structured-output
schema. It tracks the session to a terminal state and comments the result back
on the issue.”

Run:

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8000/dashboard`, then run `curl -X POST localhost:8000/sync`.
After two seconds, run that command once more and refresh the dashboard. The
manual endpoint performs the same issue and session reconciliation as the
background loop, without waiting for its interval.

## 2:10–3:15 — Real outputs

Open PR #3, PR #4, and one issue comment containing its Devin session URL and
verification.

“This is not only a simulation. Two real Superset issues produced two open,
mergeable PRs. One removes an orphaned component; the other adds five direct
lifecycle tests. The linked issue comments preserve the exact checks and risks.
No GitHub status checks were configured on this fork, so I state that boundary
instead of presenting local checks as CI.”

## 3:15–4:00 — Why Devin

“A conventional bot can bump a version or apply a codemod. Here each task needs
repository exploration, a scoped implementation, environment setup, test
selection, debugging, a PR, and reviewer-oriented reasoning. Devin is the core
execution primitive; the surrounding service supplies policy, triggers,
idempotency, budgets, and observability.”

Show `/metrics`: throughput, active/blocked/failed work, PR success rate,
time-to-PR, ACUs, and the explicit hours-saved assumption.

## 4:00–4:30 — When / next steps

“For production I would add Dependabot, Snyk, or Jira event sources; per-repo
playbooks; CI-result feedback into the same session; risk-based approval gates;
and SLOs for time-to-first-PR, acceptance rate, and ACU cost per merged change.
I would keep human review as the default boundary and only auto-merge narrowly
classified low-risk changes.”
