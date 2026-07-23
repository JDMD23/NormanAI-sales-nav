# Sales Nav — Warm Path Engine

Relationship-mapping sibling to [Norman CRM Core](https://github.com/JDMD23/normanai-workspace). For each pipeline company, this system reads its LinkedIn **Sales Navigator** account page from JD's logged-in Chrome session, runs JD's saved **personas** (CEO, Cofounder, Head of Talent, Head of Operations, Head of Finance), maps **who JD knows that is connected to those persona targets**, and writes the warm paths back to the company's profile in the Norman CRM Core Notion DB.

It is the "angle engine": it answers *who can get me into this company, through whom* — and keeps re-scanning so new paths surface as relationships form.

## Pipeline

```text
Select companies (crm-core shelves) → Resolve SN account → Persona scan → Path map → Notion writeback → Re-scan loop
```

| Stage | What it does |
|-------|--------------|
| Select | Pull companies from Norman CRM Core (`Need Warm Path Sync` ON, or shelf-tagged) |
| Resolve | Company LinkedIn URL → Sales Nav account page |
| Persona scan | Read persona matches on the account: name, title, persona, connection degree |
| Path map | For 2nd-degree targets: which shared connections link JD to the target |
| Writeback | `Warm Path Summary` + page-body Warm Paths section on the Notion company page |
| Re-scan | Cadence re-check on active shelves; deltas (new path, new persona hire) flagged |

Phase 2: Apollo email pull for identified persona targets (email only — no outbound from this repo, ever).

## Inherited discipline (from crm-core)

- **Never writes Status.** This is an enrich-style lane; only crm-core's score agent routes status.
- **Unknown ≠ 0.** A failed scan writes nothing; it never erases previously found paths.
- **Human pace.** Real Chrome, real session, deliberate pauses + jitter (`config/pace.json`). Never sub-second bursts. Low daily volume, opt-in selection only.
- **success / retry / park** lane outcomes, `Need Warm Path Sync` checkbox as the work queue.
- **Drafts only.** This system identifies angles. It never sends anything.

## Layout

```text
config/    personas, pacing, Notion writeback map
docs/      spec.md — full system brief
scripts/   sn_capture.py (page capture tool), sn_agent.py (orchestrator), lib/
state/     SQLite path history + page captures (gitignored)
```

## Status

Scaffold. Parsers pend selector development against a live Sales Nav session — see `docs/spec.md` § Build plan.
