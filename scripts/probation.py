#!/usr/bin/env python3
"""probation.py - put an AI API endpoint on probation before you trust it.

Standard library only (Python 3.8+). The API key is read from an environment
variable you name; it is never printed, logged or written to disk.

Commands
  probe     run the probe battery against one endpoint, write JSONL evidence
  report    summarise a run; with --ref, compare it against a reference run
  bill      check what you were charged against what the usage fields say
  card      create (new) or check (lint) a PROBATION.md card
  backup    copy agent config files to a timestamped folder before a switch
  selftest  rehearse everything against two local fake endpoints

Examples
  export CANDIDATE_KEY=...           # a throwaway key with a small balance
  python3 probation.py probe --base https://relay.example.com/v1 \
      --protocol openai --model gpt-x --key-env CANDIDATE_KEY \
      --rounds 3 --out runs/candidate.jsonl
  python3 probation.py report runs/candidate.jsonl --ref runs/official.jsonl
  python3 probation.py bill runs/candidate.jsonl --in-price 3 --out-price 15 --charged 0.41
"""
import argparse
import datetime as _dt
import json
import math
import os
import random
import shutil
import statistics
import string
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"

# ---------------------------------------------------------------- pinned texts
# Fixed inputs whose reported prompt-token counts act as a tokenizer fingerprint.
PINNED = {
    "pin-en": "A quiet lighthouse keeper counted seventeen gulls, three ferries and one stubborn fog bank before breakfast.",
    "pin-zh": "山脚下的小面馆清晨五点就亮灯，老板一边揉面一边听收音机里的天气预报，说午后会有雷阵雨。",
    "pin-code": "def merge(a, b):\n    out = {**a}\n    for k, v in b.items():\n        out[k] = out.get(k, 0) + v\n    return out\n",
    "pin-mixed": "Order #A-7731 \u2192 \u00e9t\u00e9 \u2615 \U0001F680 \u2014 total \u00a5128.50 (\u542b\u7a0e) \u2713",
}
REPLY_OK = "\n\nReply with the single word: ok"
HEADER_HINTS = ("x-request-id", "request-id", "cf-ray", "x-amzn-requestid", "openai-processing-ms",
                "anthropic-ratelimit", "x-ratelimit", "server", "via", "x-powered-by", "x-new-api-version",
                "x-oneapi-request-id", "openai-organization", "x-envoy", "x-cache")


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def long_document(words, code):
    rnd = random.Random(words)
    vocab = ("river", "ledger", "copper", "window", "harvest", "signal", "orchard", "tunnel", "lantern",
             "meadow", "circuit", "basket", "glacier", "thread", "compass", "pebble", "furnace", "anchor")
    body = []
    for i in range(words // 12):
        body.append(" ".join(rnd.choice(vocab) for _ in range(12)) + ".")
    return ("The code word is %s. Remember it.\n\n" % code) + "\n".join(body) + \
        "\n\nQuestion: What was the code word stated at the very start of this document? Answer with the code word only."


# ---------------------------------------------------------------- transport
class Endpoint:
    def __init__(self, base, protocol, model, key, auth, timeout):
        self.base = base.rstrip("/")
        self.protocol = protocol
        self.model = model
        self.key = key
        self.auth = auth
        self.timeout = timeout

    def url(self):
        if self.protocol == "openai":
            return self.base + "/chat/completions"
        return self.base + ("/messages" if self.base.endswith("/v1") else "/v1/messages")

    def headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.protocol == "anthropic":
            h["anthropic-version"] = "2023-06-01"
            if self.auth == "bearer":
                h["Authorization"] = "Bearer " + self.key
            else:
                h["x-api-key"] = self.key
        else:
            h["Authorization"] = "Bearer " + self.key
        return h

    def body(self, prompt, max_tokens, stream, model=None):
        b = {"model": model or self.model, "max_tokens": max_tokens,
             "messages": [{"role": "user", "content": prompt}], "stream": stream}
        if stream and self.protocol == "openai":
            b["stream_options"] = {"include_usage": True}
        return b

    def call(self, prompt, max_tokens=16, stream=False, model=None):
        """Returns a dict of observations. Never raises for HTTP/network trouble."""
        rec = {"status": None, "ok": False, "error_class": None, "error_excerpt": None,
               "ttft_ms": None, "total_ms": None, "max_gap_ms": None, "completed": None,
               "text": "", "prompt_tokens": None, "completion_tokens": None, "cached_tokens": None,
               "finish": None, "model_echo": None, "header_keys": [], "stream": stream}
        data = json.dumps(self.body(prompt, max_tokens, stream, model)).encode()
        req = urllib.request.Request(self.url(), data=data, headers=self.headers(), method="POST")
        t0 = time.monotonic()
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            rec["total_ms"] = round((time.monotonic() - t0) * 1000)
            rec["header_keys"] = header_keys(e.headers)
            try:
                raw = e.read()[:600].decode("utf-8", "replace")
            except Exception:
                raw = ""
            rec["error_excerpt"] = redact(raw, self.key)[:300]
            rec["error_class"] = classify_status(e.code)
            return rec
        except Exception as e:  # network, TLS, timeout
            rec["total_ms"] = round((time.monotonic() - t0) * 1000)
            rec["error_class"] = "network"
            rec["error_excerpt"] = redact(str(e), self.key)[:300]
            return rec
        rec["status"] = resp.status
        rec["header_keys"] = header_keys(resp.headers)
        try:
            if stream:
                self._read_stream(resp, rec, t0)
            else:
                payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
                rec["total_ms"] = round((time.monotonic() - t0) * 1000)
                self._read_plain(payload, rec)
        except Exception as e:
            rec["error_class"] = rec["error_class"] or "protocol"
            rec["error_excerpt"] = redact(str(e), self.key)[:300]
        finally:
            resp.close()
        if rec["total_ms"] is None:
            rec["total_ms"] = round((time.monotonic() - t0) * 1000)
        rec["ok"] = rec["error_class"] is None and (rec["completed"] is not False)
        return rec

    def _read_plain(self, p, rec):
        if "error" in p and p.get("error"):
            rec["error_class"] = "error-in-200"
            rec["error_excerpt"] = json.dumps(p["error"])[:300]
            return
        rec["model_echo"] = p.get("model")
        if self.protocol == "openai":
            ch = (p.get("choices") or [{}])[0]
            rec["text"] = ((ch.get("message") or {}).get("content") or "")
            rec["finish"] = ch.get("finish_reason")
            u = p.get("usage") or {}
            rec["prompt_tokens"] = u.get("prompt_tokens")
            rec["completion_tokens"] = u.get("completion_tokens")
            rec["cached_tokens"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        else:
            rec["text"] = "".join(b.get("text", "") for b in p.get("content", []) if b.get("type") == "text")
            rec["finish"] = p.get("stop_reason")
            u = p.get("usage") or {}
            rec["prompt_tokens"] = u.get("input_tokens")
            rec["completion_tokens"] = u.get("output_tokens")
            rec["cached_tokens"] = u.get("cache_read_input_tokens")
        rec["completed"] = rec["finish"] is not None

    def _read_stream(self, resp, rec, t0):
        last = None
        gaps = []
        done = False
        event = None
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                if rec["finish"] is not None or self.protocol != "openai":
                    done = True
                elif rec["error_class"] is None:
                    rec["error_class"] = "early-done"  # [DONE] with no finish reason
                continue
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("error") or obj.get("type") == "error" or event == "error":
                rec["error_class"] = "error-in-200"
                rec["error_excerpt"] = json.dumps(obj.get("error", obj))[:300]
                continue
            piece = ""
            if self.protocol == "openai":
                if obj.get("model"):
                    rec["model_echo"] = obj.get("model")
                for ch in obj.get("choices") or []:
                    d = ch.get("delta") or {}
                    piece += (d.get("content") or "") + (d.get("reasoning_content") or "")
                    if ch.get("finish_reason"):
                        rec["finish"] = ch["finish_reason"]
                u = obj.get("usage")
                if u:
                    rec["prompt_tokens"] = u.get("prompt_tokens")
                    rec["completion_tokens"] = u.get("completion_tokens")
                    rec["cached_tokens"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
            else:
                t = obj.get("type")
                if t == "message_start":
                    m = obj.get("message") or {}
                    rec["model_echo"] = m.get("model")
                    u = m.get("usage") or {}
                    rec["prompt_tokens"] = u.get("input_tokens")
                    rec["cached_tokens"] = u.get("cache_read_input_tokens")
                elif t == "content_block_delta":
                    d = obj.get("delta") or {}
                    piece = d.get("text") or d.get("thinking") or ""
                elif t == "message_delta":
                    rec["finish"] = (obj.get("delta") or {}).get("stop_reason")
                    rec["completion_tokens"] = (obj.get("usage") or {}).get("output_tokens")
                elif t == "message_stop":
                    done = True
            if piece:
                tnow = time.monotonic()
                if last is None:
                    rec["ttft_ms"] = round((tnow - t0) * 1000)
                else:
                    gaps.append((tnow - last) * 1000)
                last = tnow
                rec["text"] += piece
        rec["total_ms"] = round((time.monotonic() - t0) * 1000)
        rec["max_gap_ms"] = round(max(gaps)) if gaps else None
        if self.protocol == "openai" and rec["finish"] is not None and not done and rec["error_class"] is None:
            done = True  # some servers omit [DONE]; a finish_reason is enough
        rec["completed"] = bool(done) and rec["error_class"] is None
        if not rec["completed"] and rec["error_class"] is None:
            rec["error_class"] = "no-completion"


def header_keys(h):
    keys = sorted({k.lower() for k in (h.keys() if h else [])})
    return [k for k in keys if any(k.startswith(x) for x in HEADER_HINTS)]


def redact(text, key):
    if key and key in text:
        text = text.replace(key, "<redacted>")
    return text


def classify_status(code):
    if code in (401, 403):
        return "auth"
    if code == 429:
        return "rate-limit"
    if 400 <= code < 500:
        return "client"
    if code in (502, 503, 504):
        return "upstream"
    return "server"


# ---------------------------------------------------------------- probe
def run_probe(ep, rounds, long_words, out, label, quiet=False):
    rows = []

    def log(r):
        rows.append(r)
        if not quiet:
            mark = "ok " if r["ok"] else "BAD"
            print("  %s %-12s round %d status=%s %s ttft=%s total=%sms" % (
                mark, r["probe"], r["round"], r["status"], r["error_class"] or "", r["ttft_ms"], r["total_ms"]))

    for rnd in range(1, rounds + 1):
        for name, text in PINNED.items():
            r = ep.call(text + REPLY_OK, max_tokens=5)
            log(dict(r, probe=name, round=rnd))
        r = ep.call("Count from one to forty in digits, separated by commas.", max_tokens=200, stream=True)
        log(dict(r, probe="stream", round=rnd))
        code = "%s-%d" % ("".join(random.choice(string.ascii_uppercase) for _ in range(5)), random.randint(100, 999))
        r = ep.call(long_document(long_words, code), max_tokens=20, stream=True)
        r["recall_expected"] = code
        r["recall_correct"] = code in (r.get("text") or "")
        log(dict(r, probe="long-recall", round=rnd, long_words=long_words))
    r = ep.call("Reply with: ok", max_tokens=5, model="no-such-model-%d" % random.randint(1000, 9999))
    log(dict(r, probe="bad-model", round=0))
    r = ep.call("Reply with: ok", max_tokens=10 ** 9)
    log(dict(r, probe="huge-max", round=0))
    stamp = now_iso()
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": True, "label": label, "base_host": ep.base.split("/")[2] if "//" in ep.base else ep.base,
                            "protocol": ep.protocol, "model": ep.model, "rounds": rounds, "long_words": long_words,
                            "finished_at": stamp, "tool": "probation.py " + VERSION}, ensure_ascii=False) + "\n")
        for r in rows:
            r = dict(r)
            r["text"] = (r.get("text") or "")[:160]
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def load(path):
    meta, rows = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if o.get("meta"):
                meta = o
            else:
                rows.append(o)
    return meta, rows


# ---------------------------------------------------------------- statistics
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def fisher_two_sided(a, b, c, d):
    """2x2 table [[a, b], [c, d]]; returns two-sided p-value."""
    n = a + b + c + d
    r1, c1 = a + b, a + c

    def pmf(x):
        return math.comb(r1, x) * math.comb(n - r1, c1 - x) / math.comb(n, c1)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(lo, hi + 1) if pmf(x) <= p0 * (1 + 1e-9)))


def pct(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    i = min(len(vals) - 1, max(0, int(math.ceil(q * len(vals))) - 1))
    return vals[i]


def summarize(rows):
    s = {}
    core = [r for r in rows if r["probe"] not in ("bad-model", "huge-max")]
    k = sum(1 for r in core if r["ok"])
    s["success"] = (k, len(core))
    s["errors"] = {}
    for r in core:
        if r["error_class"]:
            s["errors"][r["error_class"]] = s["errors"].get(r["error_class"], 0) + 1
    st = [r for r in rows if r["stream"] and r["ok"]]
    s["ttft_p50"] = pct([r["ttft_ms"] for r in st], 0.5)
    s["ttft_p95"] = pct([r["ttft_ms"] for r in st], 0.95)
    s["gap_max"] = max([r["max_gap_ms"] for r in st if r.get("max_gap_ms") is not None] or [0]) or None
    s["tokens"] = {}
    for name in PINNED:
        vals = [r["prompt_tokens"] for r in rows if r["probe"] == name and r.get("prompt_tokens") is not None]
        s["tokens"][name] = statistics.median(vals) if vals else None
    lr = [r for r in rows if r["probe"] == "long-recall"]
    s["recall"] = (sum(1 for r in lr if r.get("recall_correct")), len(lr))
    s["long_tokens"] = statistics.median([r["prompt_tokens"] for r in lr if r.get("prompt_tokens")] or [0]) or None
    s["finish"] = sorted({str(r["finish"]) for r in rows if r.get("finish") is not None})
    s["models_echoed"] = sorted({r["model_echo"] for r in rows if r.get("model_echo")})
    s["headers"] = sorted({h for r in rows for h in r.get("header_keys", [])})
    bm = [r for r in rows if r["probe"] == "bad-model"]
    s["bad_model"] = (bm[0]["status"], bm[0]["error_class"], (bm[0].get("error_excerpt") or "")[:120]) if bm else None
    hm = [r for r in rows if r["probe"] == "huge-max"]
    s["huge_max"] = (hm[0]["status"], (hm[0].get("error_excerpt") or "")[:160]) if hm else None
    s["cached_seen"] = any((r.get("cached_tokens") or 0) > 0 for r in rows)
    return s


def flags_for(meta, s, ref=None, rs=None):
    """Returns list of (trial, level, message). level: FAIL / WARN / NOTE"""
    f = []
    k, n = s["success"]
    lo, hi = wilson(k, n)
    if n and k < n:
        f.append(("plumbing", "WARN" if k / n >= 0.9 else "FAIL",
                  "%d of %d core calls failed (success %.0f%%, 95%% range %.0f-%.0f%%)" % (n - k, n, 100 * k / n, 100 * lo, 100 * hi)))
    for cls in ("error-in-200", "early-done", "no-completion"):
        if s["errors"].get(cls):
            f.append(("plumbing", "FAIL", "%d call(s) showed '%s' - a failure dressed up as success" % (s["errors"][cls], cls)))
    if s["bad_model"] and s["bad_model"][0] == 200:
        f.append(("identity", "FAIL", "an unknown model name was accepted with 200 - the router answers with something else"))
    if s["recall"][1] and s["recall"][0] < s["recall"][1]:
        f.append(("fidelity", "FAIL", "long-document recall %d/%d - the start of long prompts may be cut" % s["recall"]))
    if len(s["models_echoed"]) > 1:
        f.append(("identity", "WARN", "responses named different models: %s" % ", ".join(s["models_echoed"])))
    if meta.get("model") and s["models_echoed"] and meta["model"] not in s["models_echoed"]:
        f.append(("identity", "NOTE", "model field in responses (%s) differs from the requested name" % ", ".join(s["models_echoed"])))
    if ref and rs:
        for name, v in s["tokens"].items():
            rv = rs["tokens"].get(name)
            if v and rv:
                ratio = v / rv
                if abs(ratio - 1) > 0.15:
                    f.append(("identity", "FAIL", "%s: %s prompt tokens vs %s on the reference (x%.2f) - different tokenizer or padded billing" % (name, v, rv, ratio)))
                elif abs(ratio - 1) > 0.03:
                    f.append(("identity", "WARN", "%s: %s prompt tokens vs %s on the reference (x%.2f)" % (name, v, rv, ratio)))
        if s["long_tokens"] and rs["long_tokens"]:
            ratio = s["long_tokens"] / rs["long_tokens"]
            if ratio < 0.85:
                f.append(("fidelity", "FAIL", "long prompt counted as %s tokens vs %s on the reference - prompt likely trimmed" % (s["long_tokens"], rs["long_tokens"])))
        if set(s["finish"]) - set(rs["finish"]):
            f.append(("identity", "WARN", "finish/stop vocabulary %s differs from the reference %s" % (s["finish"], rs["finish"])))
        ck, cn = s["success"]
        rk, rn = rs["success"]
        if cn and rn:
            p = fisher_two_sided(ck, cn - ck, rk, rn - rk)
            msg = "success %d/%d vs reference %d/%d (Fisher p=%.3f)" % (ck, cn, rk, rn, p)
            f.append(("weather", "FAIL" if (p < 0.05 and ck / cn < rk / rn) else "NOTE", msg))
        if s["ttft_p50"] and rs["ttft_p50"] and s["ttft_p50"] > 2 * rs["ttft_p50"]:
            f.append(("weather", "WARN", "median time-to-first-token %sms vs %sms on the reference" % (s["ttft_p50"], rs["ttft_p50"])))
        if s["bad_model"] and rs["bad_model"] and s["bad_model"][0] != rs["bad_model"][0]:
            f.append(("identity", "WARN", "unknown-model error status %s vs %s on the reference" % (s["bad_model"][0], rs["bad_model"][0])))
    return f


def cmd_report(a):
    meta, rows = load(a.run)
    s = summarize(rows)
    ref = rs = None
    if a.ref:
        ref, rrows = load(a.ref)
        rs = summarize(rrows)
    k, n = s["success"]
    lo, hi = wilson(k, n)
    zh = a.lang == "zh"
    print(("# 试用期报告: %s" if zh else "# Probation report: %s") % (meta.get("label") or a.run))
    print(("端点 %s · 协议 %s · 模型 %s · 轮数 %s · 完成于 %s" if zh else "host %s · protocol %s · model %s · rounds %s · finished %s") % (
        meta.get("base_host"), meta.get("protocol"), meta.get("model"), meta.get("rounds"), meta.get("finished_at")))
    print()
    print(("成功 %d/%d（95%% 区间 %.0f–%.0f%%）" if zh else "success %d/%d (95%% range %.0f-%.0f%%)") % (k, n, 100 * lo, 100 * hi))
    print(("错误类型: %s" if zh else "error classes: %s") % (s["errors"] or "-"))
    print(("首字时间 p50/p95: %s / %s ms · 最长流内停顿: %s ms" if zh else "time to first token p50/p95: %s / %s ms · longest in-stream stall: %s ms") % (s["ttft_p50"], s["ttft_p95"], s["gap_max"]))
    print(("长文召回: %d/%d · 长文 prompt tokens 中位数: %s" if zh else "long-document recall: %d/%d · long prompt tokens (median): %s") % (s["recall"] + (s["long_tokens"],)))
    print(("固定文本 prompt tokens: %s" if zh else "pinned prompt tokens: %s") % s["tokens"])
    print(("结束原因词表: %s · 回显模型名: %s" if zh else "finish vocabulary: %s · model names echoed: %s") % (s["finish"], s["models_echoed"]))
    print(("未知模型 → %s · 超大 max_tokens → %s" if zh else "unknown model -> %s · huge max_tokens -> %s") % (s["bad_model"], s["huge_max"]))
    print(("响应头家族: %s" if zh else "header families: %s") % (", ".join(s["headers"]) or "-"))
    if rs:
        print(("参照: %s（%s）" if zh else "reference: %s (%s)") % (ref.get("label"), ref.get("base_host")))
        print(("参照固定文本 tokens: %s" if zh else "reference pinned tokens: %s") % rs["tokens"])
    print()
    fl = flags_for(meta, s, ref, rs)
    print("## " + ("旗标" if zh else "Flags"))
    if not fl:
        print("- " + ("没有发现问题（这不等于通过：还要看计费与托管两项）" if zh else "none raised (this is not a pass by itself: billing and custody still need checking)"))
    for trial, level, msg in fl:
        print("- [%s] %s: %s" % (level, trial, msg))
    worst = "FAIL" if any(l == "FAIL" for _, l, _ in fl) else ("WARN" if any(l == "WARN" for _, l, _ in fl) else "CLEAN")
    if not rs:
        print("- [NOTE] identity: " + ("没有参照运行，身份只能算 INCONCLUSIVE；请先对官方端点跑一次 --label official" if zh else
              "no reference run, so identity stays INCONCLUSIVE; probe the official endpoint once and pass it with --ref"))
    print()
    print(("机器结论（仅供参考，最终判决写在卡片里）: %s" if zh else "machine read (advisory; the verdict belongs on the card): %s") % worst)
    return 1 if worst == "FAIL" else 0


# ---------------------------------------------------------------- bill
def cmd_bill(a):
    meta, rows = load(a.run)
    pin = sum(r.get("prompt_tokens") or 0 for r in rows)
    pout = sum(r.get("completion_tokens") or 0 for r in rows)
    cached = sum(r.get("cached_tokens") or 0 for r in rows)
    cache_price = a.cache_price if a.cache_price is not None else a.in_price
    expected = ((pin - cached) * a.in_price + cached * cache_price + pout * a.out_price) / 1e6 * a.multiplier
    zh = a.lang == "zh"
    print(("用量字段合计: 输入 %d（其中缓存命中 %d）· 输出 %d" if zh else "usage fields total: input %d (cache hits %d) · output %d") % (pin, cached, pout))
    print(("按标价 × 倍率 %.2f 应付: %.4f" if zh else "expected at list price x multiplier %.2f: %.4f") % (a.multiplier, expected))
    if a.ref:
        _, rrows = load(a.ref)
        rin = sum(r.get("prompt_tokens") or 0 for r in rrows)
        if rin and pin:
            print(("同一批请求在参照端点计 %d 输入 token，本端点计 %d（x%.2f）" if zh else
                   "the same requests counted %d input tokens on the reference and %d here (x%.2f)") % (rin, pin, pin / rin))
    if a.charged is not None and not expected:
        print("[GAP] " + ("这次运行没有任何用量字段，无法核对扣费；端点不回传 usage 本身就是一个警告" if zh else
                          "this run carries no usage fields, so charges cannot be checked; an endpoint that hides usage is itself a warning"))
        return 1
    if a.charged is not None:
        ratio = a.charged / expected if expected else float("inf")
        print(("实际扣费: %.4f · 实际/应付 = %.2f" if zh else "actually charged: %.4f · charged/expected = %.2f") % (a.charged, ratio))
        if ratio > 1.10:
            print("[FAIL] " + ("扣费比用量字段高出 10% 以上：隐藏倍率、虚增 token 或缓存优惠没有返还" if zh else
                               "charged more than 10% above what the usage fields justify: hidden multiplier, padded tokens or kept cache discount"))
            return 1
        if ratio < 0.5:
            print("[WARN] " + ("扣费远低于标价：确认是不是真的是这个模型、是不是有补贴期限" if zh else
                               "charged far below list price: confirm the model is real and ask when the subsidy ends"))
        else:
            print("[OK] " + ("扣费与用量字段一致" if zh else "charges line up with the usage fields"))
    return 0


# ---------------------------------------------------------------- card
CARD_EN = """# Probation card: {name}

Opened: {date} · Owner: {owner} · Status: OPEN

## 1. The claim (copy what the seller promises, word for word)
- Model name(s) promised:
- Protocol and base URL host:
- Price / multiplier / top-up rules:
- Context window, caching, reasoning mode promised:
- Data handling promise (logging, retention, region):

## 2. The job it will do
- Tool or app that will use it (Claude Code, Codex, backend, ...):
- Sensitivity of what will be sent: public / internal / confidential (confidential means: do not use a third party)
- Longest prompt you actually send:

## 3. Pass criteria (frozen before any test; do not edit after results)
- Plumbing: core success >= __% over __ calls, zero failures disguised as success
- Identity: pinned token counts within 3% of the reference; unknown model refused
- Fidelity: long-document recall __/__ at __ words
- Meter: charged/expected <= 1.10
- Weather: time to first token p95 <= ____ ms, checked in __ time windows
- Custody: throwaway key, balance cap ____, nothing confidential sent

## 4. Evidence (tag each line [ran] [seen] [said] [gap])
| Trial | Result | Evidence | Tag |
|---|---|---|---|
| Plumbing | | | |
| Identity | | | |
| Fidelity | | | |
| Meter | | | |
| Weather | | | |
| Custody | | | |

## 5. Verdict
One of: CLEARED · CLEARED-WITH-LIMITS · EXTENDED · REJECTED · INCONCLUSIVE
Verdict:
Limits (if any):
Re-probation triggers: price change · model alias change · failure spike · next check date ____

## 6. Switch log
- Config backed up to:
- Switched on:
- Rollback command:
"""

CARD_ZH = """# 试用期卡片：{name}

开立：{date} · 负责人：{owner} · 状态：OPEN

## 1. 对方的承诺（照抄卖家原话）
- 承诺的模型名：
- 协议与 base URL 域名：
- 价格 / 倍率 / 充值规则：
- 承诺的上下文长度、缓存、推理模式：
- 数据处理承诺（是否记录、保留多久、所在地区）：

## 2. 它要干的活
- 哪个工具或应用会用它（Claude Code、Codex、后端服务……）：
- 发送内容的敏感度：公开 / 内部 / 机密（机密 = 不要走第三方）
- 你真实会发的最长 prompt：

## 3. 通过标准（测试前冻结，出结果后不许改）
- 管道：__ 次调用核心成功率 >= __%，伪装成成功的失败为零
- 身份：固定文本 token 数与参照相差 <= 3%；未知模型名被拒绝
- 保真：__ 字长文召回 __/__
- 计量：实际扣费/应付 <= 1.10
- 天气：首字时间 p95 <= ____ ms，覆盖 __ 个时间段
- 托管：一次性 key，余额上限 ____，不发送任何机密

## 4. 证据（每行标注 [ran] [seen] [said] [gap]）
| 项目 | 结果 | 证据 | 标签 |
|---|---|---|---|
| 管道 | | | |
| 身份 | | | |
| 保真 | | | |
| 计量 | | | |
| 天气 | | | |
| 托管 | | | |

## 5. 判决
五选一：CLEARED · CLEARED-WITH-LIMITS · EXTENDED · REJECTED · INCONCLUSIVE
判决：
限制条件（如有）：
重新试用的触发条件：价格变化 · 模型别名变化 · 失败率飙升 · 下次检查日期 ____

## 6. 切换记录
- 配置备份位置：
- 切换时间：
- 回滚命令：
"""

VERDICTS = ("CLEARED-WITH-LIMITS", "CLEARED", "EXTENDED", "REJECTED", "INCONCLUSIVE")


def cmd_card(a):
    if a.action == "new":
        if os.path.exists(a.path) and not a.force:
            print("refusing to overwrite %s (use --force)" % a.path)
            return 1
        tpl = CARD_ZH if a.lang == "zh" else CARD_EN
        with open(a.path, "w", encoding="utf-8") as f:
            f.write(tpl.format(name=a.name or "endpoint", date=now_iso()[:10], owner=a.owner or "-"))
        print("wrote " + a.path)
        return 0
    text = open(a.path, encoding="utf-8").read()
    problems = []
    lines = text.splitlines()
    verdict_line = next((l for l in lines if l.strip().startswith(("Verdict:", "判决："))), "")
    verdict = next((v for v in VERDICTS if v in verdict_line), None)
    if not verdict:
        problems.append("no verdict recorded (pick one of CLEARED, CLEARED-WITH-LIMITS, EXTENDED, REJECTED, INCONCLUSIVE)")
    crit = text.split("## 3.")[1].split("## 4.")[0] if "## 3." in text and "## 4." in text else ""
    if "__" in crit or "____" in crit:
        problems.append("pass criteria still have blanks - freeze them before testing")
    ev = text.split("## 4.")[1].split("## 5.")[0] if "## 4." in text and "## 5." in text else ""
    rows = [l for l in ev.splitlines() if l.startswith("|") and not l.startswith("|---") and ("Trial" not in l and "项目" not in l)]
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if len(cells) >= 4 and (not cells[1] or not any(t in cells[3] for t in ("[ran]", "[seen]", "[said]", "[gap]"))):
            problems.append("evidence row '%s' has no result or no tag" % cells[0])
    if verdict in ("CLEARED", "CLEARED-WITH-LIMITS"):
        for r in rows:
            cells = [c.strip() for c in r.strip("|").split("|")]
            if len(cells) >= 4 and "[gap]" in cells[3]:
                problems.append("cleared while '%s' is only a [gap] - use INCONCLUSIVE or EXTENDED" % cells[0])
            if len(cells) >= 4 and "[said]" in cells[3] and cells[0].lower() in ("identity", "meter", "身份", "计量"):
                problems.append("'%s' rests on the seller's word [said] - identity and billing need [ran] evidence" % cells[0])
    if verdict == "CLEARED-WITH-LIMITS":
        lim = next((l for l in lines if l.strip().startswith(("Limits", "限制条件"))), "")
        if len(lim.split(":", 1)[-1].split("：", 1)[-1].strip()) < 3:
            problems.append("CLEARED-WITH-LIMITS needs the limits written down")
    if verdict and "Rollback" not in text and "回滚" not in text:
        problems.append("no rollback line")
    elif verdict in ("CLEARED", "CLEARED-WITH-LIMITS"):
        rb = next((l for l in lines if "Rollback" in l or "回滚命令" in l), "")
        if len(rb.split(":", 1)[-1].split("：", 1)[-1].strip()) < 3:
            problems.append("cleared without a rollback command written down")
    if problems:
        for p in problems:
            print("- " + p)
        return 1
    print("card ok: verdict %s" % verdict)
    return 0


# ---------------------------------------------------------------- backup
AGENT_FILES = [
    "~/.claude/settings.json", "~/.claude.json", "~/.codex/config.toml", "~/.codex/auth.json",
    "~/.gemini/settings.json", "~/.gemini/.env", "~/.config/opencode/opencode.json", "~/.aider.conf.yml",
    "~/.continue/config.yaml", "~/.cursor/mcp.json",
]


def cmd_backup(a):
    dest = os.path.expanduser(a.dest or "~/.endpoint-probation/backups")
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(dest, stamp)
    files = a.files or AGENT_FILES
    copied = []
    for p in files:
        src = os.path.expanduser(p)
        if os.path.isfile(src):
            rel = src.replace(os.path.expanduser("~"), "HOME").lstrip("/")
            out = os.path.join(target, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
            os.chmod(out, 0o600)
            copied.append((src, out))
    if not copied:
        print("nothing to back up (none of the known agent config files exist)")
        return 0
    with open(os.path.join(target, "RESTORE.sh"), "w") as f:
        f.write("#!/bin/sh\n# restores the files exactly as they were at %s\nset -e\n" % stamp)
        for src, out in copied:
            f.write('cp -p "%s" "%s"\n' % (out, src))
    os.chmod(os.path.join(target, "RESTORE.sh"), 0o700)
    for src, out in copied:
        print("saved %s" % src)
    print("rollback: sh %s" % os.path.join(target, "RESTORE.sh"))
    print("(backups contain your keys; they are chmod 600 - delete the folder when probation is over)")
    return 0


# ---------------------------------------------------------------- selftest
def cmd_selftest(a):
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import mock_endpoint
    tmp = tempfile.mkdtemp(prefix="probation-")
    servers = []
    ok = True
    for mode in ("honest", "shifty"):
        srv = mock_endpoint.serve(0, mode)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    os.environ.setdefault("PROBATION_DEMO_KEY", "demo-key-not-secret")
    for proto in ("openai", "anthropic"):
        print("== protocol %s" % proto)
        paths = {}
        for srv, mode in zip(servers, ("honest", "shifty")):
            base = "http://127.0.0.1:%d/v1" % srv.server_address[1]
            ep = Endpoint(base, proto, "demo-large", os.environ["PROBATION_DEMO_KEY"], "x-api-key", 10)
            paths[mode] = os.path.join(tmp, "%s-%s.jsonl" % (proto, mode))
            run_probe(ep, 2, 2000, paths[mode], mode, quiet=True)
        ns = argparse.Namespace(run=paths["honest"], ref=paths["honest"], lang="en")
        code_h = cmd_report(ns)
        ns = argparse.Namespace(run=paths["shifty"], ref=paths["honest"], lang="en")
        code_s = cmd_report(ns)
        good = code_h == 0 and code_s == 1
        print("selftest %s: honest exit=%d (want 0), shifty exit=%d (want 1) -> %s\n" % (proto, code_h, code_s, "PASS" if good else "FAIL"))
        ok = ok and good
    card = os.path.join(tmp, "PROBATION.md")
    cmd_card(argparse.Namespace(action="new", path=card, name="demo", owner="me", lang="en", force=False))
    lint_code = cmd_card(argparse.Namespace(action="lint", path=card))
    print("blank card lint exit=%d (want 1) -> %s" % (lint_code, "PASS" if lint_code == 1 else "FAIL"))
    ok = ok and lint_code == 1
    for s in servers:
        s.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="run the probe battery")
    p.add_argument("--base", required=True, help="base URL, e.g. https://api.example.com/v1")
    p.add_argument("--protocol", choices=["openai", "anthropic"], default="openai")
    p.add_argument("--model", required=True)
    p.add_argument("--key-env", required=True, help="name of the env var holding the key")
    p.add_argument("--auth", choices=["x-api-key", "bearer"], default="x-api-key", help="anthropic protocol only")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--long-words", type=int, default=6000, help="size of the long-recall document")
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--label", default="")
    p.add_argument("--out", required=True)

    p = sub.add_parser("report", help="summarise a run")
    p.add_argument("run")
    p.add_argument("--ref")
    p.add_argument("--lang", choices=["en", "zh"], default="en")

    p = sub.add_parser("bill", help="check charges against usage")
    p.add_argument("run")
    p.add_argument("--in-price", type=float, required=True, help="list price per 1M input tokens")
    p.add_argument("--out-price", type=float, required=True, help="list price per 1M output tokens")
    p.add_argument("--cache-price", type=float, help="price per 1M cached input tokens")
    p.add_argument("--multiplier", type=float, default=1.0, help="the multiplier the seller advertised")
    p.add_argument("--charged", type=float, help="what the balance actually dropped by")
    p.add_argument("--ref", help="the same battery on a reference endpoint")
    p.add_argument("--lang", choices=["en", "zh"], default="en")

    p = sub.add_parser("card", help="create or lint a probation card")
    p.add_argument("action", choices=["new", "lint"])
    p.add_argument("--path", default="PROBATION.md")
    p.add_argument("--name")
    p.add_argument("--owner")
    p.add_argument("--lang", choices=["en", "zh"], default="en")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("backup", help="back up agent config files before switching")
    p.add_argument("--dest")
    p.add_argument("files", nargs="*")

    sub.add_parser("selftest", help="rehearse against local fake endpoints")

    a = ap.parse_args(argv)
    if a.cmd == "probe":
        key = os.environ.get(a.key_env)
        if not key:
            print("environment variable %s is empty; export a throwaway key first" % a.key_env)
            return 2
        ep = Endpoint(a.base, a.protocol, a.model, key, a.auth, a.timeout)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        print("probing %s (%s, %s), %d rounds ..." % (ep.url(), a.protocol, a.model, a.rounds))
        run_probe(ep, a.rounds, a.long_words, a.out, a.label or a.model)
        print("evidence written to " + a.out)
        return 0
    return {"report": cmd_report, "bill": cmd_bill, "card": cmd_card, "backup": cmd_backup,
            "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
