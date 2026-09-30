import unittest

from scenario import *

EV = {"E1": APP_V1, "E2": AUTH}
CTX = {"evidence": EV, "side": "BUYER", "status": "PASS"}
GOOD = "@require_token"


def q(eid="E1", text=GOOD):
    return {"evidence_id": eid, "quote": text}


class VerifierNormalisationTests(unittest.TestCase):
    def norm(self, **raw):
        return at._norm_verifier(raw, CTX)

    def test_grounded_pass_is_kept(self):
        out = self.norm(verdict="PASS", quotes=[q()], reason="ok")
        self.assertEqual((out["verdict"], out["detail"]), ("PASS", ""))
        self.assertEqual(out["quotes"], [q()])

    def test_pass_without_quotes_is_downgraded(self):
        out = self.norm(verdict="PASS", quotes=[], reason="trust me")
        self.assertEqual((out["verdict"], out["detail"]), ("INSUFFICIENT_EVIDENCE", "UNGROUNDED_PASS"))

    def test_pass_with_fabricated_quote_is_downgraded(self):
        out = self.norm(verdict="PASS", quotes=[q(text="@require_admin_token_and_mfa")])
        self.assertEqual(out["detail"], "UNGROUNDED_PASS")
        self.assertEqual(out["quotes"], [])

    def test_quote_of_the_wrong_item_is_not_grounded(self):
        out = self.norm(verdict="PASS", quotes=[q("E2", "@app.route")])
        self.assertEqual(out["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_unknown_evidence_id_and_bad_types_are_dropped(self):
        raw = [q("E9"), {"evidence_id": 1, "quote": GOOD}, {"evidence_id": "E1", "quote": 5}, "text", None, q()]
        out = self.norm(verdict="PASS", quotes=raw)
        self.assertEqual(out["quotes"], [q()])

    def test_quotes_too_short_or_too_long_are_dropped(self):
        out = self.norm(verdict="PASS", quotes=[q(text="app"), q(text="x" * (at.MAX_QUOTE + 1))])
        self.assertEqual(out["quotes"], [])

    def test_whitespace_and_case_insensitive_grounding(self):
        out = self.norm(verdict="PASS", quotes=[q(text="RETURN   jsonify(user),\n 200")])
        self.assertEqual(out["verdict"], "PASS")

    def test_quote_count_is_capped_and_deduplicated(self):
        many = [q(text="def create_user():"), q(text="def create_user():"), q(text="def get_user(user_id):"),
                q(text="USERS = {}"), q(text="return jsonify(user), 201"), q(text="abort(401)", eid="E2")]
        out = self.norm(verdict="PASS", quotes=many)
        self.assertLessEqual(len(out["quotes"]), at.MAX_QUOTES)
        self.assertEqual(len(out["quotes"]), len({(x["evidence_id"], x["quote"]) for x in out["quotes"]}))

    def test_conflict_needs_two_distinct_items(self):
        one = self.norm(verdict="CONFLICTING_EVIDENCE", quotes=[q()])
        self.assertEqual((one["verdict"], one["detail"]), ("INSUFFICIENT_EVIDENCE", "UNGROUNDED_CONFLICT"))
        two = self.norm(verdict="CONFLICTING_EVIDENCE", quotes=[q(), q("E2", "abort(401)")])
        self.assertEqual((two["verdict"], two["detail"]), ("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"))

    def test_fail_needs_no_quotes(self):
        out = self.norm(verdict="fail", quotes=None, reason="absent")
        self.assertEqual(out["verdict"], "FAIL")

    def test_garbage_is_an_error(self):
        for raw in (None, "PASS", 5, [], {"verdict": "MAYBE"}, {"verdict": None}, {}):
            expect_raises(lambda r=raw: at._norm_verifier(r, CTX))

    def test_reason_is_cleaned_and_bounded(self):
        out = self.norm(verdict="FAIL", reason="a\x00b\nc" + "x" * 2000)
        self.assertLessEqual(len(out["reason"]), at.MAX_REASON)
        self.assertNotIn("\x00", out["reason"])
        self.assertNotIn("\n", out["reason"])

    def test_check_leader_accepts_normalised_and_rejects_tampered(self):
        good = self.norm(verdict="PASS", quotes=[q()])
        self.assertTrue(at._check_verifier(good, CTX))
        forged = dict(good, quotes=[q(text="@require_admin_token")])
        self.assertFalse(at._check_verifier(forged, CTX))
        self.assertFalse(at._check_verifier(dict(good, quotes=[]), CTX))
        self.assertFalse(at._check_verifier(dict(good, verdict="MAYBE"), CTX))
        self.assertFalse(at._check_verifier(dict(good, extra=1), CTX))
        self.assertFalse(at._check_verifier(dict(good, detail="CONFLICTING_EVIDENCE"), CTX))


class RedTeamAndAuditorTests(unittest.TestCase):
    def test_redteam_counterexample_needs_a_grounded_quote(self):
        out = at._norm_redteam({"outcome": "COUNTEREXAMPLE", "claim": "x", "quotes": []}, CTX)
        self.assertEqual(out["outcome"], "UNSUBSTANTIATED")
        out = at._norm_redteam({"outcome": "COUNTEREXAMPLE", "claim": "x", "quotes": [q()]}, CTX)
        self.assertEqual(out["outcome"], "COUNTEREXAMPLE")
        self.assertEqual(at._key_redteam(out), "COUNTEREXAMPLE")
        self.assertEqual(at._key_redteam(at._norm_redteam({"outcome": "NONE_FOUND"}, CTX)), "NO_ATTACK")
        self.assertEqual(at._key_redteam({"outcome": "UNSUBSTANTIATED"}), "NO_ATTACK")

    def test_auditor_rules_by_side(self):
        buyer = dict(CTX, side="BUYER", status="PASS")
        worker = dict(CTX, side="WORKER", status="FAIL")
        up = at._norm_auditor({"ruling": "UPHELD", "new_verdict": "FAIL"}, buyer)
        self.assertEqual((up["ruling"], up["new_verdict"]), ("UPHELD", "FAIL"))
        up = at._norm_auditor({"ruling": "UPHELD", "new_verdict": "PASS"}, buyer)
        self.assertEqual((up["ruling"], up["detail"]), ("REJECTED", "INVALID_UPHOLD"))
        up = at._norm_auditor({"ruling": "UPHELD", "new_verdict": "PASS", "quotes": []}, worker)
        self.assertEqual((up["ruling"], up["detail"]), ("REJECTED", "UNGROUNDED_UPHOLD"))
        up = at._norm_auditor({"ruling": "UPHELD", "new_verdict": "PASS", "quotes": [q()]}, worker)
        self.assertEqual((up["ruling"], up["new_verdict"]), ("UPHELD", "PASS"))
        same = at._norm_auditor({"ruling": "UPHELD", "new_verdict": "FAIL"}, dict(buyer, status="FAIL"))
        self.assertEqual(same["ruling"], "REJECTED")
        self.assertEqual(at._key_auditor(up), "UPHELD")
        self.assertEqual(at._key_auditor(dict(up, new_verdict="FAIL")), at._key_auditor(up))


class DerivationTests(unittest.TestCase):
    def test_overall_rule(self):
        P, F, I = "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"
        self.assertEqual(at._derive_overall([(P, ""), (P, "")]), "PASS")
        self.assertEqual(at._derive_overall([(P, ""), (F, "")]), "FAIL")
        self.assertEqual(at._derive_overall([(I, ""), (F, "")]), "FAIL")
        self.assertEqual(at._derive_overall([(P, ""), (I, "")]), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(at._derive_overall([(P, ""), (I, "CONFLICTING_EVIDENCE")]), "CONFLICTING_EVIDENCE")
        self.assertEqual(at._derive_overall([(I, "CONFLICTING_EVIDENCE"), (F, "")]), "FAIL")
        self.assertEqual(at._derive_overall([("UNVERIFIED", "")]), "INSUFFICIENT_EVIDENCE")

    def test_bond_scales_with_amount(self):
        self.assertEqual(at._bond_for(GEN), at.DISPUTE_BOND_MIN)
        self.assertEqual(at._bond_for(1000 * GEN), 50 * GEN)

    def test_draw_index_is_deterministic_and_in_range(self):
        b = "ab" * 32
        idx = [at._draw_index(b, "AT-1", k, 7) for k in range(200)]
        self.assertEqual(idx, [at._draw_index(b, "AT-1", k, 7) for k in range(200)])
        self.assertEqual(set(idx), set(range(7)))
        self.assertNotEqual(idx, [at._draw_index("cd" * 32, "AT-1", k, 7) for k in range(200)])

    def test_beacon_round_arithmetic(self):
        for t in (at.BEACON_GENESIS + 1, 1_800_000_000, 1_800_000_030, 1_800_000_031):
            r = at._beacon_round(t)
            self.assertGreaterEqual(at._beacon_time(r), t)
            self.assertLess(at._beacon_time(r) - t, at.BEACON_PERIOD)
        self.assertEqual(at._beacon_time(1), at.BEACON_GENESIS)


if __name__ == "__main__":
    unittest.main()
