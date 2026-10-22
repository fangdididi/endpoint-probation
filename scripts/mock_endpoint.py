#!/usr/bin/env python3
"""A tiny fake model endpoint for rehearsing a probation run without spending money.

It speaks just enough of the OpenAI-style chat API and the Anthropic-style
messages API for probation.py to exercise every probe.

Two personalities:
  honest   counts tokens consistently, keeps the whole prompt, ends every
           stream properly, rejects unknown models with a 4xx.
  shifty   inflates token counts, silently drops the start of long prompts,
           sometimes hides an error inside a 200 stream, and ends some
           streams without a completion marker.

Usage:
  python3 mock_endpoint.py --port 8765 --mode honest
"""
import argparse
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KNOWN_MODELS = {"demo-large", "demo-small"}


def count_tokens(text, mode):
    # crude but stable: one token per 4 chars, CJK chars count as one each
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    rest = len(re.sub(r"[\u4e00-\u9fff]", "", text))
    n = cjk + max(1, rest // 4)
    if mode == "shifty":
        n = int(n * 1.45) + 3
    return n


def answer_for(prompt, mode):
    if mode == "shifty" and len(prompt) > 6000:
        prompt = prompt[len(prompt) // 2:]  # silent window cut
    m = re.search(r"The code word is ([A-Z]+-\d+)", prompt)
    if "code word" in prompt.lower() and "what was" in prompt.lower():
        return m.group(1) if m else "I could not find a code word in the document."
    if "count from one" in prompt.lower():
        return ", ".join(str(i) for i in range(1, 41))
    return "ok"


class Handler(BaseHTTPRequestHandler):
    mode = "honest"
    calls = 0
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _send_json(self, code, obj, extra=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("x-request-id", "req_%06d" % random.randint(0, 999999))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        with Handler.lock:
            Handler.calls += 1
            nth = Handler.calls
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            return self._send_json(400, {"error": {"type": "invalid_request", "message": "bad json"}})
        anthropic = self.path.rstrip("/").endswith("/messages")
        model = req.get("model", "")
        if model not in KNOWN_MODELS:
            if self.mode == "shifty":
                # quietly answers with some other model instead of refusing
                model = "demo-small"
            else:
                return self._send_json(404, {"error": {"type": "not_found", "message": "model %s does not exist" % model}})
        if int(req.get("max_tokens", 16)) > 100000:
            return self._send_json(400, {"error": {"type": "invalid_request", "message": "max_tokens must be <= 8192 for this model"}})
        msgs = req.get("messages", [])
        prompt = "\n".join(m.get("content", "") if isinstance(m.get("content"), str) else
                           " ".join(p.get("text", "") for p in m.get("content", [])) for m in msgs)
        text = answer_for(prompt, self.mode)
        pt = count_tokens(prompt, self.mode)
        ct = count_tokens(text, self.mode)
        if self.mode == "shifty" and len(prompt) > 6000:
            pt = pt // 2
        stream = bool(req.get("stream"))
        if not stream:
            if anthropic:
                return self._send_json(200, {"id": "msg_x", "type": "message", "model": model,
                                             "content": [{"type": "text", "text": text}],
                                             "stop_reason": "end_turn",
                                             "usage": {"input_tokens": pt, "output_tokens": ct}})
            return self._send_json(200, {"id": "chatcmpl-x", "object": "chat.completion", "model": model,
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}})
        # streaming
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("x-request-id", "req_%06d" % random.randint(0, 999999))
        self.end_headers()
        pieces = re.findall(r"\S+\s*", text) or [text]
        hide_error = self.mode == "shifty" and nth % 3 == 0
        cut_short = self.mode == "shifty" and nth % 4 == 0
        first_delay = 0.05 if self.mode == "honest" else 0.35

        def emit(obj, event=None):
            chunk = ""
            if event:
                chunk += "event: %s\n" % event
            chunk += "data: %s\n\n" % (obj if isinstance(obj, str) else json.dumps(obj))
            self.wfile.write(chunk.encode())
            self.wfile.flush()

        try:
            if anthropic:
                emit({"type": "message_start", "message": {"model": model, "usage": {"input_tokens": pt}}}, "message_start")
            time.sleep(first_delay)
            if hide_error:
                if anthropic:
                    emit({"type": "error", "error": {"type": "overloaded_error", "message": "upstream pool exhausted"}}, "error")
                else:
                    emit({"error": {"message": "upstream rate limit exceeded", "code": 429}})
                    emit("[DONE]")
                return
            for i, p in enumerate(pieces):
                if cut_short and i > len(pieces) // 2:
                    break
                if anthropic:
                    emit({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}}, "content_block_delta")
                else:
                    emit({"choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]})
                time.sleep(0.005)
            if cut_short:
                return  # connection closes with no completion marker
            if anthropic:
                emit({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": ct}}, "message_delta")
                emit({"type": "message_stop"}, "message_stop")
            else:
                emit({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                emit({"choices": [], "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}})
                emit("[DONE]")
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(port, mode):
    handler = type("H", (Handler,), {"mode": mode, "calls": 0})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--mode", choices=["honest", "shifty"], default="honest")
    a = ap.parse_args()
    s = serve(a.port, a.mode)
    print("mock endpoint (%s) on http://127.0.0.1:%d" % (a.mode, a.port))
    s.serve_forever()
