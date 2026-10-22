"""Offline tests: python3 -m unittest discover -s tests -v"""
import argparse
import io
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import probation  # noqa: E402
import mock_endpoint  # noqa: E402


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*a)
    return code, buf.getvalue()


class Stats(unittest.TestCase):
    def test_wilson_bounds(self):
        lo, hi = probation.wilson(16, 20)
        self.assertAlmostEqual(lo, 0.584, places=2)
        self.assertAlmostEqual(hi, 0.919, places=2)

    def test_fisher_symmetric(self):
        self.assertAlmostEqual(probation.fisher_two_sided(16, 4, 8, 12), 0.022, places=2)
        self.assertEqual(probation.fisher_two_sided(5, 0, 5, 0), 1.0)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.servers = {}
        for mode in ("honest", "shifty"):
            s = mock_endpoint.serve(0, mode)
            threading.Thread(target=s.serve_forever, daemon=True).start()
            cls.servers[mode] = s

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers.values():
            s.shutdown()
            s.server_close()

    def run_mode(self, mode, proto):
        port = self.servers[mode].server_address[1]
        ep = probation.Endpoint("http://127.0.0.1:%d/v1" % port, proto, "demo-large", "k", "x-api-key", 10)
        out = os.path.join(self.tmp, "%s-%s.jsonl" % (mode, proto))
        probation.run_probe(ep, 2, 2000, out, mode, quiet=True)
        return out

    def test_honest_is_clean_and_shifty_fails(self):
        for proto in ("openai", "anthropic"):
            ref = self.run_mode("honest", proto)
            bad = self.run_mode("shifty", proto)
            code, _ = quiet(probation.cmd_report, argparse.Namespace(run=ref, ref=ref, lang="en"))
            self.assertEqual(code, 0, proto)
            code, text = quiet(probation.cmd_report, argparse.Namespace(run=bad, ref=ref, lang="en"))
            self.assertEqual(code, 1, proto)
            self.assertIn("unknown model name was accepted", text)
            self.assertIn("long-document recall 0/", text)

    def test_key_never_written(self):
        port = self.servers["honest"].server_address[1]
        ep = probation.Endpoint("http://127.0.0.1:%d/v1" % port, "openai", "demo-large", "sk-SECRET-123", "x-api-key", 10)
        out = os.path.join(self.tmp, "k.jsonl")
        probation.run_probe(ep, 1, 500, out, "k", quiet=True)
        with open(out) as fh:
            self.assertNotIn("sk-SECRET-123", fh.read())


class Cards(unittest.TestCase):
    def test_examples_lint(self):
        for name in ("claude-code-gateway.en.md", "miniprogram-relay.zh-CN.md"):
            path = os.path.join(HERE, "..", "examples", name)
            code, text = quiet(probation.cmd_card, argparse.Namespace(action="lint", path=path))
            self.assertEqual(code, 0, text)

    def test_blank_card_fails(self):
        path = os.path.join(tempfile.mkdtemp(), "P.md")
        quiet(probation.cmd_card, argparse.Namespace(action="new", path=path, name="x", owner="y", lang="zh", force=False))
        code, text = quiet(probation.cmd_card, argparse.Namespace(action="lint", path=path))
        self.assertEqual(code, 1)

    def test_cleared_on_gap_fails(self):
        path = os.path.join(HERE, "..", "examples", "claude-code-gateway.en.md")
        text = open(path).read().replace("| [ran] |\n| Identity", "| [gap] |\n| Identity")
        p2 = os.path.join(tempfile.mkdtemp(), "P.md")
        open(p2, "w").write(text)
        code, out = quiet(probation.cmd_card, argparse.Namespace(action="lint", path=p2))
        self.assertEqual(code, 1)
        self.assertIn("[gap]", out)


if __name__ == "__main__":
    unittest.main()
