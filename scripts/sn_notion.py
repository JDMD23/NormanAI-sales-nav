#!/usr/bin/env python3
"""Notion writeback in format v3 — stacked Connectivity blocks.

Applies the connection registry (core > inner ⭐ > ok > unrated > skip) and the
hard rule: if skip-removal empties a target's mutual list, write `no usable path`
and flag Need Warm Path Sync. Never leave a dead path looking live.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRM = Path.home() / "Projects" / "NormanAI-crm-core"

# crm-core ships its own `lib` package; load notion_client by path so it does not
# collide with this repo's scripts/lib.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location(
    "crmcore_notion_client", CRM / "scripts" / "lib" / "notion_client.py")
nc = _ilu.module_from_spec(_spec)
sys.modules["crmcore_notion_client"] = nc
_spec.loader.exec_module(nc)

CONFIG = json.loads((ROOT / "config" / "salesnav.json").read_text())
REG = json.loads((ROOT / "config" / "connections.json").read_text())
PROPS = CONFIG["propertyMap"]
DB = CONFIG["notionDatabaseId"]
LEAD = "https://www.linkedin.com/sales/lead/"


def _names(tier):
    return {e["name"].casefold() for e in REG.get(tier, []) if e.get("name")}


CORE, INNER, OK, SKIP = _names("core"), _names("inner"), _names("ok"), _names("skip")


def tier_of(name: str) -> str:
    """Registry lookup. Tries the full name first — several registry entries
    legitimately contain parentheses (e.g. "Kirsten (Kiki) C.") — then falls back
    to the pre-parenthetical form for entries written as "Name (Company)"."""
    full = name.strip().casefold()
    short = name.split(" (")[0].strip().casefold()
    for n in (full, short):
        if n in SKIP:
            return "skip"
        if n in CORE:
            return "core"
        if n in INNER:
            return "inner"
        if n in OK:
            return "ok"
    return "unrated"


def seg(text, url=None, bold=False, italic=False, color=None):
    t = {"type": "text", "text": {"content": text}}
    ann = {}
    if url:
        t["text"]["link"] = {"url": url}
    if bold:
        ann["bold"] = True
    if italic:
        ann["italic"] = True
    if color:
        ann["color"] = color
    if ann:
        t["annotations"] = ann
    return t


def render_via(via: list[str]) -> tuple[str, bool]:
    """Apply registry tiers. Returns (text, needs_rescan)."""
    kept = []
    dropped = False
    for name in via:
        t = tier_of(name)
        if t == "skip":
            dropped = True
            continue
        kept.append(("⭐" + name) if t in ("core", "inner") else name)
    if not kept:
        # A path that exists only through skip-listed people is a definitive
        # ANSWER: rescanning cannot change it, only JD re-rating someone or a new
        # connection forming can. Flagging it re-queues the row on every loop
        # pass forever (this burned ~370 redundant scans on 2026-07-23).
        if dropped:
            return ("no usable path — skip-listed mutuals removed", False)
        return ("no usable path", True)
    # gold first, then the rest, order otherwise preserved
    kept.sort(key=lambda x: 0 if x.startswith("⭐") else 1)
    return ("via " + " · ".join(kept), False)


def build_rows(people: list[dict]) -> tuple[list, list, bool]:
    """-> (workplace_poc_rich, connectivity_rich, needs_sync)"""
    poc, conn, needs = [], [], False
    for i, p in enumerate(people):
        name, title = p["name"], (p.get("title") or "")
        deg, flag = p.get("degree"), p.get("flag")
        star = "⭐ " if tier_of(name) in ("core", "inner") else ""
        extra = []
        if p.get("past_colleague"):
            extra.append("ex-colleague")
        if p.get("follows_company"):
            extra.append("follows you")
        tail = " · " + title if title else ""
        if deg:
            tail += f" · {deg}"
        if extra:
            tail += " · " + " · ".join(extra)

        if i:
            poc.append(seg("\n"))
        if flag:
            poc.append(seg(f"{flag} · "))
        if star:
            poc.append(seg(star))
        poc.append(seg(name, LEAD + p["lead_id"], bold=True))
        poc.append(seg(tail))

    live = [p for p in people if p.get("via") or p.get("degree") == "1st"]
    for i, p in enumerate(live):
        name, title, deg = p["name"], (p.get("title") or ""), p.get("degree")
        if i:
            conn.append(seg("\n\n"))
        if p.get("flag"):
            conn.append(seg(f"{p['flag']} · "))
        if tier_of(name) in ("core", "inner"):
            conn.append(seg("⭐ "))
        conn.append(seg(name, LEAD + p["lead_id"], bold=True))
        t = " · " + title if title else ""
        if deg:
            t += f" · {deg}"
        conn.append(seg(t))
        if deg == "1st":
            conn.append(seg("\n    ↳ you're connected — go direct"))
        else:
            txt, flag_it = render_via(p.get("via") or [])
            needs = needs or flag_it
            conn.append(seg("\n    ↳ " + txt))

    if not conn:
        # Never leave the column blank — say so, and queue a rescan.
        conn = [seg("No warm path found this scan — every persona match is 3rd "
                    "degree or shows no shared connections. Watch for one to form.")]
        needs = True
    return poc, conn, needs


def read_existing(page_id: str, token: str) -> str:
    pg = nc.notion("GET", f"https://api.notion.com/v1/pages/{page_id}", token=token)
    return "".join(t["plain_text"] for t in
                   (pg["properties"].get(PROPS["connectivity"]) or {}).get("rich_text", []))


def write(page_id: str, people: list[dict], angles: list[str],
          moves: list[str] | None = None, date: str = "2026-07-23",
          token: str | None = None, thin: bool = False) -> bool | str:
    """Returns needs_sync, or the string 'degraded' if the write was REFUSED.

    Unknown != 0 — but only when it is genuinely *unknown*. Two different things
    produce an empty Connectivity and conflating them is a bug either way:

      thin=True   the page never rendered, or we read the wrong company. We do
                  not know the answer. Refuse; keep whatever is already there.
      thin=False  the page rendered fine and the targets genuinely have no shared
                  connections. That IS the answer — write it and clear the flag.
                  Otherwise the row is refused and re-queued on every loop pass,
                  forever, and the loop never drains.
    """
    tok = token or nc.load_token()
    poc, conn, needs = build_rows(people)

    new_txt = "".join(s["text"]["content"] for s in conn)
    if "No warm path found" in new_txt:
        if thin:
            prev = read_existing(page_id, tok)
            if "↳ via" in prev:
                return "degraded"
        else:
            # A confirmed no-path is an ANSWER, not an open question. Leaving the
            # flag on would re-queue this row on every loop pass and the loop
            # would never drain. Re-checking later is the rescan cadence's job.
            needs = False
    props = {
        PROPS["workplacePoc"]: {"rich_text": poc[:100]},
        PROPS["connectivity"]: {"rich_text": conn[:100]},
        PROPS["angles"]: {"rich_text": [seg("\n".join(angles))]},
        PROPS["warmPathCheckedAt"]: {"date": {"start": date}},
        PROPS["needWarmPathSync"]: {"checkbox": needs},
    }
    if moves:
        props[PROPS["peopleMoves"]] = {"rich_text": [seg("\n".join(moves))]}
    nc.notion("PATCH", f"https://api.notion.com/v1/pages/{page_id}",
              {"properties": props}, token=tok)
    return needs


def select(status: str, unscanned_only: bool = True, token: str | None = None) -> list[dict]:
    """Pull work from Notion — the queue rebuilds itself, no local state needed."""
    tok = token or nc.load_token()
    rows, cursor = [], None
    while True:
        body = {"filter": {"property": PROPS["status"], "select": {"equals": status}},
                "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = nc.notion("POST", f"https://api.notion.com/v1/databases/{DB}/query",
                        body, token=tok)
        rows += res["results"]
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]

    out = []
    for r in rows:
        p = r["properties"]
        done = bool((p.get(PROPS["warmPathCheckedAt"]) or {}).get("date"))
        if unscanned_only and done:
            continue
        out.append({
            "page_id": r["id"],
            "name": "".join(t["plain_text"] for t in p[PROPS["company"]]["title"]),
            "fit": (p.get("Fit Score") or {}).get("number"),
            "linkedin": (p.get(PROPS["linkedinUrl"]) or {}).get("url"),
            "needs_sync": bool((p.get(PROPS["needWarmPathSync"]) or {}).get("checkbox")),
        })
    out.sort(key=lambda x: (x["fit"] is None, -(x["fit"] or 0)))
    return out
