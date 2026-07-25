#!/usr/bin/env python3
"""Run digest — the daily-use surface.

    python3 scripts/sn_digest.py              # full digest
    python3 scripts/sn_digest.py --intros     # just the intro-ask leaderboard
    python3 scripts/sn_digest.py --md         # markdown, paste anywhere

Reads Notion (the source of truth) and answers three questions:
  1. Who should I ask for intros this week?     (intro nodes, ranked)
  2. What's newly reachable?                    (1st-degree + gold-connect paths)
  3. What's stale or broken?                    (no usable path, unresolved, unscanned)

Never sends anything. Read-only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sn_notion as N  # noqa: E402

VIA_RE = re.compile(r"↳\s*via\s*(.+)")
PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def norm(name: str) -> str:
    """Collapse 'Shensi Ding (Merge)' and 'Shensi Ding' to one person. Mutual
    names were captured with and without an employer suffix during the manual
    sweep; without this the leaderboard double-counts."""
    return PAREN_RE.sub("", name.replace("⭐", "")).strip()


def harvest(token):
    """-> rows[] with parsed paths"""
    out = []
    for shelf in ("Top Pursuit", "Prospect"):
        for r in N.select(shelf, unscanned_only=False, token=token):
            pg = N.nc.notion("GET", f"https://api.notion.com/v1/pages/{r['page_id']}",
                             token=token)
            p = pg["properties"]
            conn = "".join(t["plain_text"] for t in
                           (p.get(N.PROPS["connectivity"]) or {}).get("rich_text", []))
            angles = "".join(t["plain_text"] for t in
                             (p.get(N.PROPS["angles"]) or {}).get("rich_text", []))
            moves = "".join(t["plain_text"] for t in
                            (p.get(N.PROPS["peopleMoves"]) or {}).get("rich_text", []))
            scanned = bool((p.get(N.PROPS["warmPathCheckedAt"]) or {}).get("date"))
            blocks = [b for b in conn.split("\n\n") if b.strip()]
            paths, direct, dead = [], [], 0
            for b in blocks:
                head = b.split("\n")[0].strip()
                target = re.sub(r"^(NEW|UP|PROMOTED|NEW HIRE)\s*·\s*", "", head)
                target = target.split(" · ")[0].replace("⭐", "").strip()
                if "you're connected" in b:
                    direct.append(target)
                elif "no usable path" in b or "No warm path" in b:
                    dead += 1
                else:
                    m = VIA_RE.search(b)
                    if m:
                        for v in m.group(1).split("·"):
                            v = v.strip()
                            if v and not v.startswith("+"):
                                paths.append((norm(v), target))
            out.append({**r, "shelf": shelf, "scanned": scanned, "paths": paths,
                        "direct": direct, "dead": dead, "angles": angles, "moves": moves})
    return out


def digest(rows, md=False):
    L = []
    B = (lambda s: f"**{s}**") if md else (lambda s: s)
    H = (lambda s: f"\n## {s}\n") if md else (lambda s: f"\n{'='*4} {s} {'='*4}")

    scanned = [r for r in rows if r["scanned"]]
    L.append(f"{len(scanned)} of {len(rows)} in-scope companies enriched")

    # 1. intro leaderboard
    node = defaultdict(list)
    for r in scanned:
        for via, target in r["paths"]:
            node[via].append((r["name"], target, r["fit"]))
    ranked = sorted(node.items(), key=lambda kv: -len({c for c, _, _ in kv[1]}))
    L.append(H("Ask these people for intros"))
    for name, hits in ranked[:12]:
        cos = sorted({c for c, _, _ in hits}, key=lambda c: -next(
            f or 0 for cc, _, f in hits if cc == c))
        tier = N.tier_of(name)
        mark = "⭐ " if tier in ("core", "inner") else ("   " if tier == "ok" else " ? ")
        L.append(f"{mark}{B(name)} — {len(cos)} companies: {', '.join(cos[:6])}"
                 + (f" +{len(cos)-6}" if len(cos) > 6 else ""))
        if tier == "unrated":
            L.append("      (unrated — worth a solid/skip call)")

    # 2. direct reach
    L.append(H("You already know someone inside"))
    for r in sorted([r for r in scanned if r["direct"]], key=lambda r: -(r["fit"] or 0)):
        L.append(f"   {B(r['name'])} ({r['fit']}) — {', '.join(r['direct'])}")

    # 3. gold-connect coverage
    L.append(H("Reachable through a gold connect"))
    gold = []
    for r in scanned:
        g = sorted({v for v, _ in r["paths"] if N.tier_of(v) in ("core", "inner")})
        if g:
            gold.append((r, g))
    for r, g in sorted(gold, key=lambda x: -(x[0]["fit"] or 0))[:15]:
        L.append(f"   {B(r['name'])} ({r['fit']}) — via {', '.join(g[:4])}")

    # 4. problems
    dead = [r for r in scanned if r["dead"]]
    unres = [r for r in scanned if r["needs_sync"]]
    unscanned = [r for r in rows if not r["scanned"]]
    L.append(H("Needs attention"))
    L.append(f"   {len(dead)} companies have a target with no usable path")
    if dead:
        L.append("      " + ", ".join(f"{r['name']}" for r in
                                      sorted(dead, key=lambda r: -(r['fit'] or 0))[:8]))
    L.append(f"   {len(unres)} rows flagged for name resolution — run: sn_run.py --backfill")
    L.append(f"   {len(unscanned)} unscanned — run: sn_run.py --shelf Prospect --min-fit 82")

    # 5. movement
    hires = Counter()
    for r in scanned:
        for line in r["moves"].split("\n"):
            if line.startswith("HIRE"):
                hires[r["name"]] += 1
    hot = [c for c, n in hires.most_common(8) if n >= 3]
    if hot:
        L.append(H("Hiring waves (3+ decision-maker hires)"))
        L.append("   " + ", ".join(hot))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--md", action="store_true", help="markdown output")
    ap.add_argument("--intros", action="store_true", help="only the intro leaderboard")
    args = ap.parse_args()
    tok = N.nc.load_token()
    rows = harvest(tok)
    text = digest(rows, md=args.md)
    if args.intros:
        text = text.split("You already know someone inside")[0]
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
