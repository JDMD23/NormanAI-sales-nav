# Sales Nav Warm Path Engine — system brief

Owner: JD. Engineer: Claude Code. Operator (downstream consumer): Norman.
Date: 2026-07-23 (rev 2 — post-brainstorm).

## 1. What JD asked for (source of truth)

> "Any company tagged Prospect or Top Pursuit in my Notion CRM Core pipeline should automatically be added to Navigator as a company on some sort of list… have a job running that clicks a company — the main page has About, Relationship Explorer, Relationship Map, Growth Insights… the personas say Workplace POC: head of people, office manager, founder, COO… click any mutual connections to these people in the persona, and tell me who I'm connected with that's connected to those people. I'm trying to find angles on connectivity — a warm email, or reach out to a good connection for an introduction. Account alerts posts recent news about the company that could also be an angle for a cold email."

Readout format (JD, rev 2): two display properties on the company row —
**Workplace POC** listing the persona people one per line ("easy to read, not one
long sentence"), and **Connectivity** mapping each target to who JD knows:
"the CEO is X, and A and B are connected to him." JD eyeballs it and judges
the angle.

Decisions locked:

- **Ingest:** browser scrape of JD's logged-in Chrome (AppleScript, same mechanism as crm-core's LinkedIn lane).
- **Personas:** a single Sales Nav persona, **Workplace POC**, bundling decision-maker titles (`config/personas.json`; verify exact SN setup during the capture session).
- **Destination:** company page in Norman CRM Core Notion DB. People stay company-scoped in v1; the SQLite store keeps the people graph so a dedicated People DB can be promoted in v2 without rework.
- **Apollo:** helper only — email pull for confirmed targets. Later phase.
- Standing loop, JD-triggered; scheduling only with JD's explicit approval.

## 2. Capabilities & phases

| Phase | Capability | Notes |
|-------|-----------|-------|
| 1 | **List sync** — Notion shelves → SN account lists | Top Pursuit → "Norman — Top Pursuits", Prospect → "Norman — Prospects". Saving accounts is what turns on SN's own alert engine, feeding phase 2 cheaply. |
| 1 | **Warm path mapping** — persona targets + mutual connections → Notion writeback | The core. Includes intro-node ranking. |
| 1 | **Connection registry** — JD-curated tiers (`config/connections.json`), 5 levels: **core** > **inner** (⭐, tops lines) > **ok** (shown, unstarred) > **unrated** > **skip** (removed entirely from Connectivity). When skip removal empties a target's mutual list, write `no usable path` and flag `Need Warm Path Sync` — never leave a dead path looking live. | Replaces frequency-based leaderboard (JD 2026-07-23). Frequency = tiebreaker within tier only. |
| 1 | **New-hire tripwire** — `NEW HIRE ·` prefix on recently-hired POCs; people-move alert triggers same-day rescan | 4/10 pilot companies had one. First-90-days window. |
| 2 | **Angles** — account alerts (news, hires, funding) harvested from the SN feed/list alert views | Confirmed in (JD). e.g. Omni $120M Series C. Written as angle entries; input for Norman's outreach drafting. |
| 2 | **Digest** — per run: "N new warm paths, M new angles, new connectors to rate" | Likely the daily-use surface. |
| — (skipped) | Draft-the-intro-ask | JD declined 2026-07-23. |
| 3 (parked) | **Growth insights** — headcount distribution, new hires from SN growth tab | Field-ownership conflict: crm-core's LinkedIn lane owns headcount fields. Decide then: new SN-specific fields, or sales-nav feeds the existing lane. Do not double-own fields. |

## 3. Objects

| Object | Meaning |
|--------|---------|
| **Company** | A Norman CRM Core row. Join key: Notion page ID + LinkedIn company URL. |
| **SN account** | The company's Sales Navigator account page. |
| **Persona target** | Person at the company matching Workplace POC. |
| **Warm path** | JD → (mutual connection) → target. Degree 1: JD knows the target. Degree 2: the mutual is the angle. Degree 3: target recorded, "no path yet" — watch for one to form. |
| **Intro node** | A 1st-degree JD connection ranked by how many targets/companies they unlock. Mutual with three POCs across two Top Pursuits = highest-value ask. |
| **Angle** | An account alert worth writing about (funding, leadership hire, headcount jump, news). |
| **Delta** | Change between scans: new target (hire), new path (relationship formed), path lost, new angle. |

## 4. Pipeline (phase 1)

```text
Select (Notion shelves) → List sync (SN) → Account scan (Relationship Explorer personas)
  → Mutual connections (2nd-degree targets) → Writeback (Notion) → Re-scan loop
```

### 4.1 Select
Companies with Status ∈ {Top Pursuit, Prospect} (JD-only shelves — read, never written), plus `Need Warm Path Sync` ON as a manual queue. Batch caps from `config/pace.json`.

### 4.2 List sync
Ensure each selected company is saved to its shelf's SN list (`salesNavLists` in config). Resolve company → SN account via LinkedIn URL, corroborate identity (website-first rule), save. Companies leaving the shelves get removed from lists on a later pass (not v1-blocking).

### 4.3 Account scan
On the account page, read the Relationship Explorer / persona module for Workplace POC matches: name, title, degree, lead URL.

### 4.4 Mutual connections
For 2nd-degree targets (cap: `maxLeadPagesPerPersona`), open the target's mutual-connections view; record each mutual as a warm path.

### 4.5 Writeback
Company page, four properties (§6):

`Workplace POC` (rich_text, one per line):
```
Jane Chen — CEO (1st)
Marc Roth — COO (2nd)
Ana Diaz — Head of People (2nd)
Tom Ellis — Office Manager (3rd)
```

`Connectivity` (rich_text, per-target path map). Format v3 — STACKED BLOCKS (JD 2026-07-23 late):
one block per target, never one long line. Line 1 = flags + name (linked, bold) + title + degree;
line 2 = indented `    ↳ via` + every mutual by name; blank line between targets:
```
NEW · ⭐ Nick Zhao · Head of Finance · 1st
    ↳ you're connected — go direct

Dan Mishin · Founder & CEO · 2nd
    ↳ via ⭐Nick Zhao · ⭐Shensi Ding · ⭐Jon Cohen · Zach Goldstein
```
Connectivity is self-sufficient (carries title + degree) so JD reads one column, not two.
Format v2 rules below still hold — names always, counts never replace names:
**every mutual is named — counts never replace names** (`+N` allowed only after ≥2 names,
and flags the row `Need Warm Path Sync` for name resolution). Arrow shorthand, one line per target:
```
⭐ Nick Zhao — you're connected
Dan Mishin ← ⭐Nick Zhao · ⭐Shensi Ding · ⭐Jon Cohen · Zach Goldstein
Tara Neuman ← Mike Shebat · Marilynn Joyner · +1
```
Roster lines: `NEW · ⭐ Name · Title · deg [· ex-CBRE | · follows you]`. Each fact appears in
exactly ONE field; long-form detail (companies, dates, watch list, cautions) lives in the managed
page-body "Warm Paths" section. Scanner rule: expand every 2nd-degree target's mutuals fully by name
(View-all navigation when the popover truncates). Original prose rules below kept for history:
**every name is a clickable link** (target → SN lead URL; mutual → their profile URL),
**always full names**, inner-circle mutuals starred and listed first, lines ordered
by angle strength (1st-degree targets, then ⭐ paths, then rest; "no path yet"
people stay out of the column — page body only). New hires prefixed `NEW HIRE ·`,
fresh paths `NEW ·`:
```
Jane Chen (CEO): you're connected
NEW HIRE · Ana Diaz (Head of People): ⭐ via Dan Katz
Marc Roth (COO): via Mike Ross, Sarah Lee
```

Plus `Warm Path Checked At` (date) and `Need Warm Path Sync` (checkbox, lane queue).
Page body: managed `Warm Paths` section — full table with SN links, first-seen dates, deltas on top.

**Never writes Status. A failed scan writes nothing — never blanks previously written paths (Unknown ≠ 0).**

### 4.6 Re-scan loop
Cadence: Top Pursuit 7d, Prospect 14d (`rescanCadenceDays`). Deltas surface in the run digest (phase 2) and page-body section.

## 5. State (state/salesnav.db, SQLite, gitignored)

```
companies(notion_page_id PK, name, linkedin_url, sn_account_url, resolved_at)
targets(id PK, company_id FK, name, title, persona, degree, sn_lead_url, first_seen, last_seen, active)
paths(id PK, target_id FK, via_name, via_sn_url, first_seen, last_seen, active)
scans(id PK, company_id FK, at, outcome, note)
```

Append-preserving (`active` flag, never delete): `first_seen` answers "when did this relationship become visible." Intro-node ranking is a query over `paths` grouped by `via_name`.

## 6. Notion schema additions (one-time, on Norman CRM Core DB)

| Property | Type | Who reads it |
|----------|------|--------------|
| `Workplace POC` | rich_text | JD (display) |
| `Connectivity` | rich_text | JD (display) |
| `Angles` | rich_text | JD — up to 3 typed lines (Funding / People / Product / Expansion), strongest first |
| `People Moves` | rich_text | JD — hires/promotions/departures feed, `HIRE ·` / `PROMOTED ·` / `LEFT ·` prefixes; promotions and departures come from scan-to-scan diffs |
| `Warm Path Checked At` | date | machine |
| `Need Warm Path Sync` | checkbox | machine (queue) |

Additive only. Created via Notion API with JD's go-ahead, then `schemaReady: true`.

## 7. Compliance & pacing posture

- JD's own logged-in session and paid SN seat; JD-triggered runs; human pacing with jitter (`config/pace.json`); low caps.
- Reads only what SN shows JD. List-save clicks are the only UI writes.
- **Nothing outbound, ever, from this repo** — no connection requests, InMail, or messages. Angle identification only; drafts live with Norman.
- Captcha / auth wall / logged-out → outcome **retry**, run stops immediately.

## 8. Build plan

| # | Step | Needs |
|---|------|-------|
| 1 | Scaffold (done, rev 1) | — |
| 2 | Live capture session: account page w/ Relationship Explorer, a 2nd-degree lead's mutual connections view, list-save flow, list/alerts view | JD logged into SN, ~15 min |
| 3 | Parsers from captures | Step 2 |
| 4 | Notion writeback + 4 properties | JD go-ahead |
| 5 | Pilot: 5 Top Pursuit companies end-to-end; JD reviews the two columns | 3–4 |
| 6 | List sync automation + re-scan loop | Pilot sign-off |
| 7 | Phase 2: angles + digest; Apollo email pull | 6 |

## 9. Non-goals

- No outbound. No new CRM. No full-pipeline crawls (Top Pursuit + Prospect + explicit queue only).
- No scraping beyond what JD's session displays; no wholesale connection exports.
- No headcount field writes until the phase-3 ownership decision (crm-core LinkedIn lane owns those today).

## 10. Running it (built 2026-07-23)

The engine now runs unattended from the command line against JD's logged-in Chrome.

```bash
python3 scripts/sn_run.py --shelf "Top Pursuit"
python3 scripts/sn_run.py --shelf Prospect --min-fit 82 --limit 15
python3 scripts/sn_run.py --backfill        # rows flagged Need Warm Path Sync
python3 scripts/sn_run.py --shelf Prospect --dry-run
```

Modules:
- `scripts/sn_extract.py` — three verified JS payloads. `search_company` (spell-
  correction OFF; it silently redirects to the wrong company), `read_account`
  (one call returns every persona person with title/degree/mutual-count/lead id),
  and `mutual_names` — the unlock: the mutual-connections view has a stable URL
  built directly from a lead id, returning EVERY mutual by name. The hover popover
  caps at 2; this does not.
- `scripts/sn_notion.py` — format v3 writeback + registry tiers. `tier_of` tries
  the full name before the pre-parenthetical form (registry contains names like
  "Kirsten (Kiki) C."). Empty Connectivity is never written blank.
- `scripts/sn_run.py` — selection, pacing, identity memo (`state/company_ids.json`,
  so a company resolves once), auth-wall abort, angle/people-move derivation.

The work queue lives in Notion, not on disk: `Need Warm Path Sync` and
`Warm Path Checked At` are the state. Nothing to lose if the machine resets.

**Known limits.** Identity resolution takes the first search hit when no id is
memoised — fine for distinctive names, wrong for common ones (Artemis, Rebar,
Sesame all mis-resolved during the manual sweep). Seed `state/company_ids.json`
or pass the id for those. Angles are derived from spotlight/headcount only; the
richer Account IQ narrative still needs a human or a later pass.

### 10.1 Anti-erase guard (learned the hard way, 2026-07-23)

The first unattended backfill run **overwrote verified paths with "no warm path
found"** on Hex Technologies and Braintrust. Cause: the Relationship Explorer
renders lazily, so `read_account` was reading the DOM before the persona cards
(and their mutual chips) existed. Two fixes, both required:

1. `read_account` now scrolls, waits, and retries up to 3× until the cards carry
   degree info — keeping the best result across attempts.
2. `sn_notion.write` refuses the write and returns `"degraded"` when the new
   Connectivity would be the empty placeholder but the existing cell already
   contains `↳ via`. The runner reports it as REFUSED and leaves the row intact.

This is the spec's own Unknown ≠ 0 rule applied to this lane: **a thin scan writes
nothing.** Any future extractor change must keep guard (2) — it is the only thing
standing between a rendering hiccup and silent data loss across the pipeline.

### 10.2 Loop mode

```bash
python3 scripts/sn_run.py --backfill --loop --batch 15 --rest 180
python3 scripts/sn_run.py --shelf Prospect --loop --batch 15 --min-fit 75
```

Batch → rest → repeat, re-pulling the queue from Notion each batch (so rows
flagged mid-run get picked up automatically). Three stop conditions:

| Stop | Why |
|------|-----|
| queue empty | the goal |
| auth wall | the session is the scarce resource — abort, don't push through |
| **zero writes in a batch** | anti-spin. A batch that writes nothing means a systematic bug; stop and say so rather than burning the seat on it. |

`--rest` exists for session hygiene, not politeness theatre: continuous
back-to-back scanning for an hour looks nothing like a human using the product.

### 10.3 Lazy-render fix (second pass)

The first hardening still produced thin reads on ~1 in 3 backfills. Cause: it
scrolled a fixed 900px, but page furniture varies per account so that often
lands nowhere near the Relationship Explorer. Now it scrolls **to the element**,
runs a cheap readiness probe (`_JS_READY`) to confirm degree badges exist before
extracting, escalates the wait on each retry, and tries 4×. Verified on the exact
rows that had been refused: Finch Legal went 0 → 6 targets with mutuals.

### 10.4 Identity guard (the bug that mattered most)

`scan_company` used to take `hits[0]` from company search. That poisoned
`state/company_ids.json`: **Finch Legal** memoised to an unrelated "Finch",
**PointOne** to id 28003, **Radial** and **Peregrine** likewise. Every later scan
then read the *wrong company*.

It did not corrupt Notion — the §10.1 anti-erase guard refused all five writes
because the wrong-company scans came back thin. Two independent guards, and the
second one caught what the first missed. Keep both.

Fixes:
- `pick_match()` accepts a search hit only on an exact normalised name match, or
  a **prefix** match in either direction. Prefix, not substring: "Sesame" must
  not match "Open Sesame AI" — leading words change the entity, trailing ones
  usually don't. Multiple equal candidates (several "Radial"s) → park.
- Unresolvable names return `ambiguous_identity` with candidate ids, and the
  runner prints them so a human can paste the right one into
  `state/company_ids.json`.
- The map was rebuilt from the 47 ids verified by eye during the manual sweep
  (parsed out of `docs/sweep-2026-07-23.md`).

Lesson: a heuristic that is right 90% of the time is a *data-integrity* bug when
its output is cached and reused.

### 10.5 "No path" is an answer, not an unknown

Two different situations produce an empty Connectivity, and conflating them
breaks the loop in opposite directions:

| | meaning | behaviour |
|---|---|---|
| `thin=True` | page never rendered, or we read the wrong company | **refuse** the write, keep existing data |
| `thin=False` | page rendered; targets genuinely share no connections | **write it, clear the flag** |

Getting this wrong the first way destroys data (§10.1). Getting it wrong the
second way means every genuinely-path-less company is refused and re-queued on
every pass — the loop never drains. `Need Warm Path Sync` means *needs another
look*, not *has no path*; re-checking a confirmed no-path is the rescan
cadence's job.

### 10.6 The spin: progress is NEW rows, not writes

The first real `--loop` run went 34 batches and reported "209 written". It had
actually written the **same 6 rows 29 times** and parked the same 5 rows 34
times — ~370 redundant Sales Nav requests before the zero-progress guard tripped.

`--backfill` selects `needs_sync == True`. Two states survive a perfectly good
scan and leave the flag on, so the queue refilled with the rows just processed:

1. a target whose only mutuals were skip-listed → `no usable path`
2. a parked row (ambiguous identity / no persona data) — parking never clears
   the flag

Fixes, both needed:
- **`render_via`**: a path that exists only through skip-listed people returns
  `needs_rescan=False`. Rescanning cannot change it — only JD re-rating someone
  or a new connection forming can, and that is the rescan cadence's job.
- **`run_loop`** keeps a `seen` set of page ids and excludes them from later
  batches *in the same run*. This is the belt-and-braces guard: whatever future
  reason leaves a row flagged, the loop can no longer chew it twice.

The zero-progress guard was necessary but not sufficient — it only fires when a
batch writes *nothing*, and this batch "wrote" six rows every pass. Measure
progress in rows newly touched.

### 10.7 Identity, second correction: too strict is also a bug

After §10.4 the guard swung the other way and parked an entire batch of 15. The
cause: `_norm` collapses case and strips filler words, so name-identical
candidates are the *common* case, not the exotic one — "Concourse" vs "The
Concourse", "Scribe" vs "scribe", "Tetrix" vs "TETRIX". Two "exact" matches meant
park, so most of the tail was unreachable.

Tiebreak on **headcount from the search blurb**, which is what actually separates
the operating company from a dormant shell — but only on a decisive margin:
winner must have ≥10 employees AND ≥3× the runner-up. Below that margin it still
parks (two similar-sized "Radial"s remain a human decision).

Both failure directions cost real money: too loose scanned the wrong company and
poisoned the cache; too strict stranded the tail. The margin is the knob.

### 10.8 The detail layer went missing when the writeback was automated

The hand-run pilot wrote two layers per company: the properties (for scanning a
board view) and a **Warm Paths section in the page body** (for when JD actually
opens the row). When the writeback was automated, only the properties were
ported. Nobody noticed for 169 companies, because the columns looked right —
the audit found **98 rows with properties but no body at all**.

`sn_notion.write_body()` restores it, and owns exactly one section: it finds its
own `Warm Paths` H2 (plus the divider above it), deletes from there, and appends
fresh. Anything else on the page is never touched, so hand-written notes on a
company page survive a rescan.

Lesson: a manual→automated port needs a diff of the *output*, not just a reading
of the code. The code was correct at everything it did; it just did less.

### 10.9 Headcount is not an angle

`derive_angles()` originally emitted the SN spotlight plus size/location/revenue.
That is a description of a company, not a reason to call one. The best insights
in the manual pass all came from **Account IQ** — a panel the extractor never
read: "expanding its operations in the United States, particularly in New York
City" (ElevenLabs), "$120M Series C" (Omni). One of those is a leasing trigger;
`1K+ ppl` is not.

`_JS_ACCOUNT` now lifts `Strategic priorities` and any funding sentence, and
angles order best-signal-first: funding → priorities → people moves → workplace
seat on staff → size. Size stays last as context, capped at four lines total.

Added with it: a **workplace seat** signal. A company with a Head of Workplace or
Head of Ops on staff has someone whose job is the office — a better demand tell
than headcount.

### 10.10 A JS comment silently deleted every scan

Payloads are collapsed to one line (`" ".join(expr.split())`) before AppleScript
hands them to Chrome. A `//` comment added to `_JS_ACCOUNT` while writing §10.9
therefore commented out **the entire rest of the payload**, including the closing
braces. Every scan died on a syntax error.

Fixed at the source: `_js()` strips `//` line comments before collapsing. The
trap is invisible at the point of use — the comment looks fine in the file — and
the next person to document a selector inline would hit it again.

### 10.11 "Funding" that was not funding

The first funding regex was `(raised|raising|Series [A-F]|funding round|IPO)`
against the whole page text. It produced confident nonsense on the first refresh
batch: Mercor got "raising concerns about data security", Navan got "IPO
Disclosures and Shareholder Risk". Both are risk-section prose. An angle that is
wrong is worse than no angle — JD would open a call with it.

Now a funding match must pair an event verb (raised/closed/secured/announced)
with an actual **amount or round letter**, and an explicit blocklist kills
"raising concerns/questions/awareness". No match falls through to the strategic
priority, which is the better angle anyway. Verified: both false positives gone,
Hex's "$70 million Series C" and Manifest's "$60M from Kleiner Perkins" kept.

Caught by eyeballing the actual written output of batch 1 rather than the run
counters — which said 15/15 written, and were right.
