# OpenCodeReview (GitHub Action)

PR auto-review via [alibaba/open-code-review](https://github.com/alibaba/open-code-review) `@v1.9.1` (workflow: `.github/workflows/ocr-review.yml`). Warm Path rules live in `.opencodereview/rule.json`.

## Required secrets and variables

Configure under **Settings → Secrets and variables → Actions** (from the official OCR GitHub Actions example):

| Kind | Name | Required | Description |
|------|------|----------|-------------|
| Secret | `OCR_LLM_URL` | Yes | LLM API endpoint URL |
| Secret | `OCR_LLM_AUTH_TOKEN` | Yes | LLM auth token (mapped to `OCR_LLM_TOKEN`) |
| Variable | `OCR_LLM_MODEL` | Yes | Model name |
| Variable | `OCR_LLM_USE_ANTHROPIC` | Yes | `true` for Anthropic Claude, `false` for OpenAI-compatible |

`GITHUB_TOKEN` is provided by Actions (`pull-requests: write`).

## Triggers

- `pull_request_target`: opened / synchronize / reopened
- PR comment starting with `/open-code-review` or `@open-code-review` (MEMBER / OWNER / COLLABORATOR only)

## Warm Path review focus

Reviews should flag violations of: CRMx Notion DB only; Warm Path write allowlist; no Status / Fit* / JD human fields; attended SN + `dailyCompanyCap`; Unknown ≠ 0; no overnight freestyle.
