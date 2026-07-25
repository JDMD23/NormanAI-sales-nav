#!/usr/bin/env python3
"""Warm Path Engine runner — scans companies and writes Notion, unattended.

    python3 scripts/sn_run.py --shelf "Top Pursuit"
    python3 scripts/sn_run.py --shelf Prospect --limit 15
    python3 scripts/sn_run.py --shelf Prospect --min-fit 82
    python3 scripts/sn_run.py --backfill          # rows flagged Need Warm Path Sync
    python3 scripts/sn_run.py --shelf Prospect --dry-run

Requires JD's Chrome open and logged into Sales Navigator. Reads only; the sole
UI write is the optional save-to-list. Stops immediately on an auth wall.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sn_extract  # noqa: E402
import sn_notion  # noqa: E402
from lib import chrome, pace  # noqa: E402

STATE = ROOT.parent / "state"
IDMAP = STATE / "company_ids.json"


def load_ids() -> dict:
    try:
        return json.loads(IDMAP.read_text())
    except Exception:
        return {}


def save_ids(m: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    IDMAP.write_text(json.dumps(m, indent=1, sort_keys=True))


def derive_angles(acct: dict, people: list[dict]) -> list[str]:
    out = []
    if acct.get("spotlight"):
        out.append(f"People: {acct['spotlight']} (SN spotlight)")
    news = [p for p in people if p.get("flag") == "NEW"]
    if len(news) >= 3:
        out.append(f"People: hiring wave — {len(news)} recent hires among decision-makers")
    bits = [b for b in (acct.get("employees") and f"{acct['employees']} ppl",
                        acct.get("location"), acct.get("revenue")) if b]
    if bits:
        out.append(" · ".join(bits))
    return out or ["(no angle surfaced this scan)"]


def derive_moves(people: list[dict]) -> list[str]:
    stamp = date.today().strftime("%b %Y")
    out = []
    for p in people:
        if p.get("flag") == "NEW":
            out.append(f"HIRE · {p['name']} — {p.get('title') or '?'} (seen {stamp})")
        elif p.get("flag") == "UP":
            out.append(f"PROMOTED · {p['name']} — {p.get('title') or '?'} (seen {stamp})")
    return out


def run_loop(args, run_batch) -> int:
    """Batch → rest → repeat, until the queue drains or progress stalls.

    Two stop conditions matter as much as 'queue empty':
      * auth wall    — abort immediately, the session is the scarce resource
      * zero progress — a batch that writes nothing means something is
        systematically broken. Stop and say so rather than spinning through the
        pipeline burning JD's Sales Nav seat on a bug.
    """
    batch_no = 0
    totals = {"ok": 0, "flagged": 0, "parked": 0, "degraded": 0}
    while True:
        batch_no += 1
        print(f"\n{'='*52}\nBATCH {batch_no}\n{'='*52}", flush=True)
        res = run_batch(args, cap=args.batch)
        if res is None:
            print("\nstopped — auth wall")
            return 1
        for k in totals:
            totals[k] += res[k]
        if res["queued"] == 0:
            print(f"\nQUEUE EMPTY after {batch_no - 1} batches")
            break
        if res["ok"] == 0 and res["degraded"] == 0:
            print(f"\nSTOPPED — batch {batch_no} produced no successful writes "
                  f"({res['parked']} parked). Something is systematically wrong; "
                  f"fix before continuing rather than spinning.")
            return 1
        print(f"\nbatch {batch_no}: {res['ok']} written, {res['flagged']} flagged, "
              f"{res['parked']} parked, {res['degraded']} refused"
              f"  |  running total {totals['ok']} written")
        print(f"resting {args.rest}s…", flush=True)
        time.sleep(args.rest)

    print(f"\nLOOP DONE — {totals['ok']} written, {totals['flagged']} flagged, "
          f"{totals['parked']} parked, {totals['degraded']} refused")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shelf", help="Notion Status to scan (Top Pursuit / Prospect)")
    ap.add_argument("--backfill", action="store_true",
                    help="rescan rows already flagged Need Warm Path Sync")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-fit", type=float, default=None,
                    help="skip below this Fit Score (sub-scale companies yield little)")
    ap.add_argument("--dry-run", action="store_true", help="scan and print, write nothing")
    ap.add_argument("--loop", action="store_true",
                    help="keep running batches until the queue drains")
    ap.add_argument("--batch", type=int, default=15, help="companies per batch with --loop")
    ap.add_argument("--rest", type=int, default=180,
                    help="seconds between batches with --loop (session hygiene)")
    args = ap.parse_args()

    if not args.shelf and not args.backfill:
        ap.error("need --shelf or --backfill")
    if not json.loads((ROOT.parent / "config" / "salesnav.json").read_text()).get("schemaReady"):
        print("salesnav.json schemaReady=false — Notion properties not confirmed. Aborting.")
        return 2

    try:
        token = sn_notion.nc.load_token()
    except SystemExit:
        print("NOTION_TOKEN not found."); return 2

    if args.loop:
        return run_loop(args, lambda a, cap: run_batch(a, token, cap))
    res = run_batch(args, token,
                    args.limit if args.limit is not None else pace.batch_limit())
    return 0 if res is not None else 1


def run_batch(args, token, cap: int):
    """One batch. Returns counts, or None if an auth wall stopped us.

    The queue is re-pulled from Notion every call, so --loop naturally picks up
    rows that got flagged earlier in the same run.
    """
    if args.backfill:
        rows = [r for r in sn_notion.select("Prospect", unscanned_only=False, token=token)
                if r["needs_sync"]]
        rows += [r for r in sn_notion.select("Top Pursuit", unscanned_only=False, token=token)
                 if r["needs_sync"]]
    else:
        rows = sn_notion.select(args.shelf, unscanned_only=True, token=token)

    if args.min_fit is not None:
        rows = [r for r in rows if (r["fit"] or 0) >= args.min_fit]
    rows = rows[:cap]

    print(f"{len(rows)} companies queued\n")
    ids = load_ids()
    ok = flagged = parked = degraded = 0

    for i, row in enumerate(rows, 1):
        name = row["name"]
        print(f"[{i}/{len(rows)}] {name} (fit {row['fit']})", flush=True)
        try:
            acct = sn_extract.scan_company(name, ids.get(name))
        except chrome.DependencyError as exc:
            print(f"  ! {exc}\n  stopping run (retry later)")
            save_ids(ids)
            return None
        if acct.get("error") == "ambiguous_identity":
            cands = ", ".join(f"{n} ({i})" for n, i in acct.get("candidates", [])[:3])
            print(f"  parked — ambiguous name; paste the right id into "
                  f"state/company_ids.json. candidates: {cands}")
            parked += 1
            continue
        if acct.get("error") or not acct.get("people"):
            print("  parked — no Sales Nav match or no persona data")
            parked += 1
            continue

        ids[name] = acct["company_id"]
        people = acct["people"]
        if args.dry_run:
            for p in people[:8]:
                via = " ← " + ", ".join(p.get("via", [])) if p.get("via") else ""
                print(f"    {p['name']} · {p.get('title')} · {p.get('degree')}{via}")
        else:
            needs = sn_notion.write(row["page_id"], people,
                                    derive_angles(acct, people),
                                    derive_moves(people), token=token)
            if needs == "degraded":
                degraded += 1
                print("  REFUSED — thin scan would have erased existing paths; left intact")
                pace.pause_between_companies()
                continue
            flagged += bool(needs)
            print(f"  written{' · flagged for name resolution' if needs else ''}")
        ok += 1
        save_ids(ids)
        pace.pause_between_companies()

    print(f"\ndone — {ok} scanned, {flagged} need name resolution, "
          f"{parked} parked, {degraded} refused (would have erased data)")
    return {"ok": ok, "flagged": flagged, "parked": parked,
            "degraded": degraded, "queued": len(rows)}


if __name__ == "__main__":
    sys.exit(main())
