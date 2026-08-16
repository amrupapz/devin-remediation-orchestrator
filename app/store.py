import json
import os
import sqlite3
import threading
from typing import Any, Optional

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  issue_number INTEGER PRIMARY KEY,
  title TEXT,
  issue_url TEXT,
  session_id TEXT,
  session_url TEXT,
  status TEXT,
  pr_url TEXT,
  outcome TEXT,
  verification TEXT,
  risk_notes TEXT,
  error TEXT,
  session_status TEXT,
  session_status_detail TEXT,
  acus_consumed REAL,
  commented INTEGER DEFAULT 0,
  started_at REAL,
  finished_at REAL
);
"""

# Columns `update()` may write; keeps interpolated names off any input path.
UPDATABLE_COLUMNS = {
    "title",
    "issue_url",
    "session_id",
    "session_url",
    "status",
    "pr_url",
    "outcome",
    "verification",
    "risk_notes",
    "error",
    "session_status",
    "session_status_detail",
    "acus_consumed",
    "commented",
    "started_at",
    "finished_at",
}

_lock = threading.Lock()


def _connect(path: str) -> sqlite3.Connection:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    conn.commit()
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring a database created by an older build up to the current schema."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    for column, ddl in (
        ("session_status", "TEXT"),
        ("session_status_detail", "TEXT"),
        ("acus_consumed", "REAL"),
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}")


_conn = _connect(DB_PATH)


def use_database(path: str) -> None:
    """Point the store at another database file (used by the tests)."""
    global _conn
    with _lock:
        _conn.close()
        _conn = _connect(path)


def get(issue_number: int) -> Optional[dict]:
    with _lock:
        row = _conn.execute(
            "SELECT * FROM tasks WHERE issue_number = ?", (issue_number,)
        ).fetchone()
    return dict(row) if row else None


def all_tasks() -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM tasks ORDER BY issue_number DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def count_by_status(status: str) -> int:
    with _lock:
        row = _conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE status = ?", (status,)
        ).fetchone()
    return int(row["n"])


def insert(issue_number: int, title: str, issue_url: str, status: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO tasks (issue_number, title, issue_url, status) "
            "VALUES (?, ?, ?, ?)",
            (issue_number, title, issue_url, status),
        )
        _conn.commit()


def update(issue_number: int, **fields: Any) -> None:
    if not fields:
        return
    unknown = set(fields) - UPDATABLE_COLUMNS
    if unknown:
        raise ValueError(f"unknown task columns: {sorted(unknown)}")
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = [
        json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()
    ]
    with _lock:
        _conn.execute(
            f"UPDATE tasks SET {assignments} WHERE issue_number = ?",
            (*values, issue_number),
        )
        _conn.commit()
