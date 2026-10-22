# Endpoint Probation

**English** · [简体中文](README.zh-CN.md)

> Every AI endpoint starts on probation. Trust is earned with evidence you ran yourself — not with a price list, a screenshot, or the model telling you its name.

**Endpoint Probation** is an agent skill for Claude Code, Codex, Cursor and other coding agents. It decides whether an AI API endpoint — a cheap relay, a reseller, a team gateway, an aggregator, a self-hosted proxy, or an official model alias that suddenly feels different — deserves to carry real work, and it switches your tools over only with a backup and a one-line rollback.

It comes with `probation.py`, a dependency-free Python helper that runs a fixed probe battery against the candidate and a trusted reference, flags failures, reconciles the bill, lints the probation card and backs up agent configuration. A built-in `selftest` rehearses everything against two local fake endpoints, so you can see what each kind of cheating looks like before spending a cent.

## Why

From the outside every endpoint looks the same: a base URL, a key, a model name. Behind it, any of these can be happening:

- a `200 OK` whose stream carries a rate-limit error, which your client shows as the model's answer;
- the flagship name on the label, a cheaper model behind it — especially on long or expensive requests;
- the start of long context silently trimmed, so your agent forgets files it just read;
- a hidden multiplier, padded token counts, or a cache discount the relay keeps;
- fine at 10:00, unusable at the evening peak; gone with your balance next week;
- prompts, code and keys passing through an operator you know nothing about.

Most people judge all of that by "it answered my hello". This skill replaces that with a card, six trials and one verdict.

## Features

- **Frozen criteria.** Pass thresholds are written from the job (tool, sensitivity, longest prompt, working hours) before any test runs; edits after results start a new probation.
- **Six trials.** Plumbing · Identity · Fidelity · Meter · Weather · Custody — each with a clear question and a clear deciding signal.
- **Reference-based identity.** Pinned English, Chinese, code and mixed-symbol texts compare prompt-token counts with the official endpoint; unknown-model and limit errors are compared too. "Ask it who it is" is explicitly not evidence.
- **Honest statistics.** Success rates with Wilson intervals, Fisher exact test for candidate vs reference, p50/p95 time to first token, longest in-stream stall.
- **Evidence tags.** Every result is `[ran]`, `[seen]`, `[said]` or `[gap]`; the card linter refuses a clearance resting on `[gap]`, or identity and billing resting on `[said]`.
- **Five verdicts.** CLEARED · CLEARED-WITH-LIMITS · EXTENDED · REJECTED · INCONCLUSIVE, with written limits and re-probation triggers.
- **Safe switch.** Backs up Claude Code, Codex, Gemini CLI, OpenCode, Aider, Continue and Cursor config files with a `RESTORE.sh`, and recommends the narrowest scope (project settings, Codex profiles).
- **Parole.** A repeatable "did it get dumber?" protocol: fixed task, equal attempt budgets, every sample kept, intervals compared.
- **Bilingual.** Full English and Chinese skill text; `report`, `bill` and `card` speak both (`--lang zh`).

## Installation

The skill is the folder containing `SKILL.md` (English) and `SKILL.zh-CN.md` (Chinese). Clone the whole repository so `scripts/` and `examples/` come with it.

**Claude Code**

```bash
git clone https://github.com/fangdididi/endpoint-probation.git ~/.claude/skills/endpoint-probation
```

**Codex / agents that read `~/.agents/skills`**

```bash
git clone https://github.com/fangdididi/endpoint-probation.git ~/.agents/skills/endpoint-probation
```

**Cursor** (project skills folder)

```bash
git clone https://github.com/fangdididi/endpoint-probation.git .cursor/skills/endpoint-probation
```

**Any other agent** (Gemini CLI, OpenCode, Windsurf, Cline, Kimi, chat apps): paste `SKILL.md` into its instructions or project rules, or ask it to install the skill from this repository URL. For Chinese conversations use `SKILL.zh-CN.md`.

Requirements for the helper: Python 3.8+, nothing else.

## Usage

Talk to your agent:

- "This relay is 40% of the official price. Put it on probation before I use it in Claude Code."
- "Compare these three gateways for our Codex setup and tell me which one clears."
- "My balance dropped faster than the usage. Check the meter."
- "Everyone says the model got dumber this week. Is that real or just noise?"
- "帮我给这个中转站做一次试用期考核。"

Or drive the helper directly:

```bash
# 0. See every failure mode for free
python3 scripts/probation.py selftest

# 1. Open a card and fill in the criteria before testing
python3 scripts/probation.py card new --name "relay-1000" --owner me

# 2. Reference run on the official endpoint (a few cents)
export REF_KEY=...
python3 scripts/probation.py probe --base https://api.anthropic.com --protocol anthropic \
  --model <model-id> --key-env REF_KEY --label official --out runs/official.jsonl

# 3. Candidate run with a throwaway key (repeat in each time window)
export CANDIDATE_KEY=...
python3 scripts/probation.py probe --base https://api.relay.example/v1 --protocol openai \
  --model <claimed-model> --key-env CANDIDATE_KEY --label relay-1000 --out runs/relay-1000.jsonl

# 4. Read the flags, reconcile the bill
python3 scripts/probation.py report runs/relay-1000.jsonl --ref runs/official.jsonl
python3 scripts/probation.py bill runs/relay-1000.jsonl --in-price 3 --out-price 15 \
  --multiplier 0.6 --charged 0.071 --ref runs/official.jsonl

# 5. Record the verdict, lint the card, back up configs, switch narrowly
python3 scripts/probation.py card lint --path PROBATION.md
python3 scripts/probation.py backup
```

The key is read from the environment variable you name and never printed or written. Evidence files hold truncated answers, usage numbers, timings and header names only.

## Example output

A shifty endpoint compared with an honest reference (from `selftest`):

```text
## Flags
- [FAIL] plumbing: 2 call(s) showed 'error-in-200' - a failure dressed up as success
- [FAIL] identity: an unknown model name was accepted with 200 - the router answers with something else
- [FAIL] fidelity: long-document recall 0/2 - the start of long prompts may be cut
- [FAIL] identity: pin-zh: 72.0 prompt tokens vs 48.0 on the reference (x1.50) - different tokenizer or padded billing
- [FAIL] fidelity: long prompt counted as 2706.0 tokens vs 3731.0 on the reference - prompt likely trimmed
- [WARN] weather: median time-to-first-token 351ms vs 51ms on the reference

machine read (advisory; the verdict belongs on the card): FAIL
```

Worked cards:

- [`examples/claude-code-gateway.en.md`](examples/claude-code-gateway.en.md) — a Claude Code gateway for a public docs repo: **CLEARED-WITH-LIMITS** (public repos only, prompts under 100k, official fallback after 21:00, balance cap).
- [`examples/miniprogram-relay.zh-CN.md`](examples/miniprogram-relay.zh-CN.md) — a "0.3x price" relay for a mini-program support bot: **REJECTED** for hidden stream errors, 1.5x token counts and trimmed prompts.

## The six trials at a glance

| Trial | Question | Deciding signal |
|---|---|---|
| Plumbing | Does a request become a complete, honestly labelled answer? | success interval, completion markers, no errors inside 200 |
| Identity | Is it the model on the label? | pinned token counts vs reference, unknown-model and limit errors, finish vocabulary |
| Fidelity | Does the whole request arrive? | recall of the first line of a long document, reported prompt size |
| Meter | Is the charge justified? | balance drop vs usage × price × multiplier, cache credit |
| Weather | Is it usable when you work? | TTFT p50/p95, stalls, success by time window |
| Custody | What happens to your data and money? | operator, terms, retention, key scope, balance exposure |

## File structure

```text
endpoint-probation/
├── SKILL.md                         # the skill (English)
├── SKILL.zh-CN.md                   # the skill (Chinese)
├── README.md / README.zh-CN.md
├── LICENSE
├── scripts/
│   ├── probation.py                 # probe · report · bill · card · backup · selftest
│   └── mock_endpoint.py             # honest / shifty fake endpoint for rehearsal and tests
├── examples/
│   ├── claude-code-gateway.en.md    # CLEARED-WITH-LIMITS card
│   └── miniprogram-relay.zh-CN.md   # REJECTED card
└── tests/
    └── test_probation.py            # offline tests: python3 -m unittest discover -s tests -v
```

## Limits

- Supports OpenAI-style chat completions and Anthropic-style messages. Other protocols (for example a Responses-only endpoint) need the same probes run by hand.
- Identity evidence is strong against crude substitution and padded billing, weaker against a substitute from the same model family with the same tokenizer. Treat a clean identity trial as "no evidence of substitution", not as a certificate.
- The helper never judges custody; that trial is always human work.
- Probation checks behaviour. Whether a given relay is allowed under the model provider's terms is a separate question.

## License

[MIT](LICENSE) © fangdididi
