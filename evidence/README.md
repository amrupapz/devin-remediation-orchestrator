# Evidence

Everything here was produced by running the orchestrator. Files are split into
**live** (real Devin sessions against the real fork) and **dry-run** (simulated
Devin/GitHub calls, `DRY_RUN=true`). No secrets, tokens, `.env` files or
databases are committed.

| File | Kind | What it is |
| --- | --- | --- |
| `live-remediations.md` | live | Issue → session → PR links for the two remediated issues, with the verification each session ran |
| `dry-run-metrics.json` | dry-run | `GET /metrics` after a full simulated cycle |
| `dry-run-tasks.json` | dry-run | `GET /tasks` for the same cycle |
| `dry-run-logs.jsonl` | dry-run | Structured orchestrator log lines for the same cycle |
| `pytest-output.txt` | local | `pytest -v` output (26 tests) |

## Exact commands used to produce this directory

```bash
# tests
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -v            # -> evidence/pytest-output.txt

# container build + dry-run cycle
docker build -t devin-remediation-orchestrator:local .
docker run -d --name orch-demo -p 8000:8000 \
  -e DRY_RUN=true -e POLL_INTERVAL=5 -e DB_PATH=/tmp/demo.db \
  devin-remediation-orchestrator:local
curl -s localhost:8000/metrics          # -> evidence/dry-run-metrics.json
curl -s localhost:8000/tasks            # -> evidence/dry-run-tasks.json
docker logs orch-demo | grep '^{'       # -> evidence/dry-run-logs.jsonl
```

The committed cycle happens to contain one `done` and one `blocked` run: the mock
client blocks a fraction of sessions on purpose so the "needs a human" path is
visible in the metrics and the logs.

Note on the dry-run PR URLs: `dry-run-tasks.json` contains
`https://github.com/example/superset/pull/1`. That is the canned placeholder the
mock Devin client returns — it is **not** a real pull request. Real PR URLs
appear only in `live-remediations.md`.
