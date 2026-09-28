"""SQLite storage.

Two tables keep the customer's original submission separate from what the
system derived from it:
  leads     - exactly what the customer submitted, plus workflow status
  analyses  - AI output, rule decisions and human decisions, kept side by side
              (ai_priority / rule_priority / human_priority, and so on) so the
              app can always explain who decided what.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

LEAD_STATUSES = ["New", "Reviewed", "Contacted", "Qualified", "Closed"]
EMAIL_STATUSES = ["Pending review", "Approved", "Rejected"]
JSON_FIELDS = ("priority_reasons", "key_details", "missing_info", "tags", "warnings")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name       TEXT NOT NULL,
    last_name        TEXT NOT NULL,
    email            TEXT,
    phone            TEXT,
    address          TEXT,
    monthly_bill     REAL,
    service_interest TEXT NOT NULL,
    message          TEXT,
    status           TEXT NOT NULL DEFAULT 'New',      -- human
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id            INTEGER NOT NULL UNIQUE REFERENCES leads(id) ON DELETE CASCADE,
    source             TEXT NOT NULL,          -- 'llm', 'demo' or 'fallback'
    ai_error           TEXT,                   -- user-safe reason if fallback was used
    -- AI: language understanding
    summary            TEXT NOT NULL,
    intent             TEXT NOT NULL,
    key_details        TEXT NOT NULL,          -- JSON list
    missing_info       TEXT NOT NULL,          -- JSON list (context questions only)
    ai_priority        TEXT NOT NULL,          -- AI's read of urgency (input to rules)
    ai_department      TEXT,                   -- AI suggestion (used only for 'Unsure')
    ai_next_action     TEXT NOT NULL,
    followup_timeframe TEXT NOT NULL,          -- AI suggestion (informational)
    email_subject      TEXT NOT NULL,          -- AI draft, human may edit
    email_body         TEXT NOT NULL,
    raw_response       TEXT,                   -- raw AI text, kept for auditing
    -- Rules: deterministic decisions
    rule_priority      TEXT NOT NULL,
    priority_reasons   TEXT NOT NULL,          -- JSON list
    department         TEXT NOT NULL,
    department_reason  TEXT,
    tags               TEXT NOT NULL,          -- JSON list
    warnings           TEXT NOT NULL,          -- JSON list
    follow_up_date     TEXT NOT NULL,
    -- Human: overrides and approvals
    human_priority     TEXT,
    human_next_action  TEXT,
    human_updated_at   TEXT,
    email_status       TEXT NOT NULL DEFAULT 'Pending review',
    email_edited       INTEGER NOT NULL DEFAULT 0,
    email_reviewed_at  TEXT,
    created_at         TEXT NOT NULL
);
"""

# Databases created by earlier versions of LeadFlow are upgraded in place.
_RENAMES = {"final_priority": "rule_priority", "next_action": "ai_next_action"}
_ADDED = {"ai_department": "TEXT", "department_reason": "TEXT", "human_priority": "TEXT",
          "human_next_action": "TEXT", "human_updated_at": "TEXT"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(analyses)")}
        for old, new in _RENAMES.items():
            if old in columns and new not in columns:
                conn.execute(f"ALTER TABLE analyses RENAME COLUMN {old} TO {new}")
        for name, sql_type in _ADDED.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE analyses ADD COLUMN {name} {sql_type}")


def save_lead_with_analysis(db_path: str, lead: dict, analysis: dict) -> int:
    """Insert the lead and its analysis in a single transaction."""
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO leads (first_name, last_name, email, phone, address, monthly_bill,
                                  service_interest, message, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'New', ?, ?)""",
            (lead["first_name"], lead["last_name"], lead["email"], lead["phone"], lead["address"],
             lead["monthly_bill"], lead["service_interest"], lead["message"], now, now),
        )
        lead_id = cur.lastrowid
        record = {k: (json.dumps(v) if k in JSON_FIELDS else v) for k, v in analysis.items()}
        record.update(lead_id=lead_id, created_at=now)
        columns = ", ".join(record)
        placeholders = ", ".join("?" for _ in record)
        conn.execute(f"INSERT INTO analyses ({columns}) VALUES ({placeholders})", list(record.values()))
    return lead_id


def _row_to_dict(row) -> dict:
    data = dict(row)
    for field in JSON_FIELDS:
        if field in data and data[field] is not None:
            data[field] = json.loads(data[field])
    return data


# `priority` and `next_action` are the *effective* values: a person's override wins.
_SELECT = """SELECT l.*, a.source, a.ai_error, a.summary, a.intent, a.key_details, a.missing_info,
                    a.ai_priority, a.ai_department, a.ai_next_action, a.followup_timeframe,
                    a.email_subject, a.email_body, a.raw_response,
                    a.rule_priority, a.priority_reasons, a.department, a.department_reason,
                    a.tags, a.warnings, a.follow_up_date,
                    a.human_priority, a.human_next_action, a.human_updated_at,
                    a.email_status, a.email_edited, a.email_reviewed_at,
                    COALESCE(a.human_priority, a.rule_priority) AS priority,
                    COALESCE(a.human_next_action, a.ai_next_action) AS next_action
             FROM leads l JOIN analyses a ON a.lead_id = l.id"""


def list_leads(db_path: str, limit: int = 50) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(f"{_SELECT} ORDER BY l.created_at DESC, l.id DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_lead(db_path: str, lead_id: int) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(f"{_SELECT} WHERE l.id = ?", (lead_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_stats(db_path: str) -> dict:
    today = date.today().isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(COALESCE(a.human_priority, a.rule_priority) = 'High' AND l.status != 'Closed') AS high_priority,
                 SUM(l.status IN ('New', 'Reviewed')) AS needs_follow_up,
                 SUM(l.status IN ('New', 'Reviewed') AND a.follow_up_date <= ?) AS due_now,
                 SUM(a.email_status = 'Pending review' AND l.status != 'Closed') AS drafts_pending
               FROM leads l JOIN analyses a ON a.lead_id = l.id""",
            (today,),
        ).fetchone()
    return {k: (row[k] or 0) for k in row.keys()}


def update_status(db_path: str, lead_id: int, status: str) -> None:
    if status not in LEAD_STATUSES:
        raise ValueError("Invalid status")
    with connect(db_path) as conn:
        conn.execute("UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), lead_id))


def save_human_decisions(db_path: str, lead_id: int, status: str, human_priority: str | None,
                         human_next_action: str | None, follow_up_date: str) -> None:
    if status not in LEAD_STATUSES:
        raise ValueError("Invalid status")
    now = _now()
    touched = now if (human_priority or human_next_action) else None
    with connect(db_path) as conn:
        conn.execute("UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, now, lead_id))
        conn.execute(
            """UPDATE analyses SET human_priority = ?, human_next_action = ?, human_updated_at = ?,
                      follow_up_date = ? WHERE lead_id = ?""",
            (human_priority, human_next_action, touched, follow_up_date, lead_id),
        )


def update_email_draft(db_path: str, lead_id: int, subject: str, body: str) -> None:
    """Save a human edit. Editing puts the draft back into review."""
    with connect(db_path) as conn:
        conn.execute(
            """UPDATE analyses SET email_subject = ?, email_body = ?, email_edited = 1,
                      email_status = 'Pending review', email_reviewed_at = NULL
               WHERE lead_id = ?""",
            (subject, body, lead_id),
        )


def set_email_status(db_path: str, lead_id: int, status: str) -> bool:
    """Record a review decision. Returns True if the lead was moved from New to Reviewed."""
    if status not in EMAIL_STATUSES:
        raise ValueError("Invalid email status")
    reviewed_at = None if status == "Pending review" else _now()
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE analyses SET email_status = ?, email_reviewed_at = ? WHERE lead_id = ?",
            (status, reviewed_at, lead_id),
        )
        # A reviewed email means a human has looked at the lead.
        if status != "Pending review":
            cur = conn.execute(
                "UPDATE leads SET status = 'Reviewed', updated_at = ? WHERE id = ? AND status = 'New'",
                (_now(), lead_id),
            )
            return cur.rowcount > 0
    return False
