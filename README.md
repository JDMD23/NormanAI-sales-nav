# Sales Nav — Warm Path Engine

Warm Path **SUPPLEMENT** to [NormanAI-CRMx](https://github.com/JDMD23/NormanAI-CRMx) (sole system of record). For each pipeline company on the CRMx cockpit Notion board, this system reads its LinkedIn **Sales Navigator** account page from JD's logged-in Chrome session, runs JD's saved **personas** (CEO, Cofounder, Head of Talent, Head of Operations, Head of Finance), maps **who JD knows that is connected to those persona targets**, and writes **only Warm Path fields** back to the company row.

It is the "angle engine": it answers *who can get me into this company, through whom* — and keeps re-scanning so new paths surface as relationships form.

## Pipeline

```text
Select companies (CRMx shelves) → Resolve SN account → Persona scan → Path map → Notion Warm Path writeback → Re-scan loop
```

| Stage | What it does |
|-------|--------------|
| Select | Pull companies from CRMx cockpit (`Need Warm Path Sync` ON, or Status shelf — Status is read-only) |
| Resolve | Company LinkedIn URL → Sales Nav account page |
| Persona scan | Read persona matches on the account: name, title, persona, connection degree |
| Path map | For 2nd-degree targets: which shared connections link JD to the target |
| Writeback | Warm Path properties + optional page-body `Warm Paths` section — never Status / Fit* / JD human fields |
| Re-scan | Cadence re-check on active shelves; deltas (new path, new persona hire) flagged |

Phase 2: Apollo email pull for identified persona targets (email only — no outbound from this repo, ever).

## Field ownership

Writes **only**:

- `Workplace POC`, `Connectivity`, `Angles`, `People Moves` (rich_text)
- `Warm Path Checked At` (date), `Need Warm Path Sync` (checkbox)

**Never writes** `Status`, any `Fit*` property, or JD human fields (`Relationship Notes`, `Current Angle`, `Last Touched`, `Re-check`). Default Notion database is the CRMx cockpit `3b43930e-64f4-8136-a6ef-c8dfb4ac09a5` (`SALESNAV_NOTION_DATABASE_ID` override). Legacy crm-core DB `3a33930e-…` is refused.

## Discipline

- **Unknown ≠ 0.** A failed / thin scan writes nothing; it never erases previously found paths. Missing Fit is not coerced to 0.
- **Human pace.** Real Chrome, real session, deliberate pauses + jitter (`config/pace.json`). `dailyCompanyCap` enforced. Attended runs only — no overnight unattended SN.
- **success / retry / park** lane outcomes, `Need Warm Path Sync` checkbox as the work queue.
- **Drafts only.** This system identifies angles. It never sends anything.

## Layout

```text
config/    personas, pacing, Notion writeback map (CRMx board id)
docs/      spec.md — full system brief + ownership
scripts/   sn_run.py, sn_notion.py, sn_extract.py, lib/
state/     SQLite path history + page captures (gitignored)
```

## Migration (before first write)

1. On the Mac, in NormanAI-CRMx: run `sync_board_schema --apply` so Warm Path properties exist on the cockpit board (ADR 0017).
2. Confirm property names/types match `config/salesnav.json`.
3. Set `schemaReady: true` in `config/salesnav.json`.
4. Run an attended dry-run: `python3 scripts/sn_run.py --shelf Prospect --dry-run`.
