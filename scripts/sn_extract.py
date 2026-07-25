#!/usr/bin/env python3
"""Sales Navigator extractors — the proven JS payloads, headless.

Every function here runs ONE JavaScript call in JD's logged-in Chrome and returns
structured data. No screenshots, no clicking. Selectors verified live 2026-07-23
across 80+ company scans.

Key discovery: the "who are the mutual connections" view has a stable URL that can
be constructed directly from a lead id — no popover clicking, and it returns EVERY
mutual by name (the hover popover truncates at 2).
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from lib import chrome, pace

SALES = "https://www.linkedin.com/sales"


# --------------------------------------------------------------------------- JS

_JS_SEARCH_RESULTS = """
(()=>{const r=[];const seen=new Set();
for(const a of document.querySelectorAll('a[href*="/sales/company/"]')){
 const n=a.innerText.trim().split('\\n')[0];if(!n||seen.has(n))continue;seen.add(n);
 const box=a.closest('li')||a.parentElement.parentElement.parentElement.parentElement;
 const t=(box?box.innerText:'').replace(/\\n+/g,' | ').slice(0,160);
 r.push({name:n,id:a.getAttribute('href').split('?')[0].replace('/sales/company/',''),blurb:t})}
return JSON.stringify(r.slice(0,8))})()
"""

_JS_ACCOUNT = """
(()=>{const out={};const b=document.body.innerText;
out.employees=(b.match(/([\\d.,]+K?\\+?)\\s*employees/)||[])[1]||null;
out.location=(b.match(/\\n([A-Z][a-zA-Z .]+,\\s*[A-Za-z ]+,\\s*United States)\\n/)||[])[1]||null;
out.revenue=(b.match(/(\\$[\\dKMB.]+\\s*-\\s*\\$[\\dKMB.]+)\\s*in revenue/)||[])[1]||null;
out.spotlight=(b.match(/\\d+ senior leadership hires?/)||[])[0]||null;
const seen=new Set();out.people=[];
for(const a of document.querySelectorAll('a[href*="/sales/lead/"]')){
 const n=a.innerText.trim().split('\\n')[0];
 if(!n||n.length<2||seen.has(n)||/^View/.test(n))continue;seen.add(n);
 const card=a.closest('li')||a.parentElement.parentElement.parentElement;
 const txt=card?card.innerText:'';
 const deg=(txt.match(/\\b(1st|2nd|3rd)\\b/)||[])[1]||null;
 const mut=(txt.match(/(\\d+)\\s*mutual connection/)||[])[1]||null;
 const flag=/Recently hired/.test(txt)?'NEW':(/Recently promoted/.test(txt)?'UP':null);
 const past=/Past colleague/.test(txt)||null;
 const follows=/Follows your company/.test(txt)||null;
 const lines=txt.split('\\n').map(s=>s.trim()).filter(Boolean);
 const ni=lines.findIndex(l=>l.startsWith(n));let title=null;
 for(let i=ni+1;i<Math.min(ni+4,lines.length);i++){
  if(!/^(1st|2nd|3rd)$/.test(lines[i])&&!/mutual|Recently|recent post|Save|Follows|Past colleague/.test(lines[i])){title=lines[i];break}}
 out.people.push({name:n,title:title,degree:deg,mutuals:mut?parseInt(mut):0,
   flag:flag,past_colleague:past,follows_company:follows,
   lead_id:a.getAttribute('href').split('?')[0].split(',')[0].replace('/sales/lead/','')})}
return JSON.stringify(out)})()
"""

_JS_NAMES = """
(()=>{const s=new Set();
for(const a of document.querySelectorAll('a[href*="/sales/lead/"]')){
 const n=a.innerText.trim().split('\\n')[0];if(n&&n.length>1&&!/^View/.test(n))s.add(n)}
return JSON.stringify([...s])})()
"""


def _js(expr: str):
    raw = chrome.run_js(" ".join(expr.split()))
    try:
        return json.loads(raw)
    except Exception:
        return None


# ----------------------------------------------------------------------- public

def search_company(name: str) -> list[dict]:
    """Company search → candidate accounts. spellCorrection OFF (it silently
    redirects to the wrong company — verified trap)."""
    q = quote(f'(spellCorrectionEnabled:false,keywords:"{name}")', safe='')
    chrome.open_url(f"{SALES}/search/company?query={q}")
    pace.pause_navigation()
    chrome.assert_logged_in()
    return _js(_JS_SEARCH_RESULTS) or []


# Scroll to the Relationship Explorer heading itself rather than a fixed offset —
# page furniture varies (Account IQ present or absent, banners, alert strips), so
# a hard-coded 900px lands nowhere near it on some accounts and the lazy load
# never fires. This was the cause of the 2026-07-23 data-loss regression.
_JS_SCROLL = """
(()=>{const h=[...document.querySelectorAll('h2,h3,div,span')]
 .find(e=>/Relationship explorer/i.test(e.textContent||'')&&e.children.length<4);
 if(h){h.scrollIntoView({block:'center'});return 'target'}
 window.scrollTo(0,Math.min(1200,document.body.scrollHeight/3));return 'fallback'})()
"""

# Cheap readiness probe: are the persona cards actually painted yet?
_JS_READY = """
(()=>{const n=document.querySelectorAll('a[href*="/sales/lead/"]').length;
const g=document.body.innerText.match(/\\b(1st|2nd|3rd)\\b/g);
return JSON.stringify({leads:n,graded:(g||[]).length})})()
"""


def read_account(company_id: str, attempts: int = 4) -> dict:
    """Account page → employees/location/revenue + every persona person with
    title, degree, mutual COUNT and lead id.

    The Relationship Explorer renders lazily: it needs a scroll and a beat before
    the persona cards (and their mutual-connection chips) exist in the DOM. Read
    too early and you get an empty or degraded person list — which previously
    overwrote good data. Scroll, wait, and retry until the cards carry degree
    info; give up honestly rather than return a thin result."""
    chrome.open_url(f"{SALES}/company/{company_id}")
    pace.pause_navigation()
    chrome.assert_logged_in()

    best = {}
    for i in range(attempts):
        chrome.run_js(" ".join(_JS_SCROLL.split()))
        # Escalating patience: later attempts wait longer rather than re-poking
        # at the same cadence. Cheap when the page is fast, decisive when it lags.
        for _ in range(i + 1):
            pace.pause_navigation()

        ready = _js(" ".join(_JS_READY.split())) or {}
        if not ready.get("graded"):
            continue  # cards still not painted — scroll and wait again

        acct = _js(_JS_ACCOUNT) or {}
        graded = [p for p in (acct.get("people") or []) if p.get("degree")]
        if len(graded) > len(best.get("people") or []):
            best = acct
            best["people"] = graded
        if graded and any(p.get("mutuals") for p in graded):
            return best

    if best.get("people"):
        return best
    # Honest failure. The caller must NOT write this — see sn_notion.write's guard.
    return {"people": [], "thin": True}


def mutual_names(lead_id: str) -> list[str]:
    """THE unlock: build the mutual-connections lead search directly from a lead
    id and read every mutual by name. Replaces clicking the popover (which caps
    at 2 visible names)."""
    inner = (
        "(filters:List("
        "(type:CONNECTION_OF,values:List((id:%s,selectionType:INCLUDED))),"
        "(type:RELATIONSHIP,values:List((id:F,selectionType:INCLUDED)))"
        "))" % lead_id
    )
    chrome.open_url(f"{SALES}/search/people?query={quote(inner, safe='')}")
    pace.pause_between_lead_pages()
    return _js(_JS_NAMES) or []


def _employees(blurb: str) -> int | None:
    """Headcount out of a search-result blurb ('… 158 employees on LinkedIn')."""
    m = re.search(r"([\d,.]+)(K\+?)?\s*employees", blurb or "")
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(n * 1000) if m.group(2) else int(n)


def _norm(s: str) -> str:
    keep = "".join(c for c in s.casefold() if c.isalnum() or c == " ")
    drop = {"inc", "llc", "ltd", "co", "corp", "technologies", "technology",
            "labs", "ai", "the", "health", "software", "group"}
    return " ".join(w for w in keep.split() if w not in drop).strip()


def pick_match(name: str, hits: list[dict]) -> dict | None:
    """Choose a search result only when it plausibly IS the company.

    Taking hits[0] blindly poisoned the identity memo on 2026-07-23 — "Finch
    Legal" resolved to an unrelated Finch, "PointOne" to a random account. Wrong
    ids then produced thin scans that the write guard had to refuse. Better to
    park an ambiguous name and let a human paste the id than to silently scan
    the wrong company.
    """
    want = _norm(name)
    if not want:
        return None
    exact = [h for h in hits if _norm(h["name"]) == want]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Name-identical candidates are the common case, not the exotic one:
        # "Concourse" vs "The Concourse", "Scribe" vs "scribe", "Gamma" vs
        # "GAMMA". Parking all of these strands most of the tail. Break the tie
        # on headcount, which is what actually distinguishes the operating
        # company from a dormant shell — but only on a decisive margin, and only
        # when the winner is big enough to be a real prospect.
        sized = [(_employees(h.get("blurb", "")), h) for h in exact]
        sized = [(n, h) for n, h in sized if n is not None]
        if len(sized) >= 2:
            sized.sort(key=lambda t: -t[0])
            top, second = sized[0], sized[1]
            if top[0] >= 10 and top[0] >= second[0] * 3:
                return top[1]
        return None  # genuinely ambiguous — needs a human
    # Prefix, not substring: "Sesame" must not match "Open Sesame AI" — leading
    # words change the entity. Trailing words usually don't ("Hex" / "Hex Inc").
    pre = [h for h in hits
           if _norm(h["name"]).startswith(want) or want.startswith(_norm(h["name"]))]
    return pre[0] if len(pre) == 1 else None


def scan_company(name: str, company_id: str | None = None, max_targets: int = 6) -> dict:
    """Full company scan: resolve → read account → resolve mutuals by name.

    Returns {company_id, employees, location, revenue, spotlight, people[...]}
    where each person that had a mutual count now carries a `via` name list.
    Identity is the caller's job — pass company_id when known (search results are
    ambiguous for common names; persist the id after the first successful scan).
    """
    if company_id is None:
        hits = search_company(name)
        if not hits:
            return {"error": "no_search_results", "name": name}
        match = pick_match(name, hits)
        if match is None:
            return {"error": "ambiguous_identity", "name": name,
                    "candidates": [(h["name"], h["id"]) for h in hits[:5]]}
        company_id = match["id"]

    acct = read_account(company_id)
    acct["company_id"] = company_id
    people = acct.get("people", [])

    # Resolve mutuals for the targets most likely to matter, highest count first.
    ranked = sorted(
        [p for p in people if p.get("mutuals")],
        key=lambda p: -p["mutuals"],
    )[:max_targets]
    for p in ranked:
        p["via"] = mutual_names(p["lead_id"])
    return acct


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("usage: sn_extract.py <company name> [company_id]")
    out = scan_company(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(out, indent=2))
