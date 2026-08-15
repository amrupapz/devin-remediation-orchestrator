import hashlib
import hmac
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import store
from app.config import DRY_RUN, POLL_INTERVAL, TRIGGER_LABEL, WEBHOOK_SECRET
from app.log import event
from app.orchestrator import Orchestrator

app = FastAPI(title="Devin Remediation Orchestrator")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
orchestrator = Orchestrator()


@app.on_event("startup")
def _startup() -> None:
    event("startup", dry_run=DRY_RUN, poll_interval=POLL_INTERVAL, label=TRIGGER_LABEL)
    orchestrator.start()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "dry_run": DRY_RUN}


@app.get("/metrics")
def metrics() -> JSONResponse:
    return JSONResponse(orchestrator.metrics())


@app.get("/tasks")
def tasks() -> JSONResponse:
    return JSONResponse(store.all_tasks())


@app.post("/sync")
def sync() -> dict:
    """Manual trigger, mostly for demos: same code path as the poller."""
    return {"launched": orchestrator.sync_issues()}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> dict:
    raw = await request.body()
    if WEBHOOK_SECRET:
        expected = "sha256=" + hmac.new(
            WEBHOOK_SECRET.encode(), raw, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="bad signature")

    payload = await request.json()
    if x_github_event != "issues" or payload.get("action") not in {"labeled", "opened", "reopened"}:
        return {"ignored": True}

    issue = payload.get("issue", {})
    labels = {label["name"] for label in issue.get("labels", [])}
    if TRIGGER_LABEL not in labels:
        return {"ignored": True}

    event("webhook_received", issue=issue.get("number"), action=payload.get("action"))
    return {"launched": orchestrator.handle_issue(issue)}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "metrics": orchestrator.metrics(),
            "tasks": store.all_tasks(),
            "dry_run": DRY_RUN,
        },
    )
