# Thin honesty audit — Warm Path SUPPLEMENT (2026-08-12)

Scope: NormanAI-sales-nav as Warm Path **SUPPLEMENT** only. NormanAI-CRMx is
sole SoR. No overnight SN freestyle. No Fit reweight.

## Verdict

| Check | Result |
|-------|--------|
| Writes target CRMx cockpit `3b43930e-64f4-8136-a6ef-c8dfb4ac09a5` | **Pass** (config default + legacy refuse) |
| Does not write Fit / Status (dual-writer A20) | **Pass after fail-closed harden** |
| `schemaReady` honest until `sync_board_schema --apply` | **Pass** (`false` in config; write path gated) |

## Ranked findings

### P0 — Dual-writer A20: Fit/Status must be impossible to PATCH

**Was:** Runtime allowlist + forbidden list already refused `Status` / `Fit*` /
JD human fields on the happy path (`assert_warm_path_write` + tests). Gap: a
mis-mapped `propertyMap` warm-path key could have put a forbidden name into the
*allowlist set*, and `write()` did not re-check `schemaReady` (CLI-only gate).

**Fix (this PR):**
- `assert_warm_path_config()` — fail-closed if any `warmPathWriteKeys` maps to
  Status / Fit* / JD fields.
- `patch_page_properties()` — single page-property write path; requires
  `schemaReady` + allowlist before any Notion PATCH.
- Tests for schema gate, Fit Raw, propertyMap collision, and guarded PATCH.

### P1 — schemaReady honesty until CRMx schema apply

**Was / still true:** `config/salesnav.json` has `"schemaReady": false` with an
explicit note that Warm Path properties must be created via CRMx
`sync_board_schema --apply` on the Mac before flipping the flag. `sn_run.py` /
`sn_agent.py` abort when false.

**Gap fixed:** `sn_notion.write` / `patch_page_properties` now refuse writes when
`schemaReady=false`, so a library caller cannot bypass the CLI gate and invent
properties on an unprepared CRMx board.

**Operator note:** Do not set `schemaReady: true` until the Mac apply has been
run and property names/types match `propertyMap` (LinkedIn URL = `LinkedIn`).

### P2 — SoR / no parallel CRM

**Pass:** Default `notionDatabaseId` is the CRMx cockpit
`3b43930e-64f4-8136-a6ef-c8dfb4ac09a5`. `resolve_database_id()` refuses legacy
crm-core `3a33930e-64f4-8002-ac6b-f5f99d632099` (config or
`SALESNAV_NOTION_DATABASE_ID`). Queries use that resolved DB id.

**Residual (accepted, not fixed here):** Property PATCH is by `page_id`. Normal
runners only obtain ids from CRMx `select()`. An out-of-band call with a legacy
page id could still PATCH that page's Warm Path properties; it still cannot
write Fit/Status. Parent-database verification on every PATCH left out as
heavier than this thin audit.

### P3 — Doc honesty: "unattended" language

**Was:** `sn_run.py` docstring and `docs/spec.md` §10 said the engine "runs
unattended", conflicting with OCR rules / README / non-goals (attended only; no
overnight freestyle).

**Fix:** Wording corrected to attended CLI against JD's logged-in Chrome; §10.1
historical incident kept as past tense without endorsing unattended ops.

## Explicitly out of scope (not done)

- Overnight / freestyle SN automation
- Fit score reweight or any Fit write
- Creating Warm Path properties on the Notion board (Mac / CRMx
  `sync_board_schema --apply`)
- Flipping `schemaReady` to true

## Evidence map

| Claim | Where |
|-------|--------|
| CRMx DB default | `config/salesnav.json` → `notionDatabaseId` |
| Legacy refuse | `scripts/sn_notion.py` → `resolve_database_id` |
| Write allowlist | `warmPathWriteKeys` + `assert_warm_path_write` |
| Fit/Status refuse | `forbiddenWriteProperties` / `forbiddenWritePrefixes` + config collision guard |
| schemaReady false | `config/salesnav.json` + write-path `assert_schema_ready` |
| Regression coverage | `tests/test_regressions.py` (NotionRegressionTests) |
