"""
Forgeries that recompute every hash (so only the protocol rules can catch them). Each must be INVALID
in both verifiers, and both verifiers must agree row by row.
"""
import copy
import json
import os
import shutil
import unittest

import verify_certificate_loader as vcl
from scenario import reach, vote_all, STRANGER
from harness import at

NODE = shutil.which("node")
sha, canon = vcl.sha, vcl.canon


def reseal(cert):
    c = copy.deepcopy(cert)
    c["policies_hash"] = sha(canon(c["policies"]))
    c["agreement_hash"] = sha(canon({
        "protocol": c["protocol"], "protocol_version": c["protocol_version"], "agreement_id": c["agreement_id"],
        "buyer": c["buyer"], "worker": c["worker"], "currency": c["currency"], "amount": c["amount"], "deadline": c["deadline"],
        "spec_hash": c["specification_hash"], "requirements_hash": c["requirements_hash"], "policies_hash": c["policies_hash"],
        "created_at": c["created_at"]}))
    if c["accepted_at"] > 0:
        c["frozen_hash"] = sha(canon({"agreement_hash": c["agreement_hash"], "accepted_at": c["accepted_at"], "worker": c["worker"]}))
    items = c["evidence"]["items"]
    if items:
        rows = [[i["item_id"], i["kind"], i["source"], i["content_hash"], i["mutable"]] for i in items]
        c["evidence"]["root"] = sha(canon({"agreement_id": c["agreement_id"], "items": rows}))
    c.pop("certificate_hash", None)
    c["certificate_hash"] = sha(canon(c))
    return c


def material():
    chain, llm, aid = reach("FINALIZED")
    fin = (json.loads(chain.view("get_certificate", aid)), {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)})
    chain, llm, aid = reach("SETTLED")
    st = (json.loads(chain.view("get_certificate", aid)), {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)})
    chain, llm, aid = reach("REFUNDED")
    rf = (json.loads(chain.view("get_certificate", aid)), {"evidence": [], "challenges": []})
    return fin, st, rf


def forgeries():
    fin, st, rf = material()
    out = []

    def add(name, base, fn, bundle_fn=None):
        c = copy.deepcopy(base[0])
        b = copy.deepcopy(base[1])
        fn(c)
        if bundle_fn:
            bundle_fn(b)
        out.append((name, reseal(c), b))

    add("jury decision under dispute policy NONE", fin, lambda c: c["policies"].__setitem__("dispute", "NONE"))
    add("settled without acceptance", st, lambda c: (c.__setitem__("accepted_at", 0), c.__setitem__("frozen_hash", "")))
    add("unknown currency", st, lambda c: c.__setitem__("currency", "USD"))
    add("amount below the protocol minimum", st, lambda c: (c.__setitem__("amount", "1"), c["settlement"].__setitem__("to_worker", "1")))
    add("unknown verification policy", st, lambda c: c["policies"].__setitem__("verification", "LAX"))
    add("boolean mutable flag", st, lambda c: c["evidence"]["items"][0].__setitem__("mutable", False))
    add("boolean disputed flag", fin, lambda c: c["requirements"][1].__setitem__("disputed", True))
    add("non-sequential evidence ids", st, lambda c: c["evidence"]["items"][0].__setitem__("item_id", "E7"))

    def refund_with_verdict(c):
        c["final_verdict"] = "FAIL"
    add("refund before acceptance carrying a verdict", rf, refund_with_verdict)

    def beacon_missing(c):
        c["dispute"]["beacon"] = ""
    add("seated jury without a beacon", fin, beacon_missing)
    return out


class ForgedCertificates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = forgeries()

    def test_every_forgery_is_invalid_in_python(self):
        for name, cert, bundle in self.cases:
            self.assertFalse(vcl.verify(json.dumps(cert), bundle, cert["certificate_hash"]).valid(), name)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_every_forgery_is_invalid_in_javascript_with_identical_rows(self):
        from tests.js.test_js_verifier import node_batch, py_rows
        variants = [{"cert": json.dumps(c), "bundle": b, "onchain": c["certificate_hash"]} for _, c, b in self.cases]
        js = node_batch(variants)
        for (name, _, _), v, rows in zip(self.cases, variants, js):
            self.assertEqual(rows, py_rows(v), name)
            self.assertIn("FAIL", [r[1] for r in rows], name)

    def test_an_auditor_record_that_contradicts_the_challenge_outcome_is_caught(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        llm.auditor[("REQ-001", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "FAIL"}
        chain.tx(__import__("scenario").BUYER, "challenge_requirement", aid, "REQ-001",
                 "A long enough claim text here.", "E1", '@app.route("/users", methods=["POST"])',
                 "A sufficiently long piece of reasoning to pass the length check.")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(__import__("scenario").BUYER, "claim_refund", aid)
        cert = json.loads(chain.view("get_certificate", aid))
        bundle = {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)}
        self.assertTrue(vcl.verify(json.dumps(cert), bundle, cert["certificate_hash"]).valid())
        ch = bundle["challenges"][0]
        ch["resolution"]["ruling"] = "REJECTED"
        ch["resolution"]["new_verdict"] = ""
        body = {k: ch[k] for k in ("challenge_id", "requirement_id", "side", "challenger", "claim", "evidence_id", "quote", "reasoning",
                                   "original_status", "status", "resolved_status", "resolution")}
        ch["challenge_hash"] = sha(canon(body))
        cert["challenges"][0]["challenge_hash"] = ch["challenge_hash"]
        cert = reseal(cert)
        self.assertFalse(vcl.verify(json.dumps(cert), bundle, cert["certificate_hash"]).valid())


if __name__ == "__main__":
    unittest.main()
