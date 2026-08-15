import os


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
DEVIN_API_BASE = os.getenv("DEVIN_API_BASE", "https://api.devin.ai")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com")
GITHUB_REPO = os.getenv("GITHUB_REPO", "amrupapz/superset")
TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-ready")
BASE_BRANCH = os.getenv("BASE_BRANCH", "master")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "3"))
DRY_RUN = _bool("DRY_RUN", "true")
DB_PATH = os.getenv("DB_PATH", "/data/orchestrator.db")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
HOURS_SAVED_PER_ISSUE = float(os.getenv("HOURS_SAVED_PER_ISSUE", "2"))
