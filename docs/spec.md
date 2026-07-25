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
