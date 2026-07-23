# Sales Nav Warm Path Engine — system brief

Owner: JD. Engineer: Claude Code. Operator (downstream consumer): Norman.
Date: 2026-07-23.

## 1. What JD asked for (source of truth)

> "Pull companies up, look at certain insights… I have personas set up that will tell me who I am connected to that is also connected or shares a connection with my certain persona. I want to write that to Notion, to the company profile — 'you know so-and-so who's connected to the head of talent, head of operations, head of finance, CEO, cofounder.' I want this to be some sort of angler… the system running, mapping out relationships and contacts forming."

Decisions locked in the same exchange:

- **Ingest:** browser scrape of JD's logged-in Sales Nav session (same mechanism as crm-core's LinkedIn lane: AppleScript → JavaScript in real Chrome).
- **Destination:** Norman CRM Core Notion DB (`3a33930e-64f4-8002-ac6b-f5f99d632099`) — write to the existing company profile, not a new DB.
- **Apollo:** helper only — once a persona target is identified, pull their email. Phase 2.
- The system lives against Sales Navigator; it is a standing loop, not a one-shot.

## 2. Objects

| Object | Meaning |
|--------|---------|
| **Company** | A Norman CRM Core row (Notion page). Join key: Notion page ID + LinkedIn company URL. |
| **SN account** | The company's Sales Navigator account page. |
| **Persona target** | A person at the company matching one of JD's saved SN personas. |
| **Warm path** | JD → (shared connection) → persona target. Degree 1 means JD knows the target directly (path is trivial). Degree 2 means one hop: the shared connection is the angle. |
| **Delta** | A change between scans: new persona target (hire), new warm path (relationship formed), path lost. |

## 3. Personas (config/personas.json)

JD's saved Sales Nav personas, priority-ordered: CEO, Cofounder, Head of Finance, Head of Operations, Head of Talent. Config carries title synonyms per persona so parsing can classify when SN's persona chip isn't readable on a given surface. Editing the config is the only step needed to add a persona.

## 4. Pipeline stages

### 4.1 Select
Query Norman CRM Core for candidates:
- `Need Warm Path Sync` checkbox ON (work queue, Need-* discipline), OR
- `--shelf` run over Status ∈ {Prospect, Top Pursuit, Tracking, Engaged} with a staleness cutoff (`Warm Path Checked At` older than cadence).
Batch cap from pace config (default 8 companies/run). Opt-in only — never the whole pipeline.

### 4.2 Resolve SN account
Input: company LinkedIn URL (crm-core already owns this field). Navigate Sales Nav company lookup, confirm identity (name/domain corroboration — website-first rule applies, search is a lead not an answer). Persist `sn_account_url` in state DB so resolve runs once per company.

### 4.3 Persona scan
On the SN account page, read the persona/people module: for each persona, the matching leads — name, title, persona label, connection degree (1st/2nd/3rd), lead URL, TeamLink flag if shown.

### 4.4 Path map
For each 2nd-degree persona target (bounded: top N per persona, default 3): open lead page, read the **shared connections** module — who JD knows that is connected to the target. Persist each as a warm path. 1st-degree targets are themselves the path. 3rd-degree targets are recorded as targets with no path (they become "watch for a path to form").

### 4.5 Notion writeback
Company page updates (properties to be added to the crm-core DB — see § 6):

| Property | Type | Content |
|----------|------|---------|
| `Warm Path Summary` | rich_text | e.g. `CEO: A. Chen (1st) · Head of Talent: R. Patel (2nd via M. Ross) · +2 more` |
| `Warm Paths Count` | number | Active paths (degree 1 counts as 1) |
| `Warm Path Personas` | multi_select | Personas with ≥1 covered target |
| `Warm Path Checked At` | date | Scan stamp |
| `Need Warm Path Sync` | checkbox | Work queue; OFF on success, ON on retry, OFF on park |

Page body: a `Warm Paths` heading + table (target, title, persona, degree, via, SN link, first seen / last seen), replaced idempotently between managed markers. Deltas since last scan listed on top ("NEW: path to Head of Finance via K. Wong").

**Never writes Status. Never touches JD-only shelves. A failed scan writes nothing** — no zeroing, no clearing of prior paths (Unknown ≠ 0).

### 4.6 Re-scan loop
Cadence per shelf (config): Top Pursuit 7d, Engaged 7d, Prospect 14d, Tracking 30d. Runner is manual or launchd-scheduled later — **scheduling is JD's call, never auto-enabled** (crm-core cron red line applies).

## 5. State (state/salesnav.db, SQLite, gitignored)

```
companies(notion_page_id PK, name, linkedin_url, sn_account_url, resolved_at)
targets(id PK, company_id FK, name, title, persona, degree, sn_lead_url, first_seen, last_seen, active)
paths(id PK, target_id FK, via_name, via_sn_url, first_seen, last_seen, active)
scans(id PK, company_id FK, at, outcome, note)
```

History is append-preserving (`active` flag, never delete) so "contacts forming" is answerable: a path's `first_seen` is when the relationship became visible.

## 6. Notion schema additions (one-time, on Norman CRM Core DB)

The five properties in § 4.5. Additive only; no existing property is modified. To be created via Notion API with JD's go-ahead at build time, then mirrored into `config/salesnav.json` propertyMap (same pattern as `config/crm-core.json`).

## 7. Compliance & pacing posture

- JD's own logged-in session, JD's paid Sales Nav seat, JD-triggered runs, human-scale volume (default caps: 8 companies/run, ≤3 lead pages per persona, pauses 5–9s nav / 7–12s between companies with jitter — `config/pace.json`).
- Reads only surfaces Sales Nav itself shows JD. No connection requests, no InMail, no messaging — **nothing outbound, ever, from this repo.**
- Captcha / auth-wall / logged-out detection → lane outcome **retry**, stop the run immediately (same as crm-core LinkedIn lane).

## 8. Apollo (phase 2)

When a persona target is confirmed, `apollo people/match` (name + company domain + title) → work email → written to the Warm Paths page-body table only. Credit-gated with a per-run cap. No sequences, no sends.

## 9. Build plan

| # | Step | Needs |
|---|------|-------|
| 1 | Scaffold: spec, configs, state store, pacing, capture tool | — (this commit) |
| 2 | Live capture session: JD logged into Sales Nav, run `sn_capture.py` on 2–3 known accounts + lead pages | JD at the machine, ~15 min |
| 3 | Parsers from captures: account resolve, persona module, shared-connections module | Step 2 output |
| 4 | Notion writeback + schema add | JD go-ahead on 5 new properties |
| 5 | Pilot: 5 Top Pursuit companies end-to-end, JD reviews Warm Paths sections | Steps 3–4 |
| 6 | Re-scan loop + 48h-digest delta line; Apollo email pull | Pilot sign-off |

## 10. Non-goals

- No outbound (messages, connection requests, InMail) — angle identification only.
- No new CRM. Notion company page remains the single pane.
- No full-pipeline crawls. Opt-in shelves and Need-queue only.
- No scraping beyond what JD's session displays (no profile deep-dumps, no exports of connection lists wholesale).
