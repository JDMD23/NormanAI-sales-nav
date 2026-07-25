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


_JS_SCROLL = "(()=>{window.scrollTo(0,900);return '1'})()"


def read_account(company_id: str, attempts: int = 3) -> dict:
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
        chrome.run_js(_JS_SCROLL)
        pace.pause_navigation()
        acct = _js(_JS_ACCOUNT) or {}
        people = acct.get("people") or []
        graded = [p for p in people if p.get("degree")]
        if len(graded) > len(best.get("people") or []):
            best = acct
            best["people"] = graded
        # good enough: we have graded people and at least one mutual count,
        # or we have graded people and this is the last attempt
        if graded and (any(p.get("mutuals") for p in graded) or i == attempts - 1):
            return best
    return best or {"people": []}


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
        company_id = hits[0]["id"]

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
