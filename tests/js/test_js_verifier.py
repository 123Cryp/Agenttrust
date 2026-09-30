"""
Conformance: the JavaScript verifier (frontend/assets/verify.js) must reach exactly the same
check-by-check outcome as the Python verifier on valid certificates and on thousands of
randomly corrupted ones, including unicode, whitespace and big-number edge cases.
"""
import copy
import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

import verify_certificate_loader as vcl
from scenario import reach, vote_all
from harness import at
from certs import check_cert

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODE = shutil.which("node")
RUNNER = os.path.join(ROOT, "tests", "js", "batch_runner.js")


def node_batch(variants):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(variants, f)
        path = f.name
    try:
        p = subprocess.run([NODE, RUNNER, path], capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            raise AssertionError("node failed: " + p.stderr[-2000:])
        return json.loads(p.stdout)
    finally:
        os.unlink(path)


def py_rows(variant):
    rep = vcl.verify(variant["cert"], variant["bundle"], variant["onchain"])
    return [[name, status] for name, status, _ in rep.rows]


def mutate(node, rng, path=()):
    """Return a deep copy of node with one random leaf changed."""
    node = copy.deepcopy(node)
    leaves = []

    def walk(x, p):
        if isinstance(x, dict):
            for k in x:
                walk(x[k], p + (k,))
        elif isinstance(x, list):
            for i, y in enumerate(x):
                walk(y, p + (i,))
        else:
            leaves.append(p)

    walk(node, ())
    if not leaves:
        return node
    target = rng.choice(leaves)
    parent = node
    for k in target[:-1]:
        parent = parent[k]
    old = parent[target[-1]]
    if isinstance(old, bool):
        new = not old
    elif isinstance(old, int):
        new = rng.choice([old + 1, old - 1, 0, old * 2, -old, bool(old), str(old)])
    elif isinstance(old, str):
        new = rng.choice([old + "x", old[:-1], "", old.upper(), old + "é", " " + old, old.replace("0", "1", 1), "0" * 64, old + "\n"])
    else:
        new = rng.choice(["x", 0, [], {}])
    parent[target[-1]] = new
    return node


@unittest.skipUnless(NODE, "node is not installed")
class JsVerifierConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = []
        for state, kw in (("SETTLED", {"verification": "ADVERSARIAL"}), ("FINALIZED", {}), ("REFUNDED", {}), ("CANCELLED", {}), ("TIMEOUT", {}),
                          ("VERIFIED_PASS", {})):
            chain, llm, aid = reach(state, **kw)
            if state in ("VERIFIED_PASS", "TIMEOUT", "CANCELLED"):
                if state == "TIMEOUT":
                    chain.tx(chain.now and __import__("scenario").BUYER, "claim_refund", aid)
                elif state == "CANCELLED":
                    continue
                else:
                    continue
            cls.samples.append({"cert": chain.view("get_certificate", aid),
                                "bundle": {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)},
                                "onchain": chain.view("get_certificate_hash", aid)})
        chain, llm, aid = reach("CANCELLED")
        cls.samples.append({"cert": chain.view("get_certificate", aid) or "", "bundle": None, "onchain": None})

    def test_valid_certificates_agree_and_pass(self):
        real = [s for s in self.samples if s["cert"]]
        self.assertGreaterEqual(len(real), 3)
        js = node_batch(real)
        for s, rows in zip(real, js):
            self.assertEqual(rows, py_rows(s))
            self.assertTrue(all(status != "FAIL" for _, status in rows), rows)

    def test_corrupted_certificates_agree_check_by_check(self):
        rng = random.Random(int(os.environ.get("FUZZ_SEED", "11")))
        variants = []
        for s in [s for s in self.samples if s["cert"]]:
            cert = json.loads(s["cert"])
            for _ in range(int(os.environ.get("JS_CONFORMANCE_CASES", "250"))):
                m = mutate(cert, rng)
                variants.append({"cert": json.dumps(m), "bundle": s["bundle"], "onchain": s["onchain"], "changed": m != cert})
            for _ in range(60):
                bundle = mutate(s["bundle"], rng) if s["bundle"] else None
                variants.append({"cert": s["cert"], "bundle": bundle, "onchain": s["onchain"], "changed": bundle != s["bundle"]})
            variants.append({"cert": s["cert"], "bundle": s["bundle"], "onchain": "0" * 64, "changed": True})
            variants.append({"cert": s["cert"][:-5], "bundle": None, "onchain": None, "changed": True})
            variants.append({"cert": "[]", "bundle": None, "onchain": None, "changed": True})
        js = node_batch(variants)
        changed = 0
        for v, rows in zip(variants, js):
            expected = py_rows(v)
            js_fail = any(status == "FAIL" for _, status in rows)
            py_fail = any(status == "FAIL" for _, status in expected)
            self.assertEqual(js_fail, py_fail, "verifiers disagree on validity: %s" % json.dumps(v)[:400])
            if rows != expected:
                # a malformed document may abort one implementation earlier than the other; both must then have reported a FAIL
                self.assertTrue(js_fail and py_fail and len(rows) != len(expected), "verifiers disagree on %s" % json.dumps(v)[:400])
            if v["changed"]:
                changed += 1
                self.assertTrue(js_fail, "a corrupted input was accepted: %s" % json.dumps(v)[:400])
        self.assertGreater(changed, 500)

    def test_primitives_agree(self):
        rng = random.Random(3)
        texts = ["", "abc", "éè", "\U0001f600 emoji", "line\nbreak\ttab", "\x7f del", "  ", "\x1c\x1d\x1e\x1f", "A B　C",
                 "İstanbul", "ǅ", "ﬁ ligature", "\u0000nul"] + ["".join(chr(rng.randint(1, 0x2fff)) for _ in range(rng.randint(0, 20))) for _ in range(300)]
        script = ("const v=require('%s/frontend/assets/verify.js');const t=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));"
                  "process.stdout.write(JSON.stringify(t.map(x=>[v.sha(x),v.canon({k:x,'é':[x]}),v.normWs(x)])));" % ROOT)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(texts, f)
            path = f.name
        try:
            out = json.loads(subprocess.run([NODE, "-e", script, path], capture_output=True, text=True, check=True).stdout)
        finally:
            os.unlink(path)
        for x, (h, c, n) in zip(texts, out):
            self.assertEqual(h, vcl.sha(x), repr(x))
            self.assertEqual(c, vcl.canon({"k": x, "é": [x]}), repr(x))
            self.assertEqual(n, vcl.module.norm_ws(x), repr(x))


if __name__ == "__main__":
    unittest.main()
