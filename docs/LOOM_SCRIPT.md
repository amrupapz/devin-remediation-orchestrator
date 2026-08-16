# Loom script — Devin Remediation Orchestrator (~4:30)

Audience: VP Engineering plus senior ICs. Speak it straight through; the timings
are the budget, not a target. Screens to have open in tabs beforehand:

1. GitHub issues list on `amrupapz/superset` (both issues labelled `devin-ready`)
2. `http://localhost:8000/dashboard` (container running in dry-run)
3. The Devin session for issue #2
4. PR #4 on the fork
5. `app/orchestrator.py` and `app/devin.py` in the editor

---

## 0:00 — What (45s)

"Every engineering org has the same backlog: dead code, missing test coverage,
lint and dependency debt. Each item is a couple of hours, everyone agrees it
should be done, and it is always the thing that gets bumped. It's not a
prioritisation problem — it's a capacity problem, and the work is too
judgement-heavy to script.

So I built the smallest system that turns 'we should fix that' into a reviewed
pull request. The only human action is labelling an issue `devin-ready`.
Everything after that label is automated, and everything it produces is designed
to be reviewed by a human, not trusted blindly."

## 0:45 — How, the demo (1:30)

*(Screen 1 — issues)* "This is a fork of Apache Superset. Two real issues I
filed: an orphaned proof-of-concept dashboard component that's dead production
code, and a `useIsMobile` hook whose media-query lifecycle has no direct tests.
Both are labelled `devin-ready`.

*(Screen 2 — dashboard)* "The orchestrator picked them up — a GitHub webhook is
the trigger, with a poller as a fallback so a missed delivery never stalls the
pipeline. It launched one Devin session per issue and it's tracking them:
in-flight, PRs opened, success rate, median time-to-PR, ACUs consumed, and a
'needs a human' queue. If I'm an engineering leader, this page is how I know it's
working — and how much it costs.

*(Screen 3 — the session)* "This is Devin doing the work on issue #2: reading the
hook, discovering the existing test helper can't fire `change` events, writing a
`MediaQueryList` double, running the repo's own jest, lint and type-check.

*(Screen 4 — PR #4)* "And this is the output: a pull request that says `Fixes #2`,
with the exact commands and their results, and reviewer risk notes. The
orchestrator posted the same summary back on the issue. It did not merge
anything — a human still owns that decision."

## 2:15 — How, the architecture (1:00)

*(Screen 5 — code)* "Three decisions worth calling out.

First, structured output. Every session is created with a required JSON schema —
`status`, `pr_url`, `verification`, `risk_notes` — so the orchestrator branches on
typed fields instead of parsing prose.

Second, and this is the important one: a completed session is not a success. A
session only counts as `done` if it reports `fixed` *and* there's a real pull
request URL in the v3 `pull_requests` field. Finished with no PR is `blocked`, and
it goes on the 'needs a human' queue with Devin's own stated reason. That matters
because the prompt explicitly tells the agent that if the acceptance criteria are
wrong, it should report `blocked` rather than force a PR. An agent declining to
make a bad change is a correct outcome, and the system is built to record it as
one instead of hiding it.

Third, control: this runs on the v3 organization endpoints with a service-user
key, one session per issue enforced in the store, a concurrency cap, and an
explicit ACU ceiling on every session. It's dockerised, it has a test suite for
the webhook signature, the filtering, the deduplication and the no-PR case, and CI
builds the image."

## 3:15 — Why Devin (45s)

"Why does this need an autonomous agent rather than a codemod? Look at what each
fix actually required. For the dead component, deciding it was safe to delete
meant checking whether it was registered anywhere in the dashboard registry. For
the hook, it meant reading the existing test utilities, concluding they were
insufficient, and writing a fake that also covers the Safari-under-14
`addListener` fallback. Then running the repo's real test and type-check suites
and reporting the output.

A script can delete a file and open a PR. It can't investigate a repository,
decide the request is wrong, or write the verification a reviewer will actually
read. That investigation is the whole job, and it's the part that made this
backlog stay a backlog."

## 4:00 — When, next steps (30s)

"In a real engagement I'd start narrow: one repo, one label, human review on every
PR. Then add event sources — Snyk findings, Dependabot, Jira, CI failures — and
per-repo playbooks so the prompt carries local conventions, and gate auto-merge on
a risk class instead of on everything.

The numbers I'd hold it to: PRs merged per week, review-to-merge time, revert
rate, and ACUs per merged PR. If ACUs per merged PR stays flat while merged PRs
per week goes up, the system is compounding — and that's the case for expanding
it. Repos and evidence are in the description; happy to go deeper anywhere."
