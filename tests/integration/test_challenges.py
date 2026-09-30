import json
import unittest

from scenario import *
from certs import check_cert

QUOTE = "return jsonify(user), 200"
CLAIM = "The handler for this requirement is not established by the evidence."
WHY = "The quoted line returns user data and this challenge argues it is not enough to satisfy the requirement."


def challenge(chain, who, aid, rid="REQ-001", claim=CLAIM, eid="E1", quote=QUOTE, why=WHY):
    return chain.tx(who, "challenge_requirement", aid, rid, claim, eid, quote, why)


class BuyerChallengeTests(unittest.TestCase):
    def test_upheld_challenge_flips_a_pass_into_a_failure(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        llm.auditor[("REQ-001", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "FAIL"}
        self.assertEqual(challenge(chain, BUYER, aid), "CH-1:UPHELD")
        a = chain.agreement(aid)
        self.assertEqual((a["status"], a["protocol_result"]), ("VERIFIED_FAIL", "FAIL"))
        req = chain.view("get_requirements", aid)[0]
        self.assertEqual((req["verdict"], req["detail"], req["challenge_count"]), ("FAIL", "CHALLENGE_UPHELD", 1))
        ch = chain.view("get_challenges", aid)[0]
        self.assertEqual((ch["side"], ch["status"], ch["original_status"], ch["resolved_status"]), ("BUYER", "UPHELD", "PASS", "FAIL"))
        self.assertEqual(ch["challenger"], str(BUYER).lower())
        self.assertEqual(ch["quote"], QUOTE)
        self.assertRegex(ch["challenge_hash"], r"^[0-9a-f]{64}$")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        cert = check_cert(chain, aid)
        self.assertEqual((cert["final_verdict"], cert["terminal_state"]), ("FAIL", "REFUNDED"))

    def test_upheld_to_insufficient_evidence(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        llm.auditor[("REQ-001", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "INSUFFICIENT_EVIDENCE"}
        challenge(chain, BUYER, aid)
        self.assertEqual(chain.status(aid), "INSUFFICIENT_EVIDENCE")

    def test_rejected_challenge_changes_nothing_and_settlement_proceeds(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        self.assertEqual(challenge(chain, BUYER, aid), "CH-1:REJECTED")
        self.assertEqual(chain.status(aid), "VERIFIED_PASS")
        self.assertEqual(chain.view("get_requirements", aid)[0]["verdict"], "PASS")
        chain.advance(at.CHALLENGE_WINDOW_STANDARD + 1)
        chain.tx(STRANGER, "settle", aid)
        cert = check_cert(chain, aid)
        self.assertEqual(cert["challenges"][0]["status"], "REJECTED")

    def test_an_invalid_uphold_from_the_auditor_is_treated_as_rejection(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        llm.auditor[("REQ-001", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "PASS"}
        self.assertEqual(challenge(chain, BUYER, aid), "CH-1:REJECTED")
        self.assertEqual(chain.status(aid), "VERIFIED_PASS")

    def test_challenge_after_the_window_is_refused(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        chain.advance(at.CHALLENGE_WINDOW_STANDARD + 1)
        expect_raises(lambda: challenge(chain, BUYER, aid), "deadline has passed")

    def test_duplicate_challenge_by_the_same_party_is_refused(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        challenge(chain, BUYER, aid)
        expect_raises(lambda: challenge(chain, BUYER, aid), "already challenged")
        self.assertEqual(challenge(chain, BUYER, aid, rid="REQ-002"), "CH-2:REJECTED")

    def test_invalid_challenges_are_rejected_before_any_model_call(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        gl.nondet.prompts.clear()
        cases = [
            (dict(rid="REQ-999"), "unknown requirement"),
            (dict(eid="E9"), "existing frozen evidence"),
            (dict(eid=""), "existing frozen evidence"),
            (dict(quote="this text is not in the evidence at all"), "exact quote"),
            (dict(quote="short"), "quote"),
            (dict(claim="too short"), "claim"),
            (dict(why="too short"), "reasoning"),
            (dict(claim="x" * 601), "claim"),
            (dict(quote="\x00" + QUOTE), "control"),
        ]
        for kwargs, fragment in cases:
            expect_raises(lambda k=kwargs: challenge(chain, BUYER, aid, **k), fragment)
        self.assertEqual(gl.nondet.prompts, [])
        self.assertEqual(chain.view("get_challenges", aid), [])

    def test_only_parties_may_challenge_and_only_the_right_side(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        expect_raises(lambda: challenge(chain, STRANGER, aid), "only the buyer or the worker")
        expect_raises(lambda: challenge(chain, JURORS[0], aid), "only the buyer or the worker")
        expect_raises(lambda: challenge(chain, WORKER, aid), "only the buyer can challenge a passing result")

    def test_buyer_cannot_challenge_a_requirement_that_already_fails(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        expect_raises(lambda: challenge(chain, BUYER, aid, rid="REQ-002"), "invalid state")

    def test_challenge_limit(self):
        chain, llm = new_chain()
        aid = create(chain, reqs=REQUIREMENTS[:2])
        to_pending(chain, aid)
        verify_all(chain, aid)
        challenge(chain, BUYER, aid, rid="REQ-001")
        challenge(chain, BUYER, aid, rid="REQ-002")
        self.assertEqual(len(chain.view("get_challenges", aid)), 2)

    def test_challenge_prompt_is_fenced_and_carries_the_claim(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        gl.nondet.prompts.clear()
        challenge(chain, BUYER, aid)
        prompt = gl.nondet.prompts[0]
        self.assertIn("You are the AUDITOR", prompt)
        self.assertIn(CLAIM, prompt)
        self.assertIn("<<<EVIDENCE_START>>>", prompt)
        self.assertIn(at.UNTRUSTED_NOTICE, prompt)


class ChallengePhaseTests(unittest.TestCase):
    def test_worker_challenge_can_restore_a_failed_requirement(self):
        chain, llm, aid = reach("CHALLENGE")
        llm.auditor[("REQ-002", "WORKER")] = {"ruling": "UPHELD", "new_verdict": "PASS", "path": "src/app.py",
                                             "snippet": '@app.route("/users", methods=["POST"])'}
        out = challenge(chain, WORKER, aid, rid="REQ-002", quote='@app.route("/users", methods=["POST"])',
                        claim="The POST /users route is present and returns 201 as required.")
        self.assertEqual(out, "CH-1:UPHELD")
        req = chain.view("get_requirements", aid)[1]
        self.assertEqual((req["verdict"], req["disputed"]), ("PASS", 1))
        a = chain.agreement(aid)
        self.assertEqual((a["status"], a["protocol_result"]), ("CHALLENGE", "PASS"))

    def test_worker_needs_a_grounded_quote_in_the_auditors_answer(self):
        chain, llm, aid = reach("CHALLENGE")
        llm.auditor[("REQ-002", "WORKER")] = {"ruling": "UPHELD", "new_verdict": "PASS", "quotes": []}
        out = challenge(chain, WORKER, aid, rid="REQ-002", quote='@app.route("/users", methods=["POST"])')
        self.assertEqual(out, "CH-1:REJECTED")
        self.assertEqual(chain.view("get_requirements", aid)[1]["verdict"], "FAIL")

    def test_worker_cannot_challenge_a_pass_and_buyer_cannot_challenge_a_fail(self):
        chain, llm, aid = reach("CHALLENGE")
        expect_raises(lambda: challenge(chain, WORKER, aid, rid="REQ-001"), "currently fails")
        expect_raises(lambda: challenge(chain, BUYER, aid, rid="REQ-002"), "currently passes")

    def test_buyer_challenge_in_the_challenge_phase_keeps_the_state(self):
        chain, llm, aid = reach("CHALLENGE")
        llm.auditor[("REQ-001", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "FAIL"}
        challenge(chain, BUYER, aid)
        self.assertEqual(chain.status(aid), "CHALLENGE")
        self.assertEqual(chain.view("get_requirements", aid)[0]["verdict"], "FAIL")

    def test_challenge_after_the_phase_deadline(self):
        chain, llm, aid = reach("CHALLENGE")
        chain.advance(at.CHALLENGE_PHASE + 1)
        expect_raises(lambda: challenge(chain, BUYER, aid), "deadline has passed")

    def test_challenges_are_committed_into_the_seed_of_jury_selection(self):
        chain, llm, aid = reach("CHALLENGE")
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        self.assertEqual(chain.status(aid), "FINAL_REVIEW")


class RedTeamTests(unittest.TestCase):
    def setUp(self):
        self.chain, self.llm = new_chain()
        self.aid = create(self.chain, verification="ADVERSARIAL")
        to_pending(self.chain, self.aid)

    def verify_all_only(self):
        for r in ("REQ-001", "REQ-002", "REQ-003"):
            self.chain.tx(STRANGER, "verify_requirement", self.aid, r)

    def test_aggregate_waits_for_every_red_team_review(self):
        self.verify_all_only()
        expect_raises(lambda: self.chain.tx(STRANGER, "aggregate", self.aid), "red-team")
        for r in ("REQ-001", "REQ-002", "REQ-003"):
            self.assertEqual(self.chain.tx(STRANGER, "red_team_requirement", self.aid, r), "PASS")
        self.assertEqual(self.chain.tx(STRANGER, "aggregate", self.aid), "PASS")
        self.assertEqual(self.chain.status(self.aid), "VERIFIED_PASS")
        window = self.chain.agreement(self.aid)["stage_deadline"] - self.chain.now
        self.assertEqual(window, at.CHALLENGE_WINDOW_ADVERSARIAL)

    def test_a_grounded_counterexample_turns_pass_into_conflicting_evidence(self):
        self.verify_all_only()
        self.llm.redteam["REQ-002"] = {"outcome": "COUNTEREXAMPLE", "path": "src/app.py", "snippet": "return jsonify(user), 201",
                                       "claim": "The handler does not validate its input."}
        self.assertEqual(self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-002"), "INSUFFICIENT_EVIDENCE")
        for r in ("REQ-001", "REQ-003"):
            self.chain.tx(STRANGER, "red_team_requirement", self.aid, r)
        self.assertEqual(self.chain.tx(STRANGER, "aggregate", self.aid), "CONFLICTING_EVIDENCE")
        self.assertEqual(self.chain.status(self.aid), "INSUFFICIENT_EVIDENCE")
        req = self.chain.view("get_requirements", self.aid)[1]
        self.assertEqual((req["detail"], req["redteam"]["outcome"]), ("CONFLICTING_EVIDENCE", "COUNTEREXAMPLE"))
        self.chain.advance(at.DISPUTE_WINDOW + 1)
        self.chain.tx(BUYER, "claim_refund", self.aid)
        cert = check_cert(self.chain, self.aid)
        self.assertEqual(cert["final_verdict"], "CONFLICTING_EVIDENCE")

    def test_an_unsubstantiated_counterexample_is_ignored(self):
        self.verify_all_only()
        self.llm.redteam["REQ-001"] = {"outcome": "COUNTEREXAMPLE", "quotes": [], "claim": "It is broken, trust me."}
        self.assertEqual(self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-001"), "PASS")
        self.assertEqual(self.chain.view("get_requirements", self.aid)[0]["redteam"]["outcome"], "UNSUBSTANTIATED")

    def test_a_fabricated_counterexample_quote_is_ignored(self):
        self.verify_all_only()
        self.llm.redteam["REQ-001"] = {"outcome": "COUNTEREXAMPLE", "quotes": [{"evidence_id": "E1", "quote": "password = 'admin'"}]}
        self.assertEqual(self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-001"), "PASS")

    def test_red_team_rules(self):
        expect_raises(lambda: self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-001"), "only requirements currently judged PASS")
        set_verdicts(self.llm, REQ_001="FAIL")
        self.verify_all_only()
        expect_raises(lambda: self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-001"), "only requirements currently judged PASS")
        self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-002")
        expect_raises(lambda: self.chain.tx(STRANGER, "red_team_requirement", self.aid, "REQ-002"), "already red-teamed")

    def test_red_team_only_applies_to_adversarial_agreements(self):
        chain, llm = new_chain()
        aid = create(chain, verification="STANDARD")
        to_pending(chain, aid)
        chain.tx(STRANGER, "verify_requirement", aid, "REQ-001")
        expect_raises(lambda: chain.tx(STRANGER, "red_team_requirement", aid, "REQ-001"), "ADVERSARIAL")

    def test_missing_red_team_at_the_deadline_is_not_a_pass(self):
        self.verify_all_only()
        self.chain.advance(at.VERIFY_WINDOW + 1)
        self.assertEqual(self.chain.tx(STRANGER, "aggregate", self.aid), "INSUFFICIENT_EVIDENCE")
        self.assertEqual({r["detail"] for r in self.chain.view("get_requirements", self.aid)}, {"RED_TEAM_MISSING"})
        self.chain.advance(at.DISPUTE_WINDOW + 1)
        self.chain.tx(BUYER, "claim_refund", self.aid)
        check_cert(self.chain, self.aid)


if __name__ == "__main__":
    unittest.main()
