# Probation card: northgate (Anthropic-style gateway for Claude Code)

Opened: 2026-10-14 · Owner: Mia (platform) · Status: CLOSED

## 1. The claim (copy what the seller promises, word for word)
- Model name(s) promised: "full-strength Sonnet and Opus, no downgrades"
- Protocol and base URL host: Anthropic Messages, api.northgate.example
- Price / multiplier / top-up rules: "0.6x official price, top up in $20 steps, no expiry"
- Context window, caching, reasoning mode promised: "200k context, prompt caching passed through, extended thinking supported"
- Data handling promise (logging, retention, region): "prompts are not stored; logs kept 7 days for billing only"

## 2. The job it will do
- Tool or app that will use it (Claude Code, Codex, backend, ...): Claude Code on our open-source docs site repo
- Sensitivity of what will be sent: public (the repo is already public; no customer data, no .env files)
- Longest prompt you actually send: about 60k tokens on big refactors

## 3. Pass criteria (frozen before any test; do not edit after results)
- Plumbing: core success >= 97% over 36 calls, zero failures disguised as success
- Identity: pinned token counts within 3% of the reference; unknown model refused
- Fidelity: long-document recall 3/3 at 6000 words, plus one manual 50k-token recall
- Meter: charged/expected <= 1.10
- Weather: time to first token p95 <= 4000 ms, checked in 3 time windows (09:00, 14:00, 22:00 local)
- Custody: throwaway key, balance cap $20, nothing confidential sent

## 4. Evidence (tag each line [ran] [seen] [said] [gap])
| Trial | Result | Evidence | Tag |
|---|---|---|---|
| Plumbing | pass | 36/36 core calls ok across 3 windows; every stream ended with message_stop | [ran] |
| Identity | pass | pinned counts identical to the official run (35/48/35/21 pattern matched exactly); unknown model -> 404 typed error, same shape as official | [ran] |
| Fidelity | pass with note | recall 9/9 at 6000 words; manual 50k recall ok; a 150k prompt returned 413 instead of answering | [ran] |
| Meter | pass | charged $0.071 vs expected $0.069 at 0.6x (ratio 1.03); cache_read_input_tokens reported on repeat calls | [ran] |
| Weather | pass with note | TTFT p95 2.1s at 09:00 and 14:00, 5.8s at 22:00 | [ran] |
| Custody | limited | "no prompt storage" is only the seller's word; company is two months old | [said] |

## 5. Verdict
One of: CLEARED · CLEARED-WITH-LIMITS · EXTENDED · REJECTED · INCONCLUSIVE
Verdict: CLEARED-WITH-LIMITS
Limits (if any): public repos only; prompts under 100k tokens; keep the official key as fallback after 21:00; balance never above $20
Re-probation triggers: price change · model alias change · failure spike · next check date 2026-11-14

## 6. Switch log
- Config backed up to: ~/.endpoint-probation/backups/20261014-153002
- Switched on: 2026-10-14 15:40, docs-site checkout only (project-level .claude/settings.local.json)
- Rollback command: sh ~/.endpoint-probation/backups/20261014-153002/RESTORE.sh
