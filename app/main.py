import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import store
from app.config import DRY_RUN, POLL_INTERVAL, TRIGGER_LABEL, WEBHOOK_SECRET
from app.log import event
from app.orchestrator import Orchestrator

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
orchestrator = Orchestrator()


def verify_webhook_signature(raw: bytes, signature: str, secret: str) -> bool:
    if not secret:
        return DRY_RUN
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def actionable_issue(payload: dict, github_event: str, trigger_label: str) -> bool:
    if github_event != "issues" or payload.get("action") not in {"labeled", "opened", "reopened"}:
        return False
    labels = {label.get("name") for label in payload.get("issue", {}).get("labels", [])}
    return trigger_label in labels


@asynccontextmanager
async def lifespan(_app: FastAPI):
    event("startup", dry_run=DRY_RUN, poll_interval=POLL_INTERVAL, label=TRIGGER_LABEL)
    orchestrator.start()
    yield
    orchestrator.stop()


app = FastAPI(title="Devin Remediation Orchestrator", lifespan=lifespan)


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
    launched = orchestrator.sync_issues()
    orchestrator.poll_sessions()
    return {"launched": launched, "metrics": orchestrator.metrics()}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> dict:
    raw = await request.body()
    if not verify_webhook_signature(raw, x_hub_signature_256, WEBHOOK_SECRET):
        detail = "WEBHOOK_SECRET is required when DRY_RUN=false" if not WEBHOOK_SECRET else "bad signature"
        raise HTTPException(status_code=401, detail=detail)

    payload = await request.json()
    if not actionable_issue(payload, x_github_event, TRIGGER_LABEL):
        return {"ignored": True}

    issue = payload.get("issue", {})
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
