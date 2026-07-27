#!/usr/bin/env python3
"""Notion writeback in format v3 — stacked Connectivity blocks.

Applies the connection registry (core > inner ⭐ > ok > unrated > skip) and the
hard rule: if skip-removal empties a target's mutual list, write `no usable path`
and flag Need Warm Path Sync. Never leave a dead path looking live.
"""

from __future__ import annotations

import json
import sys
from datetime import date as calendar_date
from pathlib import Path
from urllib.parse import quote

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
BODY_HEADING = "Warm Paths"
BODY_START = "managed by sales-nav"
BODY_END = "end of sales-nav managed section"


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


def write(page_id: str, people: list[dict], angles: list[str],
          moves: list[str] | None = None, date: str | None = None,
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
    if thin:
        # `thin` means the extractor never obtained a trustworthy answer. It is
        # never safe to mark the row checked or replace any previously stored
        # data, including a direct (1st-degree) path that lacks the text "via".
        return "degraded"
    tok = token or nc.load_token()
    poc, conn, needs = build_rows(people)
    date = date or calendar_date.today().isoformat()

    new_txt = "".join(s["text"]["content"] for s in conn)
    if "No warm path found" in new_txt:
        # A confirmed no-path is an ANSWER, not an open question. Leaving the
        # flag on would re-queue this row on every loop pass and the loop would
        # never drain. Re-checking later is the rescan cadence's job.
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
    write_body(page_id, people, date, tok)
    return needs


def _para(rich):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich}}


def _bullet(rich):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rich}}


def _block_text(block: dict) -> str:
    rich = (block.get(block.get("type", "")) or {}).get("rich_text", [])
    return "".join(t.get("plain_text", t.get("text", {}).get("content", "")) for t in rich)


def _children(page_id: str, token: str) -> list[dict]:
    """Read every top-level child, not just Notion's first 100-block page."""
    out, cursor = [], None
    while True:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={quote(cursor, safe='')}"
        res = nc.notion("GET", url, token=token)
        out.extend(res.get("results", []))
        if not res.get("has_more"):
            return out
        cursor = res.get("next_cursor")
        if not cursor:
            return out


def _managed_span(kids: list[dict]) -> tuple[int, int] | None:
    """Locate only blocks owned by this script; return inclusive indexes.

    New sections carry an explicit end marker. Legacy sections did not, so their
    generated bullet/summary shapes are recognised conservatively and scanning
    stops at the first unrecognised block. This prevents a refresh from deleting
    unrelated notes that happen to follow Warm Paths.
    """
    for heading_at, block in enumerate(kids):
        if (block.get("type") != "heading_2"
                or _block_text(block).strip() != BODY_HEADING):
            continue
        managed_at = heading_at + 1
        if managed_at >= len(kids) or not _block_text(kids[managed_at]).startswith(BODY_START):
            continue
        start = (heading_at - 1
                 if heading_at and kids[heading_at - 1].get("type") == "divider"
                 else heading_at)
        for end in range(managed_at + 1, len(kids)):
            if _block_text(kids[end]).strip() == BODY_END:
                return start, end

        # Legacy migration: include only blocks whose exact shapes this writer
        # emitted. A normal user paragraph or bullet terminates the managed span.
        end = managed_at
        for at in range(managed_at + 1, len(kids)):
            kind = kids[at].get("type")
            text = _block_text(kids[at])
            generated_bullet = (
                kind == "bulleted_list_item"
                and (" — you're connected; go direct." in text
                     or " — via " in text
                     or " — no usable path" in text)
            )
            generated_summary = (
                kind == "paragraph"
                and (text.startswith("Watch list (no path yet): ")
                     or text.startswith("No warm path at this scan."))
            )
            if not (generated_bullet or generated_summary):
                break
            end = at
        return start, end
    return None


def write_body(page_id: str, people: list[dict], date: str, token: str) -> None:
    """Managed 'Warm Paths' section in the page body.

    The columns are for scanning; this is for when JD opens the row. Automating
    the writeback originally dropped it — 98 machine-scanned rows ended up with
    no detail layer at all while the hand-written ones had it. Rewrites only
    between its own markers; anything else on the page is never touched.
    """
    kids = _children(page_id, token)
    span = _managed_span(kids)
    if span is not None:
        start, end = span
        for b in kids[start:end + 1]:
            nc.notion("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}", token=token)

    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [seg(BODY_HEADING)]}},
        _para([seg(f"{BODY_START} · last scan {date}", italic=True, color="gray")]),
    ]
    reachable = [p for p in people if p.get("via") or p.get("degree") == "1st"]
    for p in reachable:
        line = [seg(p["name"], LEAD + p["lead_id"], bold=True),
                seg(f" — {p.get('title') or '?'} ({p.get('degree') or '?'})")]
        if p.get("degree") == "1st":
            line.append(seg(" — you're connected; go direct."))
        else:
            txt, _ = render_via(p.get("via") or [])
            line.append(seg(" — " + txt + "."))
        extra = []
        if p.get("past_colleague"):
            extra.append("past colleague")
        if p.get("follows_company"):
            extra.append("follows your company")
        if extra:
            line.append(seg(" " + ", ".join(extra).capitalize() + "."))
        blocks.append(_bullet(line))

    watch = [p for p in people if p not in reachable]
    if watch:
        blocks.append(_para(
            [seg("Watch list (no path yet): ", bold=True),
             seg(" · ".join(f"{p['name']} — {p.get('title') or '?'}" for p in watch[:10]))]))
    if not reachable:
        blocks.append(_para([seg("No warm path at this scan. Every persona match is "
                                 "3rd degree or shows no shared connections.")]))
    blocks.append(_para([seg(BODY_END, italic=True, color="gray")]))
    nc.notion("PATCH", f"https://api.notion.com/v1/blocks/{page_id}/children",
              {"children": blocks}, token=token)


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
