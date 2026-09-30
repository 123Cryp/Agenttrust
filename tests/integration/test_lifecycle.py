import json
import unittest

from scenario import *
from certs import check_cert

BOND = at._bond_for(10 * GEN)


def wallet(chain, who):
    return chain.wallets[str(who).lower()]


def withdraw_all(chain, who):
    if int(chain.view("get_balance", str(who))) > 0:
        return chain.tx(who, "withdraw")
    return 0


class HappyPathTests(unittest.TestCase):
    def test_full_path_to_settlement(self):
        chain, llm = new_chain()
        aid = create(chain)
        trail = [chain.status(aid)]

        def step(fn):
            fn()
            trail.append(chain.status(aid))

        step(lambda: chain.tx(BUYER, "fund", aid, value=10 * GEN))
        step(lambda: chain.tx(WORKER, "accept", aid))
        step(lambda: chain.tx(WORKER, "start_work", aid))
        step(lambda: chain.tx(WORKER, "submit_deliverable", aid, "Each requirement is satisfied by src/app.py and src/auth.py.", default_evidence()))
        step(lambda: freeze_all(chain, aid))
        for r in ("REQ-001", "REQ-002", "REQ-003"):
            chain.tx(STRANGER, "verify_requirement", aid, r)
        step(lambda: chain.tx(STRANGER, "aggregate", aid))
        chain.advance(at.CHALLENGE_WINDOW_STANDARD + 1)
        step(lambda: chain.tx(STRANGER, "settle", aid))
        self.assertEqual(trail, ["CREATED", "FUNDED", "ACCEPTED", "IN_PROGRESS", "DELIVERED", "VERIFICATION_PENDING",
                                 "VERIFIED_PASS", "SETTLED"])
        a = chain.agreement(aid)
        self.assertEqual((a["settle_worker"], a["settle_buyer"]), (str(10 * GEN), "0"))
        self.assertEqual(a["protocol_result"], "PASS")
        chain.tx(WORKER, "withdraw")
        self.assertEqual(wallet(chain, WORKER), 10 * GEN)
        acc = chain.ledger_ok()
        self.assertEqual(int(acc["escrow_locked"]) + int(acc["claimable_total"]), 0)
        cert = check_cert(chain, aid)
        self.assertEqual((cert["final_verdict"], cert["terminal_state"]), ("PASS", "SETTLED"))
        self.assertIn("not a guarantee", cert["statement"])

    def test_agreement_becomes_frozen_at_acceptance(self):
        chain, llm = new_chain()
        aid = create(chain)
        self.assertEqual(chain.agreement(aid)["frozen_hash"], "")
        chain.tx(BUYER, "fund", aid, value=10 * GEN)
        self.assertEqual(chain.agreement(aid)["frozen_hash"], "")
        chain.tx(WORKER, "accept", aid)
        a = chain.agreement(aid)
        expected = at._sha(at._canon({"agreement_hash": a["agreement_hash"], "accepted_at": a["accepted_at"], "worker": a["worker"]}))
        self.assertEqual(a["frozen_hash"], expected)

    def test_settle_only_after_the_challenge_window(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "challenge window is still open")
        chain.advance(at.CHALLENGE_WINDOW_STANDARD)
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "challenge window is still open")
        chain.advance(1)
        chain.tx(STRANGER, "settle", aid)

    def test_all_five_demo_requirements_pass_fail_and_insufficient(self):
        chain, llm = new_chain()
        aid = create(chain, reqs=REQUIREMENTS)
        to_pending(chain, aid, evidence_json(COMMIT_V1, ["src/app.py", "src/auth.py"]))
        set_verdicts(llm, REQ_004="FAIL", REQ_005="INSUFFICIENT_EVIDENCE")
        self.assertEqual(verify_all(chain, aid), "FAIL")
        got = {r["requirement_id"]: r["verdict"] for r in chain.view("get_requirements", aid)}
        self.assertEqual(got, {"REQ-001": "PASS", "REQ-002": "PASS", "REQ-003": "PASS", "REQ-004": "FAIL",
                               "REQ-005": "INSUFFICIENT_EVIDENCE"})
        self.assertEqual(chain.status(aid), "VERIFIED_FAIL")

    def test_requirements_are_verified_individually_with_their_own_prompts(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        gl.nondet.prompts.clear()
        chain.tx(STRANGER, "verify_requirement", aid, "REQ-002")
        self.assertTrue(gl.nondet.prompts)
        for p in gl.nondet.prompts:
            self.assertIn("REQUIREMENT ID: REQ-002", p)
            self.assertNotIn("REQUIREMENT ID: REQ-001", p)
        self.assertEqual([r["status"] for r in chain.view("get_requirements", aid)], ["UNVERIFIED", "PASS", "UNVERIFIED"])

    def test_a_verified_requirement_cannot_be_verified_again(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        chain.tx(STRANGER, "verify_requirement", aid, "REQ-001")
        expect_raises(lambda: chain.tx(STRANGER, "verify_requirement", aid, "REQ-001"), "already verified")
        expect_raises(lambda: chain.tx(STRANGER, "verify_requirement", aid, "REQ-999"), "unknown requirement")

    def test_aggregate_needs_every_requirement(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        chain.tx(STRANGER, "verify_requirement", aid, "REQ-001")
        expect_raises(lambda: chain.tx(STRANGER, "aggregate", aid), "not verified yet")


class UndisputedFailureTests(unittest.TestCase):
    def test_failed_verification_refunds_the_buyer_after_the_dispute_window(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        expect_raises(lambda: chain.tx(BUYER, "claim_refund", aid), "dispute window is still open")
        chain.advance(at.DISPUTE_WINDOW + 1)
        expect_raises(lambda: chain.tx(WORKER, "claim_refund", aid), "only the buyer")
        self.assertEqual(chain.tx(BUYER, "claim_refund", aid), "REFUNDED")
        chain.tx(BUYER, "withdraw")
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)
        chain.ledger_ok()
        cert = check_cert(chain, aid)
        self.assertEqual((cert["final_verdict"], cert["terminal_state"]), ("FAIL", "REFUNDED"))

    def test_insufficient_evidence_never_pays_the_worker(self):
        chain, llm, aid = reach("INSUFFICIENT_EVIDENCE")
        self.assertEqual(chain.agreement(aid)["protocol_result"], "INSUFFICIENT_EVIDENCE")
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "invalid state")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        self.assertEqual(wallet(chain, WORKER), 0)
        self.assertEqual(chain.agreement(aid)["settle_worker"], "0")

    def test_dispute_policy_none_refunds_immediately(self):
        chain, llm = new_chain()
        aid = create(chain, dispute="NONE")
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        out = chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=BOND)
        self.assertTrue(out.startswith("REJECTED"))
        chain.tx(BUYER, "claim_refund", aid)
        self.assertEqual(chain.status(aid), "REFUNDED")


FEE = BOND // 2
COLLATERAL = BOND - FEE
S = at.JUROR_STAKE


def dispute_without_jury(pool, side="WORKER"):
    chain, llm = new_chain(jurors=pool)
    aid = create(chain)
    to_pending(chain, aid)
    if side == "WORKER":
        set_verdicts(llm, REQ_002="FAIL")
    verify_all(chain, aid)
    rid = "REQ-002" if side == "WORKER" else "REQ-001"
    who = WORKER if side == "WORKER" else BUYER
    assert chain.tx(who, "open_dispute", aid, rid, "The verdict on this requirement is wrong.", value=BOND) == "DISPUTED"
    chain.advance(at.RESPONSE_WINDOW + 1)
    chain.tx(STRANGER, "start_challenge_phase", aid)
    return chain, llm, aid


class DisputeTests(unittest.TestCase):
    def finish(self, votes, **kw):
        chain, llm, aid = reach("FINAL_REVIEW")
        jurors = vote_all(chain, aid, votes)
        chain.tx(STRANGER, "finalize_dispute", aid)
        return chain, aid, jurors

    def collect(self, chain, aid):
        for who in [WORKER, BUYER, OWNER] + JURORS:
            withdraw_all(chain, who)
        chain.ledger_ok()

    def test_worker_prevails_recovers_the_collateral_and_the_fee_pays_the_majority(self):
        chain, aid, jurors = self.finish(["WORKER", "WORKER", "BUYER"])
        d = chain.view("get_dispute", aid)
        self.assertEqual(d["result"], "WORKER_PREVAILED")
        self.assertEqual(chain.status(aid), "FINALIZED")
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, WORKER), 10 * GEN + COLLATERAL)
        self.assertEqual(wallet(chain, BUYER), 0)
        self.assertEqual([wallet(chain, j) for j in jurors], [FEE // 2, FEE // 2, 0])
        for j in jurors:
            acc = chain.view("get_juror", j)
            self.assertEqual((acc["stake"], acc["open_seats"]), (str(S), 0))
        cert = check_cert(chain, aid)
        self.assertEqual(cert["dispute"]["result"], "WORKER_PREVAILED")

    def test_buyer_prevails_and_receives_the_losing_collateral(self):
        chain, aid, jurors = self.finish(["BUYER", "BUYER", "WORKER"])
        self.collect(chain, aid)
        self.assertEqual(chain.view("get_dispute", aid)["result"], "BUYER_PREVAILED")
        self.assertEqual(wallet(chain, BUYER), 10 * GEN + COLLATERAL)
        self.assertEqual(wallet(chain, WORKER), 0)
        self.assertEqual([wallet(chain, j) for j in jurors], [FEE // 2, FEE // 2, 0])

    def test_jurors_are_paid_whichever_side_wins(self):
        for votes in (["WORKER"] * 3, ["BUYER"] * 3):
            chain, aid, jurors = self.finish(votes)
            self.collect(chain, aid)
            self.assertEqual([wallet(chain, j) for j in jurors], [FEE // 3] * 3)

    def test_tie_falls_back_to_the_automated_result_and_non_revealers_are_slashed_to_the_revealers(self):
        chain, aid, jurors = self.finish(["WORKER", "BUYER", None])
        self.assertEqual(chain.view("get_dispute", aid)["result"], "DEADLOCK_FALLBACK")
        self.collect(chain, aid)
        a = chain.agreement(aid)
        self.assertEqual(a["protocol_result"], "FAIL")
        self.assertEqual((a["settle_worker"], a["settle_buyer"]), ("0", str(10 * GEN)))
        self.assertEqual(wallet(chain, WORKER), COLLATERAL)
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)
        self.assertEqual([wallet(chain, j) for j in jurors], [(FEE + S) // 2, (FEE + S) // 2, 0])
        slashed = chain.view("get_juror", jurors[2])
        self.assertEqual(slashed["stake"], "0")
        self.assertGreater(slashed["removed_at"], 0)
        check_cert(chain, aid)

    def test_below_quorum_falls_back_to_the_automated_result(self):
        chain, aid, jurors = self.finish(["BUYER", None, None])
        self.assertEqual(chain.view("get_dispute", aid)["result"], "DEADLOCK_FALLBACK")
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, jurors[0]), FEE + 2 * S)
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)

    def test_nobody_reveals_stakes_go_to_treasury_and_the_disputer_gets_the_whole_bond_back(self):
        chain, aid, jurors = self.finish([None, None, None])
        self.assertEqual(chain.view("get_dispute", aid)["result"], "DEADLOCK_FALLBACK")
        acc = chain.ledger_ok()
        self.assertEqual(int(acc["treasury"]), 3 * S)
        expect_raises(lambda: chain.tx(WORKER, "withdraw_treasury"), "only the owner")
        chain.tx(OWNER, "withdraw_treasury")
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, OWNER), 3 * S)
        self.assertEqual(wallet(chain, WORKER), BOND)
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)

    def test_a_slashed_juror_is_never_seated_again(self):
        chain, llm = new_chain(jurors=4)
        seated_twice = []
        for round_no in range(2):
            aid = create(chain)
            to_pending(chain, aid)
            set_verdicts(llm, REQ_002="FAIL")
            verify_all(chain, aid)
            open_and_seat(chain, aid, side_requirements="REQ-002")
            jurors = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
            seated_twice.append(jurors)
            vote_all(chain, aid, ["WORKER", "WORKER", None] if round_no == 0 else ["WORKER"] * 3)
            chain.tx(STRANGER, "finalize_dispute", aid)
            chain.advance(10)
        self.assertNotIn(seated_twice[0][2], seated_twice[1])
        chain.ledger_ok()

    def test_odd_amount_deadlock_returns_the_whole_amount_without_rounding_loss(self):
        chain, llm = new_chain()
        aid = create(chain, amount=10 * GEN + 1)
        to_pending(chain, aid, amount=10 * GEN + 1)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        bond = at._bond_for(10 * GEN + 1)
        chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=bond)
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        vote_all(chain, aid, [None, None, None])
        chain.tx(STRANGER, "finalize_dispute", aid)
        a = chain.agreement(aid)
        self.assertEqual((int(a["settle_worker"]), int(a["settle_buyer"])), (0, 10 * GEN + 1))
        chain.ledger_ok()

    def test_too_small_a_pool_means_no_jury_and_the_automated_fail_stands(self):
        chain, llm, aid = dispute_without_jury(2)
        chain.advance(SEAT_WAIT)
        self.assertEqual(chain.tx(STRANGER, "seat_jury", aid), "FINALIZED")
        self.assertEqual(chain.view("get_dispute", aid)["result"], "NO_JURY_FALLBACK")
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, WORKER), BOND)
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)
        self.assertEqual(chain.view("get_juror", str(JURORS[0]))["stake"], str(S))
        check_cert(chain, aid)

    def test_no_jury_after_a_buyer_dispute_pays_the_worker_in_full(self):
        chain, llm, aid = dispute_without_jury(0, side="BUYER")
        chain.advance(SEAT_WAIT)
        self.assertEqual(chain.tx(STRANGER, "seat_jury", aid), "FINALIZED")
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, WORKER), 10 * GEN)
        self.assertEqual(wallet(chain, BUYER), BOND)
        cert = check_cert(chain, aid)
        self.assertEqual((cert["dispute"]["result"], cert["settlement"]["to_worker"]), ("NO_JURY_FALLBACK", str(10 * GEN)))

    def test_no_jury_uses_the_verdict_after_upheld_challenges(self):
        chain, llm, aid = dispute_without_jury(0)
        llm.auditor[("REQ-002", "WORKER")] = {"ruling": "UPHELD", "new_verdict": "PASS", "path": "src/app.py",
                                             "snippet": '@app.route("/users", methods=["POST"])'}
        out = chain.tx(WORKER, "challenge_requirement", aid, "REQ-002", "The POST /users route is present and returns 201 as required.",
                       "E1", '@app.route("/users", methods=["POST"])',
                       "The frozen source shows the requirement implemented exactly as the specification asks for it.")
        self.assertEqual(out, "CH-1:UPHELD")
        self.assertEqual(chain.agreement(aid)["protocol_result"], "PASS")
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, WORKER), 10 * GEN + BOND)
        check_cert(chain, aid)

    def test_a_late_upheld_challenge_gives_the_other_side_time_to_reply(self):
        chain, llm, aid = dispute_without_jury(3, side="BUYER")
        deadline = chain.agreement(aid)["stage_deadline"]
        chain.now = deadline
        llm.auditor[("REQ-002", "BUYER")] = {"ruling": "UPHELD", "new_verdict": "FAIL"}
        out = chain.tx(BUYER, "challenge_requirement", aid, "REQ-002", "The POST handler does not return 201 at all.",
                       "E1", '@app.route("/users", methods=["POST"])',
                       "The frozen source shows the handler returning a different status than the specification demands.")
        self.assertEqual(out, "CH-1:UPHELD")
        self.assertEqual(chain.agreement(aid)["stage_deadline"], deadline + at.REPLY_WINDOW)
        chain.advance(60)
        llm.auditor[("REQ-002", "WORKER")] = {"ruling": "UPHELD", "new_verdict": "PASS", "path": "src/app.py",
                                             "snippet": '@app.route("/users", methods=["POST"])'}
        out = chain.tx(WORKER, "challenge_requirement", aid, "REQ-002", "The POST /users route is present and returns 201 as required.",
                       "E1", '@app.route("/users", methods=["POST"])',
                       "The frozen source shows the requirement implemented exactly as the specification asks for it.")
        self.assertEqual(out, "CH-2:UPHELD")
        self.assertEqual(chain.agreement(aid)["protocol_result"], "PASS")

    def test_selection_is_reproducible_from_the_beacon_and_the_pool_snapshot(self):
        chain, llm = new_chain(jurors=8)
        aid = create(chain)
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        open_and_seat(chain, aid, side_requirements="REQ-002")
        d = chain.view("get_dispute", aid)
        pool = [str(j).lower() for j in JURORS[:8]]
        expected, k = [], 0
        while len(expected) < at.JURY_SIZE:
            who = pool[at._draw_index(d["beacon"], aid, k, d["pool_size"])]
            if who not in expected:
                expected.append(who)
            k += 1
        self.assertEqual([j["address"] for j in d["jurors"]], expected)
        for j in JURORS[:8]:
            if str(j).lower() not in expected:
                self.assertEqual(chain.view("get_juror", str(j))["open_seats"], 0)
        chain.ledger_ok()

    def test_buyer_can_dispute_a_pass(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        out = chain.tx(BUYER, "open_dispute", aid, "REQ-001", "The authentication is not really enforced.", value=BOND)
        self.assertEqual(out, "DISPUTED")
        self.assertEqual([r["status"] for r in chain.view("get_requirements", aid)], ["DISPUTED", "PASS", "PASS"])
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        vote_all(chain, aid, ["BUYER", "BUYER", "BUYER"])
        chain.tx(STRANGER, "finalize_dispute", aid)
        self.collect(chain, aid)
        self.assertEqual(wallet(chain, BUYER), 10 * GEN + COLLATERAL)
        cert = check_cert(chain, aid)
        self.assertEqual((cert["final_verdict"], cert["dispute"]["result"]), ("PASS", "BUYER_PREVAILED"))

    def test_respondent_can_answer_once_in_time(self):
        chain, llm, aid = reach("DISPUTED")
        expect_raises(lambda: chain.tx(WORKER, "respond_dispute", aid, "I am the one who disputed, not the respondent."), "only the")
        chain.tx(BUYER, "respond_dispute", aid, "The verdict was right, and here is why in detail.")
        expect_raises(lambda: chain.tx(BUYER, "respond_dispute", aid, "Trying to answer a second time again."), "already responded")
        self.assertEqual(chain.view("get_dispute", aid)["response"], "The verdict was right, and here is why in detail.")

    def test_dispute_phases_respect_their_windows(self):
        chain, llm, aid = reach("DISPUTED")
        expect_raises(lambda: chain.tx(STRANGER, "start_challenge_phase", aid), "still open")
        chain.advance(at.RESPONSE_WINDOW + 1)
        expect_raises(lambda: chain.tx(BUYER, "respond_dispute", aid, "A response that arrives far too late."), "deadline")
        chain.tx(STRANGER, "start_challenge_phase", aid)
        expect_raises(lambda: chain.tx(STRANGER, "seat_jury", aid), "still open")


class TimeoutTests(unittest.TestCase):
    def test_unaccepted_funded_agreement_times_out_and_refunds(self):
        chain, llm, aid = reach("FUNDED")
        expect_raises(lambda: chain.tx(STRANGER, "expire_if_timed_out", aid), "nothing to expire")
        chain.advance(31 * 24 * 3600)
        expect_raises(lambda: chain.tx(WORKER, "accept", aid), "deadline has passed")
        self.assertEqual(chain.tx(STRANGER, "expire_if_timed_out", aid), "TIMEOUT")
        chain.tx(BUYER, "claim_refund", aid)
        chain.tx(BUYER, "withdraw")
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)
        cert = check_cert(chain, aid)
        self.assertEqual(cert["final_verdict"], "NOT_VERIFIED")

    def test_worker_who_never_delivers_times_out(self):
        for state in ("ACCEPTED", "IN_PROGRESS"):
            chain, llm, aid = reach(state)
            chain.advance(31 * 24 * 3600)
            self.assertEqual(chain.tx(STRANGER, "expire_if_timed_out", aid), "TIMEOUT")
            expect_raises(lambda: chain.tx(WORKER, "start_work", aid), "invalid state")

    def test_delivery_after_the_deadline_is_refused(self):
        chain, llm, aid = reach("IN_PROGRESS")
        chain.advance(31 * 24 * 3600)
        expect_raises(lambda: chain.tx(WORKER, "submit_deliverable", aid, "Late but honest statement text.", default_evidence()), "deadline has passed")

    def test_evidence_never_frozen_becomes_insufficient_evidence(self):
        chain, llm, aid = reach("DELIVERED")
        expect_raises(lambda: chain.tx(STRANGER, "expire_if_timed_out", aid), "nothing to expire")
        chain.advance(at.FREEZE_WINDOW + 1)
        self.assertEqual(chain.tx(STRANGER, "expire_if_timed_out", aid), "INSUFFICIENT_EVIDENCE")
        self.assertEqual({(r["verdict"], r["detail"]) for r in chain.view("get_requirements", aid)},
                         {("INSUFFICIENT_EVIDENCE", "EVIDENCE_NOT_FROZEN")})
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        cert = check_cert(chain, aid)
        self.assertEqual(cert["result_note"], "EVIDENCE_NOT_FROZEN")

    def test_a_worker_can_dispute_evidence_that_could_not_be_frozen(self):
        chain, llm, aid = reach("DELIVERED")
        chain.tx(WORKER, "freeze_evidence", aid)
        self.assertEqual(len(chain.agreement(aid)["item_ids"]), 1)
        chain.advance(at.FREEZE_WINDOW + 1)
        chain.tx(STRANGER, "expire_if_timed_out", aid)
        self.assertEqual(chain.agreement(aid)["item_ids"], [])
        out = chain.tx(WORKER, "open_dispute", aid, "REQ-001,REQ-002", "The buyer removed the repository before it could be frozen.", value=BOND)
        self.assertEqual(out, "DISPUTED")
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        vote_all(chain, aid, ["WORKER"] * 3)
        chain.tx(STRANGER, "finalize_dispute", aid)
        self.assertEqual(chain.agreement(aid)["settle_worker"], str(10 * GEN))
        check_cert(chain, aid)

    def test_verification_timeout_fills_missing_requirements_as_insufficient(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        chain.tx(STRANGER, "verify_requirement", aid, "REQ-001")
        chain.advance(at.VERIFY_WINDOW + 1)
        expect_raises(lambda: chain.tx(STRANGER, "verify_requirement", aid, "REQ-002"), "deadline has passed")
        self.assertEqual(chain.tx(STRANGER, "expire_if_timed_out", aid), "INSUFFICIENT_EVIDENCE")
        reqs = chain.view("get_requirements", aid)
        self.assertEqual([r["verdict"] for r in reqs], ["PASS", "INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"])
        self.assertEqual(reqs[1]["detail"], "TIMEOUT")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        check_cert(chain, aid)

    def test_aggregate_after_the_verify_deadline_fills_instead_of_failing(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        chain.advance(at.VERIFY_WINDOW + 1)
        self.assertEqual(chain.tx(STRANGER, "aggregate", aid), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(chain.agreement(aid)["result_note"], "TIMEOUT_FILLED")


class CancelTests(unittest.TestCase):
    def test_cancel_unfunded(self):
        chain, llm, aid = reach("CREATED")
        expect_raises(lambda: chain.tx(WORKER, "cancel", aid), "only the buyer")
        self.assertEqual(chain.tx(BUYER, "cancel", aid), "CANCELLED")
        out = chain.tx(BUYER, "fund", aid, value=10 * GEN)
        self.assertTrue(out.startswith("REJECTED"))

    def test_cancel_funded_before_acceptance_refunds(self):
        chain, llm, aid = reach("FUNDED")
        self.assertEqual(chain.tx(BUYER, "cancel", aid), "REFUNDED")
        chain.tx(BUYER, "withdraw")
        self.assertEqual(wallet(chain, BUYER), 10 * GEN)
        cert = check_cert(chain, aid)
        self.assertEqual(cert["terminal_state"], "REFUNDED_BEFORE_ACCEPTANCE")

    def test_cannot_cancel_after_acceptance(self):
        chain, llm, aid = reach("ACCEPTED")
        expect_raises(lambda: chain.tx(BUYER, "cancel", aid), "invalid state")


if __name__ == "__main__":
    unittest.main()
