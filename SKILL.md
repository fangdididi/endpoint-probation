---
name: endpoint-probation
description: Put a new or changed AI model endpoint (API relay, reseller, gateway, aggregator, self-hosted proxy, or an official alias that suddenly behaves differently) on probation before an agent or app depends on it. Freezes pass criteria, runs six trials (plumbing, identity, fidelity, meter, weather, custody) against a reference, issues one of five verdicts, switches Claude Code / Codex / other tools over with a backup and rollback, and keeps watching afterwards. Use when someone asks "is this relay real / safe / worth it", "did the model get dumber", "why is my bill higher than the usage", or before pointing a coding agent at a non-official base URL.
---

# Endpoint Probation

> Every endpoint starts on probation. It earns trust with evidence you ran yourself, not with a price list, a screenshot or the model saying who it is.

[中文版](SKILL.zh-CN.md)

## What this skill is

A field procedure for deciding whether an AI API endpoint deserves to carry real work. A cheap relay, a team gateway, a regional reseller and a brand-new aggregator all look the same from the outside: a base URL, a key and a model name. Behind that URL the request may reach the model you paid for, a cheaper model wearing its name, a pool of borrowed accounts that dies on Monday morning, or a router that quietly trims long prompts to save bandwidth.

The skill turns "it seems fine" into a dated card with frozen criteria, six trials, tagged evidence and one verdict. It also covers the two moments people usually improvise: switching a coding agent over without losing the old configuration, and checking later whether the endpoint has drifted.

## The problem it solves

- **Failures that look like success.** A `200 OK` whose stream contains a rate-limit error, a `[DONE]` that arrives before the answer is finished, or a connection that just closes. Clients often show these as real model output.
- **Substitution.** The response says the flagship name; the tokenizer, error vocabulary and behaviour belong to something else. Long or expensive requests are the usual place where routing switches.
- **Silent trimming.** The relay cuts the start of long context, so an agent "forgets" the file it read ten minutes ago.
- **Billing drift.** Hidden multipliers, padded token counts, prompt-cache discounts taken by the relay but not passed on.
- **Fragile supply.** Fine at 10:00, unusable at the evening peak; fine this week, gone with your balance next week.
- **Custody.** Prompts, code and keys pass through a party you have never met.
- **Vibes-based judgement.** One bad screenshot "proves" a downgrade; one good one "proves" quality. Neither does.

## When to use it

- Before setting `ANTHROPIC_BASE_URL`, a Codex `model_providers` entry, a Cursor custom base URL, or any SDK `base_url` to a non-official host.
- When choosing between several relays or gateways, or renewing a top-up.
- When a team builds its own gateway or proxy and wants an acceptance test.
- When an endpoint you already use changes price, model list, latency or "feel".
- When a bill does not match the usage the API reported.

Do **not** use probation as a way to make a risky deal acceptable. If the work involves confidential code, customer personal data, credentials or regulated data, the answer is the official provider or your own controlled deployment, and the trial stops at step 0. Also note that some providers' terms forbid reselling access; probation tests behaviour, not legality.

## Vocabulary

| Term | Meaning |
|---|---|
| Candidate | The endpoint on probation. |
| Reference | The same model reached through a source you already trust (the official API, or a previously cleared endpoint). Without a reference, identity can never be better than INCONCLUSIVE. |
| Battery | The fixed set of probes run identically against candidate and reference. |
| Card | `PROBATION.md`: claim, job, frozen criteria, evidence, verdict, switch log. |
| Evidence tags | `[ran]` you executed it and kept the output · `[seen]` you observed it in logs, a console or a dashboard · `[said]` someone told you (seller, group chat, docs) · `[gap]` nobody knows yet. |

## The six trials

| # | Trial | Question | What decides it |
|---|---|---|---|
| 1 | **Plumbing** | Does a request reliably become a complete, honestly labelled answer? | Success rate with an interval, stream completion markers, error classes, no errors hidden inside `200` |
| 2 | **Identity** | Is it the model named on the label? | Prompt-token counts on pinned texts vs reference, unknown-model behaviour, limit messages, finish vocabulary, header families, reasoning presence |
| 3 | **Fidelity** | Does the whole request arrive intact? | Recall of a fact placed at the very start of a long document; reported prompt size vs reference |
| 4 | **Meter** | Is the charge what the usage justifies? | Balance drop vs usage fields × list price × advertised multiplier; cache tokens credited |
| 5 | **Weather** | Is it usable when you actually work? | Time to first token p50/p95, longest in-stream stall, success by time window |
| 6 | **Custody** | What happens to what you send, and to your money? | Operator identity, written terms, logging and retention, key scope, balance exposure, exit plan |

## Step by step

### Step 0 — Decide whether probation is the right tool

Write down what will travel through the endpoint. Public or disposable material: continue. Internal material: continue only if custody can be verified to a written standard. Confidential material: stop and use the official provider or your own deployment. Record this decision on the card; it caps every later verdict.

### Step 1 — Open the card and freeze the criteria

```bash
python3 scripts/probation.py card new --name "northgate" --owner "me"          # English
python3 scripts/probation.py card new --name "青柚中转" --lang zh --path PROBATION.md   # Chinese
```

1. **Copy the claim word for word**: model names, protocol, price and multiplier, context window, caching, reasoning mode, data-handling promises. Vague claims ("full strength", "enterprise grade") are recorded as they are, and you note that they cannot be tested.
2. **Describe the job**: which tool, what sensitivity, the longest prompt you really send, the hours you really work.
3. **Fill every blank in section 3 before running anything.** The numbers come from the job, not from what the candidate turns out to achieve. Criteria edited after the results are worthless; if you must change one, write the change and the reason below it, and treat the run as a new probation.

### Step 2 — Prepare safely

- Create a **throwaway key** with the smallest top-up the seller allows. Keep it in an environment variable, never in a file inside a repository, a ticket or a screenshot.
- Never send real secrets, customer data or private code during probation. The battery uses synthetic text only.
- Note the balance before and after each run so the meter trial has real numbers.

### Step 3 — Run the reference

```bash
export REF_KEY=...   # official key
python3 scripts/probation.py probe --base https://api.anthropic.com --protocol anthropic \
  --model <model-id> --key-env REF_KEY --rounds 3 --label official --out runs/official.jsonl
```

The reference battery costs a few cents and is reusable for the same model until the provider changes it. If you truly cannot reach any trusted source, run the candidate anyway, but identity stays INCONCLUSIVE and the verdict cannot be better than CLEARED-WITH-LIMITS for disposable work.

### Step 4 — Run the candidate

```bash
export CANDIDATE_KEY=...
python3 scripts/probation.py probe --base https://api.relay.example/v1 --protocol openai \
  --model <claimed-model> --key-env CANDIDATE_KEY --rounds 3 --label relay-1000 --out runs/relay-1000.jsonl
python3 scripts/probation.py report runs/relay-1000.jsonl --ref runs/official.jsonl
```

The battery per round: four pinned texts (English prose, Chinese prose, code, mixed symbols and emoji) measured for prompt tokens; a streamed counting answer for latency and completion; a long synthetic document whose first line holds a random code word. Once per run: a made-up model name and an absurd `max_tokens`, both of which a genuine provider rejects in a characteristic way.

For weather, repeat the candidate run in each time window from your criteria (for example morning, mid-afternoon and the evening peak). Three windows over two days tell you far more than thirty calls in one minute.

If the endpoint only speaks a protocol the helper does not support, run the same idea by hand: pinned prompts with recorded usage, one streamed reply, one long-document recall, one bogus model name.

### Step 5 — Do the trials that need a human

- **Meter**: `python3 scripts/probation.py bill runs/relay-1000.jsonl --in-price 3 --out-price 15 --multiplier 0.6 --charged 0.071 --ref runs/official.jsonl`. Prices are per million tokens in the seller's currency. Ask for a per-request log export if the console offers one and reconcile three requests by hand.
- **Fidelity at your real size**: the battery uses about 6,000 words by default (`--long-words`). If your agent sends 60k tokens, repeat once at that size; trimming often starts above a threshold.
- **Identity extras**: if the claimed model offers visible reasoning, ask a question that needs several steps and check that reasoning tokens or thinking blocks appear and are billed the way the reference bills them. If the provider has a public token-count endpoint, compare its count for your pinned texts with the candidate's usage.
- **Custody**: find a legal entity, written terms, a retention statement, where it is hosted, how refunds work and what happens to the balance if the service stops. A group-chat announcement is `[said]`; a signed contract or a published policy page is `[seen]`.

### Step 6 — Read the evidence honestly

Rules of inference:

1. **A model naming itself proves nothing.** System prompts can make any model claim any name. Never include "ask it who it is" as evidence.
2. **Fail closed.** A probe that errored or was skipped is a `[gap]`, never a pass.
3. **Separate three claims.** "This answer was wrong" needs one sample. "This endpoint fails more often" needs a rate comparison with intervals on the same task and budget. "They swapped the model" needs identity evidence such as tokenizer mismatch, not quality complaints.
4. **Small samples have wide intervals.** 12/12 successes still leaves a 95% lower bound near 76%. Say the interval, not just the rate.
5. **Compare like with like.** Same prompts, same parameters, same attempt budget. A curated best-of-ten from one side against a first try from the other is not a comparison.
6. **A clean machine report is not a pass.** The helper cannot judge custody, and it only sees what the endpoint chooses to return.

Tokenizer evidence is the strongest single identity signal: different model families split the same text differently, and the Chinese and mixed-symbol texts usually diverge most. A consistent ratio well above 1 across all pinned texts can also mean padded billing; either way the trial fails.

### Step 7 — Issue the verdict

| Verdict | Use when |
|---|---|
| **CLEARED** | Every trial meets the frozen criteria with `[ran]` or `[seen]` evidence, and custody fits the sensitivity from step 0. |
| **CLEARED-WITH-LIMITS** | Fit for a narrower job than requested. Write the limits as rules a teammate can follow: which repos, maximum prompt size, hours, balance cap, fallback. |
| **EXTENDED** | Promising but one trial needs more time or data (for example only one time window tested). Name the missing evidence and the date it will be collected. |
| **REJECTED** | Any failure disguised as success, any identity or fidelity failure, or a meter ratio above the threshold. These are not tuning issues. |
| **INCONCLUSIVE** | No reference, too few calls, or custody unknown for internal material. |

Then lint the card: `python3 scripts/probation.py card lint --path PROBATION.md`. It refuses a clearance that rests on `[gap]` evidence, identity or billing backed only by `[said]`, unfilled criteria, missing limits, or a missing rollback line.

### Step 8 — Switch with a way back

1. `python3 scripts/probation.py backup` copies the usual agent configuration files to `~/.endpoint-probation/backups/<timestamp>/` with a `RESTORE.sh`. The backup holds your keys; it is chmod 600, and you delete it when probation ends.
2. Switch at the **narrowest scope** the tool allows:
   - **Claude Code**: put `ANTHROPIC_BASE_URL` and the token (`ANTHROPIC_AUTH_TOKEN` for bearer-style gateways, `ANTHROPIC_API_KEY` for x-api-key style) in the `env` block of a project-level `.claude/settings.local.json` rather than the global `~/.claude/settings.json`. Check what is active with `/status`.
   - **Codex CLI**: add a `[model_providers.<name>]` table (`base_url`, `env_key`, and a `wire_api` that matches what the endpoint really speaks) plus a `[profiles.<name>]` that uses it, then run `codex --profile <name>` only where the verdict allows.
   - **Cursor**: custom API keys and an overridden base URL live in the model settings; remember that some features still go through Cursor's own backend, so probation only covers the calls that use your key.
   - **Gemini CLI, OpenCode, Aider, Continue and SDK apps**: prefer per-project files or per-process environment variables over global files.
3. Run one small real task inside the agent and confirm with the tool's own status display that the new endpoint is answering.
4. Write the switch time and the exact rollback command on the card.

### Step 9 — Parole

A cleared endpoint stays cleared only while the conditions hold. Re-run the battery (or at least the pinned texts and one long recall) when:

- the price, multiplier or model list changes;
- the model name maps to a new version upstream;
- failures or latency jump, or teammates start saying "it got dumber";
- the next check date on the card arrives.

For "it got dumber": pick one fixed task with a fixed pass rule, run it the same number of times (20 or more) on the candidate and on the reference, keep every sample, and compare the rates with their intervals. The report prints a Fisher exact test for success counts; for your own task counts, compare the two intervals and do not call a difference real if they overlap heavily.

## Helper: `scripts/probation.py`

Standard library only, Python 3.8+. Speaks OpenAI-style chat completions and Anthropic-style messages, streamed and not. Keys are read from the environment variable you name and are never printed or written.

| Command | Purpose |
|---|---|
| `probe` | Run the battery; writes JSONL evidence (texts truncated, no key, no full headers). |
| `report RUN [--ref REF] [--lang zh]` | Summary plus FAIL/WARN/NOTE flags per trial; exit code 1 when any FAIL. |
| `bill RUN --in-price --out-price [--multiplier] [--charged] [--ref]` | Reconcile charges against usage fields. |
| `card new / card lint` | Create a card (English or Chinese) or check it for unsupported clearance. |
| `backup [FILES...]` | Back up agent configuration with a one-command restore. |
| `selftest` | Rehearse the whole flow against two local fake endpoints, one honest and one shifty. No network, no cost. |

Run `python3 scripts/probation.py selftest` once to see what each kind of failure looks like before you spend anything.

## Examples

- `examples/claude-code-gateway.en.md` — a gateway for Claude Code on a public docs repo: identity and meter pass, evening latency and an unverified logging promise lead to **CLEARED-WITH-LIMITS** with written limits and a rollback.
- `examples/miniprogram-relay.zh-CN.md` — a "0.3x official price" relay for a mini-program support bot: errors hidden in `200` streams, 1.5x token counts, trimmed long prompts — **REJECTED** before production was ever touched.

Short exchange:

> **User:** A friend's relay is 40% of the official price. Can I just put it in Claude Code?
>
> **Agent (with this skill):** Let's give it probation first; it costs about the price of a coffee. What will Claude Code read through it: public repos, or company code? … Company code, then we stop here: that needs the official endpoint or your company gateway. For your open-source side project, I'll open a card, freeze the criteria with you, run the battery against your official key and the relay, and come back with a verdict and a rollback command.

## Tips

- Probe the exact model ID you will use; relays often route each ID to a different pool.
- Keep the reference runs. A fresh candidate run plus an old reference is enough for parole checks until the official model version changes.
- When several relays are compared, use the same battery, rounds and windows for all of them and put them in one table; the cheapest one that clears is the answer, not the cheapest one.
- If a seller asks you to disable stream completion checks, retries or timeouts "for compatibility", treat that as evidence for the plumbing trial.
- A suspiciously low price is a custody question first: someone is paying the difference.
- Close the probation: revoke the throwaway key, delete raw runs you no longer need, delete config backups after a successful switch.
