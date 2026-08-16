# Live remediations (real Devin sessions, real pull requests)

Target repository: https://github.com/amrupapz/superset (fork of apache/superset)
Trigger label: `devin-ready`

## Issue #1 — remove the orphaned dashboard `ExampleComponent` POC

| | |
| --- | --- |
| Issue | https://github.com/amrupapz/superset/issues/1 |
| Devin session | https://app.devin.ai/sessions/d6e49f1b5aba47cd916d5cdafca769ed |
| Pull request | https://github.com/amrupapz/superset/pull/3 (open, `devin/issue-1` → `master`, not merged) |
| Orchestrator outcome | `done` (structured output `status=fixed` **and** a real PR URL) |
| Issue comment posted by the orchestrator | 2026-08-15T03:21:08Z on issue #1 |

Verification the session ran and reported (full output in the PR body):

```
rg -n 'ExampleComponent|dashboardComponents/Example' .   -> no matches
pre-commit run --files <the three touched paths>         -> oxfmt / oxlint / custom rules /
                                                            stylelint / Type-Checking (Frontend) Passed
npx jest src/preamble.test.ts                            -> PASS, 6/6 tests
```

## Issue #2 — add direct tests for the `useIsMobile` media-query lifecycle

| | |
| --- | --- |
| Issue | https://github.com/amrupapz/superset/issues/2 |
| Devin session | https://app.devin.ai/sessions/e3177eecf75c4fac8f39d0e3459ab4a9 |
| Pull request | https://github.com/amrupapz/superset/pull/4 (open, `devin/issue-2` → `master`, not merged) |
| Orchestrator outcome | `done` |
| Issue comment posted by the orchestrator | 2026-08-15T03:30:46Z on issue #2 |

Verification the session ran and reported (full output in the PR body):

```
npx jest src/hooks/useIsMobile.test.ts   -> PASS, 5/5 tests
npx oxlint --config oxlint.json src/hooks/useIsMobile.test.ts -> exit 0, no findings
pre-commit run (staged file)             -> oxfmt / oxlint / custom rules / stylelint / Type-Checking (Frontend) Passed
```

## CI status of the two pull requests

Checked with the GitHub API on 2026-08-16:

```
PR #3: 0 passed, 0 failed, 0 pending, 0 skipped
PR #4: 0 passed, 0 failed, 0 pending, 0 skipped
GET /repos/amrupapz/superset/actions/runs -> total_count: 0
```

Apache Superset's workflows are not enabled on this fork, so **there are no CI
checks to be green or red on either PR**. Both PRs were verified locally only,
with the commands above. Neither PR is merged.
