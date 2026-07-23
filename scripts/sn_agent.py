#!/usr/bin/env python3
"""Warm Path Engine orchestrator — skeleton.

Stages (spec §4): select → resolve → persona scan → path map → writeback.

The three parse_* functions are intentionally NotImplemented until selectors are
developed from live captures (spec §9 step 2–3). Everything around them —
pacing, state, lane outcomes, auth-wall stops — is real and final.

Run (once parsers land):
  python3 scripts/sn_agent.py --needing            # Need Warm Path Sync queue
  python3 scripts/sn_agent.py --shelf "Top Pursuit" --limit 5
  python3 scripts/sn_agent.py --company <notion-page-id>  # single company
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import chrome, pace, state  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "salesnav.json").read_text())
_PERSONAS_CFG = json.loads((ROOT / "config" / "personas.json").read_text())
PERSONAS = _PERSONAS_CFG["personas"]
MAX_LEAD_PAGES_PER_PERSONA = int(_PERSONAS_CFG.get("maxLeadPagesPerPersona", 3))


@dataclass
class PersonaTarget:
    name: str
    title: str | None
    persona: str
    degree: int | None
    sn_lead_url: str | None
    shared_connections: list[dict] = field(default_factory=list)  # {via_name, via_sn_url}


# ---------------------------------------------------------------- parsers (TODO)

def parse_account_search(body_text: str, body_html: str, company_name: str, website_domain: str | None):
    """Sales Nav company search results → confirmed sn_account_url or None.
    Identity must corroborate (name/domain) — search is a lead, not an answer."""
    raise NotImplementedError("pending live captures — spec §9 step 3")


def parse_persona_module(body_text: str, body_html: str) -> list[PersonaTarget]:
    """SN account page persona/people module → persona targets with degrees."""
    raise NotImplementedError("pending live captures — spec §9 step 3")


def parse_shared_connections(body_text: str, body_html: str) -> list[dict]:
    """SN lead page shared-connections module → [{via_name, via_sn_url}]."""
    raise NotImplementedError("pending live captures — spec §9 step 3")


# ---------------------------------------------------------------- stages

def scan_company(conn, company: dict) -> str:
    """Run resolve → persona scan → path map for one company. Returns lane outcome:
    success | retry | park. Failed scans write nothing (Unknown ≠ 0)."""
    page_id = company["notion_page_id"]
    try:
        row = conn.execute(
            "SELECT sn_account_url FROM companies WHERE notion_page_id=?", (page_id,)
        ).fetchone()
        account_url = row["sn_account_url"] if row else None

        if not account_url:
            # resolve stage — navigate SN search, corroborate, persist
            raise NotImplementedError("resolve stage pending parsers")

        chrome.open_url(account_url)
        pace.pause_navigation()
        chrome.assert_logged_in()

        targets = parse_persona_module(chrome.body_text(), chrome.body_html())
        opened_per_persona: dict[str, int] = {}
        for target in targets:
            tid, _is_new = state.record_target(
                conn, page_id, name=target.name, title=target.title,
                persona=target.persona, degree=target.degree, sn_lead_url=target.sn_lead_url,
            )
            if target.degree == 2 and target.sn_lead_url:
                opened = opened_per_persona.get(target.persona, 0)
                if opened >= MAX_LEAD_PAGES_PER_PERSONA:
                    continue
                opened_per_persona[target.persona] = opened + 1
                pace.pause_between_lead_pages()
                chrome.open_url(target.sn_lead_url)
                pace.pause_navigation()
                chrome.assert_logged_in()
                for path in parse_shared_connections(chrome.body_text(), chrome.body_html()):
                    state.record_path(conn, tid, via_name=path["via_name"], via_sn_url=path.get("via_sn_url"))

        state.record_scan(conn, page_id, "success")
        return "success"
    except chrome.DependencyError as exc:
        state.record_scan(conn, page_id, "retry", str(exc))
        return "retry"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--needing", action="store_true", help="Need Warm Path Sync queue")
    ap.add_argument("--shelf", help="Scan a Status shelf (e.g. 'Top Pursuit')")
    ap.add_argument("--company", help="Single Notion page id")
    ap.add_argument("--limit", type=int, default=pace.batch_limit())
    args = ap.parse_args()

    if not CONFIG.get("schemaReady"):
        print("config/salesnav.json schemaReady=false — Notion Warm Path properties not created yet (spec §6). Aborting.")
        return 2

    # select stage: query Notion for candidates (pending writeback module)
    raise NotImplementedError("select + writeback stages pending — spec §9 step 4")


if __name__ == "__main__":
    sys.exit(main())
