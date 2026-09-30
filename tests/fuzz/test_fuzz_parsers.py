"""
Garbage-input fuzz and property tests for the pure helpers. Every parser must either
return a well-formed value or raise a plain Exception (a clean revert) -- never a
different failure type, never a malformed success.
"""
import json
import os
import random
import string
import unittest

from harness import at
from scenario import COMMIT_V1, REPO
import verify_certificate_loader as vc

SEED = int(os.environ.get("FUZZ_SEED", "7"))
N = int(os.environ.get("FUZZ_PARSER_CASES", "1500"))
ATOMS = [None, True, False, 0, 1, -1, 2 ** 70, 1.5, "", " ", "x", "REQ-001", "E1", "\u0000", "‮", "😀", "é", "a" * 5000,
         [], {}, [[]], {"kind": "github_file"}, {"kind": 5}, "0x" + "0" * 40, "PASS", "pass ", "COUNTEREXAMPLE"]


def rand_json(rng, depth=0):
    r = rng.random()
    if depth > 3 or r < 0.4:
        return rng.choice(ATOMS)
    if r < 0.7:
        return [rand_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    keys = ["kind", "repository", "commit", "path", "url", "id", "title", "text", "verdict", "outcome", "quotes", "quote",
            "evidence_id", "reason", "claim", "ruling", "new_verdict", "requirement_id", "check", "severity"]
    return {rng.choice(keys): rand_json(rng, depth + 1) for _ in range(rng.randint(0, 6))}


def rand_text(rng):
    alphabet = string.printable + "é‮\u0000😀 "
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))


class ParserFuzz(unittest.TestCase):
    def clean(self, fn, *args):
        try:
            return fn(*args)
        except RecursionError:
            self.fail("recursion on input %r" % (args,))
        except Exception as e:
            self.assertIs(type(e), Exception, "%s raised %s: %s for %r" % (fn.__name__, type(e).__name__, e, str(args)[:200]))
            return None

    def test_evidence_parser(self):
        rng = random.Random(SEED)
        ok = 0
        for _ in range(N):
            raw = json.dumps(rand_json(rng)) if rng.random() < 0.9 else rand_text(rng)
            for policy in ("STRICT", "PERMISSIVE"):
                out = self.clean(at._parse_evidence, raw, policy)
                if out is not None:
                    ok += 1
                    self.assertTrue(1 <= len(out) <= at.MAX_EVIDENCE_ITEMS)
                    ids = [i["evidence_id"] for i in out]
                    self.assertEqual(len(ids), len(set(ids)))
        good = [{"kind": "github_file", "repository": REPO, "commit": COMMIT_V1, "path": "src/app.py"}]
        self.assertEqual(len(at._parse_evidence(json.dumps(good), "STRICT")), 1)

    def test_requirement_parser(self):
        rng = random.Random(SEED + 1)
        for _ in range(N):
            raw = json.dumps(rand_json(rng)) if rng.random() < 0.9 else rand_text(rng)
            out = self.clean(at._parse_requirements, raw)
            if out is not None:
                self.assertTrue(len(out) >= 1)
                ids = [r["requirement_id"] for r in out]
                self.assertEqual(len(ids), len(set(ids)))

    def test_model_output_normalisers_never_escape_their_shape(self):
        rng = random.Random(SEED + 2)
        ev = {"E1": "return jsonify(user), 200\nabort(401)", "E2": "other file content here"}
        ctx = {"evidence": ev, "side": "BUYER", "status": "VERIFIED_PASS"}
        for _ in range(N):
            raw = rand_json(rng)
            if isinstance(raw, dict) and rng.random() < 0.5:
                raw["quotes"] = [{"evidence_id": rng.choice(["E1", "E2", "E9", 3]), "quote": rng.choice(["abort(401)", "return jsonify(user), 200", "zz", None, "x" * 900])}
                                 for _ in range(rng.randint(0, 6))]
            for fn in (at._norm_verifier, at._norm_redteam, at._norm_auditor):
                c = ctx if fn is at._norm_auditor else {"evidence": ev}
                out = self.clean(fn, raw, c)
                if out is None:
                    continue
                for q in out.get("quotes", []):
                    self.assertIn(q["evidence_id"], ev)
                    self.assertTrue(at._grounded(q["quote"], ev[q["evidence_id"]]), "ungrounded quote survived: %r" % (q,))
                self.assertLessEqual(len(out.get("quotes", [])), at.MAX_QUOTES)
        v = at._norm_verifier({"verdict": "PASS", "quotes": [], "reason": "trust me"}, {"evidence": ev})
        self.assertEqual((v["verdict"], v["detail"]), ("INSUFFICIENT_EVIDENCE", "UNGROUNDED_PASS"))

    def test_canonical_json_properties(self):
        rng = random.Random(SEED + 3)
        for _ in range(N):
            obj = rand_json(rng)
            if isinstance(obj, float):
                continue
            a = at._canon(obj)
            self.assertEqual(a, vc.canon(obj))
            self.assertTrue(a.isascii())
            self.assertEqual(json.loads(a), json.loads(json.dumps(obj)))
            self.assertEqual(a, at._canon(json.loads(a)))
            if isinstance(obj, dict) and len(obj) > 1:
                shuffled = dict(reversed(list(obj.items())))
                self.assertEqual(a, at._canon(shuffled))
            self.assertEqual(at._sha(a), vc.sha(a))

    def test_hash_sensitivity(self):
        rng = random.Random(SEED + 4)
        seen = {}
        for _ in range(500):
            t = rand_text(rng)
            h = at._sha(t)
            self.assertEqual(len(h), 64)
            self.assertEqual(seen.setdefault(h, t), t)

    def test_commit_hash_binds_every_field(self):
        base = ("AT-1", "0x" + "a" * 40, "WORKER", "salt-value-1")
        h = at._commit_hash(*base)
        for i, alt in enumerate(("AT-2", "0x" + "b" * 40, "BUYER", "salt-value-2")):
            args = list(base)
            args[i] = alt
            self.assertNotEqual(h, at._commit_hash(*args))
        self.assertNotEqual(at._commit_hash("AT-1", "0x" + "a" * 40, "WORKER", "salt"), at._commit_hash("AT-1", "0x" + "a" * 40, "WORKE", "Rsalt"))

    def test_grounding_normalisation_properties(self):
        rng = random.Random(SEED + 5)
        for _ in range(N):
            t = rand_text(rng)
            q = " ".join(t.split())
            if q:
                self.assertTrue(at._grounded(q, "prefix " + t + " suffix"))
            self.assertFalse(at._grounded("", t))
            self.assertFalse(at._grounded("   ", t))


if __name__ == "__main__":
    unittest.main()
