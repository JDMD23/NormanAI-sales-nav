"""SQLite state store for the Warm Path Engine. History is append-preserving:
targets/paths are deactivated, never deleted, so first_seen answers
'when did this relationship become visible'.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "state" / "salesnav.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    notion_page_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    linkedin_url TEXT,
    sn_account_url TEXT,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(notion_page_id),
    name TEXT NOT NULL,
    title TEXT,
    persona TEXT NOT NULL,
    degree INTEGER,
    sn_lead_url TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(company_id, name, persona)
);
CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id),
    via_name TEXT NOT NULL,
    via_sn_url TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(target_id, via_name)
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(notion_page_id),
    at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    note TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_company(conn, notion_page_id: str, name: str, linkedin_url: str | None = None) -> None:
    conn.execute(
        """INSERT INTO companies (notion_page_id, name, linkedin_url) VALUES (?, ?, ?)
           ON CONFLICT(notion_page_id) DO UPDATE SET name=excluded.name,
             linkedin_url=COALESCE(excluded.linkedin_url, companies.linkedin_url)""",
        (notion_page_id, name, linkedin_url),
    )
    conn.commit()


def set_account_url(conn, notion_page_id: str, sn_account_url: str) -> None:
    conn.execute(
        "UPDATE companies SET sn_account_url=?, resolved_at=? WHERE notion_page_id=?",
        (sn_account_url, now_iso(), notion_page_id),
    )
    conn.commit()


def record_target(conn, company_id: str, *, name: str, title: str | None,
                  persona: str, degree: int | None, sn_lead_url: str | None) -> tuple[int, bool]:
    """Upsert a persona target. Returns (target_id, is_new)."""
    ts = now_iso()
    cur = conn.execute(
        "SELECT id FROM targets WHERE company_id=? AND name=? AND persona=?",
        (company_id, name, persona),
    )
    row = cur.fetchone()
    if row:
        conn.execute(
            "UPDATE targets SET title=?, degree=?, sn_lead_url=?, last_seen=?, active=1 WHERE id=?",
            (title, degree, sn_lead_url, ts, row["id"]),
        )
        conn.commit()
        return row["id"], False
    cur = conn.execute(
        """INSERT INTO targets (company_id, name, title, persona, degree, sn_lead_url, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (company_id, name, title, persona, degree, sn_lead_url, ts, ts),
    )
    conn.commit()
    return cur.lastrowid, True


def record_path(conn, target_id: int, *, via_name: str, via_sn_url: str | None) -> bool:
    """Upsert a warm path. Returns True if newly seen."""
    ts = now_iso()
    cur = conn.execute(
        "SELECT id FROM paths WHERE target_id=? AND via_name=?", (target_id, via_name)
    )
    row = cur.fetchone()
    if row:
        conn.execute("UPDATE paths SET last_seen=?, active=1 WHERE id=?", (ts, row["id"]))
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO paths (target_id, via_name, via_sn_url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
        (target_id, via_name, via_sn_url, ts, ts),
    )
    conn.commit()
    return True


def record_scan(conn, company_id: str, outcome: str, note: str = "") -> None:
    conn.execute(
        "INSERT INTO scans (company_id, at, outcome, note) VALUES (?, ?, ?, ?)",
        (company_id, now_iso(), outcome, note),
    )
    conn.commit()


def active_paths_for_company(conn, company_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.name AS target_name, t.title, t.persona, t.degree, t.sn_lead_url,
                  p.via_name, p.via_sn_url, p.first_seen AS path_first_seen
           FROM targets t LEFT JOIN paths p ON p.target_id = t.id AND p.active = 1
           WHERE t.company_id = ? AND t.active = 1
           ORDER BY t.persona, t.degree, t.name""",
        (company_id,),
    ).fetchall()
