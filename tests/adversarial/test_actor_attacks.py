import unittest

from scenario import *

AMOUNT = 10 * GEN
BOND = at._bond_for(AMOUNT)
DISPUTE_TEXT = "The verdict on this requirement is wrong."


def wallet_of(chain, who):
    return chain.wallets[str(who).lower()]


class MaliciousWorkerTests(unittest.TestCase):
    def test_worker_cannot_touch_the_buyers_levers(self):
        chain, llm, aid = reach("ACCEPTED")
        for method in ("cancel", "claim_refund"):
            expect_raises(lambda m=method: chain.tx(WORKER, m, aid), "only the buyer")
        out = chain.tx(WORKER, "fund", aid, value=AMOUNT)
        self.assertTrue(out.startswith("REJECTED"))

    def test_worker_cannot_settle_early_or_claim_a_fail(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        expect_raises(lambda: chain.tx(WORKER, "settle", aid), "invalid state")
        expect_raises(lambda: chain.tx(WORKER, "claim_refund", aid), "only the buyer")
        self.assertEqual(chain.agreement(aid)["settle_worker"], "0")

    def test_worker_cannot_swap_the_deliverable_after_freezing(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        expect_raises(lambda: chain.tx(WORKER, "submit_deliverable", aid, "Swapping in a much better deliverable now.", default_evidence(COMMIT_V2)), "invalid state")
        expect_raises(lambda: chain.tx(WORKER, "freeze_evidence", aid), "invalid state")
        self.assertEqual(chain.view("get_evidence_bundle", aid)[0]["content"], APP_V1)

    def test_worker_cannot_challenge_a_pass_join_the_jury_or_answer_its_own_dispute(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        expect_raises(lambda: chain.tx(WORKER, "challenge_requirement", aid, "REQ-001", "A long enough claim text here.", "E1",
                                       "return jsonify(user), 200", "A sufficiently long piece of reasoning to pass the length check."), "only the buyer")
        chain2, llm2, aid2 = reach("DISPUTED")
        expect_raises(lambda: chain2.tx(WORKER, "respond_dispute", aid2, "Answering my own dispute as if respondent."), "only the")

    def test_a_losing_worker_cannot_extract_escrow_with_an_unattended_dispute(self):
        for n_candidates, votes in ((0, None), (2, None), (3, [None, None, None]), (3, ["WORKER", "BUYER", None])):
            chain, llm = new_chain(jurors=n_candidates)
            aid = create(chain)
            to_pending(chain, aid)
            set_verdicts(llm, REQ_002="FAIL")
            verify_all(chain, aid)
            chain.tx(WORKER, "open_dispute", aid, "REQ-002", DISPUTE_TEXT, value=BOND)
            chain.advance(at.RESPONSE_WINDOW + 1)
            chain.tx(STRANGER, "start_challenge_phase", aid)
            chain.advance(SEAT_WAIT)
            chain.tx(STRANGER, "seat_jury", aid)
            if votes is not None:
                vote_all(chain, aid, votes)
                chain.tx(STRANGER, "finalize_dispute", aid)
            a = chain.agreement(aid)
            self.assertEqual((a["status"], a["settle_worker"], a["settle_buyer"]), ("FINALIZED", "0", str(AMOUNT)))
            chain.ledger_ok()

    def test_worker_cannot_dispute_a_pass(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        out = chain.tx(WORKER, "open_dispute", aid, "REQ-001", DISPUTE_TEXT, value=BOND)
        self.assertTrue(out.startswith("REJECTED"))
        self.assertEqual(chain.status(aid), "VERIFIED_PASS")

    def test_a_party_registered_as_a_juror_is_never_seated_on_its_own_case(self):
        chain, llm = new_chain(jurors=0)
        register_jurors(chain, [WORKER, BUYER] + JURORS[:3])
        aid = create(chain)
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        self.assertEqual(open_and_seat(chain, aid, side_requirements="REQ-002"), "FINAL_REVIEW")
        seated = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
        self.assertEqual(sorted(seated), sorted(str(j).lower() for j in JURORS[:3]))

    def test_identities_registered_after_the_dispute_opened_are_never_seated(self):
        chain, llm = new_chain(jurors=3)
        aid = create(chain)
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        chain.tx(WORKER, "open_dispute", aid, "REQ-002", DISPUTE_TEXT, value=BOND)
        sybils = [addr(0x5000 + i) for i in range(40)]
        for x in sybils:
            chain.tx(x, "register_juror", value=at.JUROR_STAKE)
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        seated = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
        self.assertEqual(sorted(seated), sorted(str(j).lower() for j in JURORS[:3]))
        self.assertEqual(chain.view("get_dispute", aid)["pool_size"], 3)

    def test_a_juror_registered_in_the_same_second_the_dispute_opens_is_never_seated(self):
        for salt in "abcdef":
            chain, llm = new_chain(jurors=3)
            serve_beacon(gl.nondet.web, salt)
            aid = create(chain)
            to_pending(chain, aid)
            set_verdicts(llm, REQ_002="FAIL")
            verify_all(chain, aid)
            sybil = addr(0x7777)
            chain.tx(sybil, "register_juror", value=at.JUROR_STAKE)
            chain.tx(WORKER, "open_dispute", aid, "REQ-002", DISPUTE_TEXT, value=BOND)
            self.assertEqual(chain.view("get_dispute", aid)["pool_size"], 4)
            chain.advance(at.RESPONSE_WINDOW + 1)
            chain.tx(STRANGER, "start_challenge_phase", aid)
            chain.advance(SEAT_WAIT)
            chain.tx(STRANGER, "seat_jury", aid)
            seated = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
            self.assertNotIn(str(sybil).lower(), seated, salt)

    def test_challenges_filed_during_the_challenge_phase_cannot_change_the_jury(self):
        seats = []
        for challenges in (0, 1):
            chain, llm, aid = reach("CHALLENGE")
            if challenges:
                llm.auditor[("REQ-001", "BUYER")] = {"ruling": "REJECTED"}
                chain.tx(BUYER, "challenge_requirement", aid, "REQ-001", "A long enough claim text here.", "E1",
                         '@app.route("/users", methods=["POST"])', "A sufficiently long piece of reasoning to pass the length check.")
            chain.advance(SEAT_WAIT)
            chain.tx(STRANGER, "seat_jury", aid)
            seats.append([j["address"] for j in chain.view("get_dispute", aid)["jurors"]])
        self.assertEqual(seats[0], seats[1])


class MaliciousBuyerTests(unittest.TestCase):
    def test_buyer_cannot_pull_the_escrow_back_after_acceptance(self):
        for state in ("ACCEPTED", "IN_PROGRESS", "DELIVERED", "VERIFICATION_PENDING", "VERIFIED_PASS"):
            chain, llm, aid = reach(state)
            expect_raises(lambda: chain.tx(BUYER, "cancel", aid), "invalid state")
            expect_raises(lambda: chain.tx(BUYER, "claim_refund", aid), "invalid state")

    def test_buyer_cannot_act_as_the_worker(self):
        chain, llm, aid = reach("FUNDED")
        expect_raises(lambda: chain.tx(BUYER, "accept", aid), "only the worker")
        chain, llm, aid = reach("ACCEPTED")
        expect_raises(lambda: chain.tx(BUYER, "start_work", aid), "only the worker")
        chain, llm, aid = reach("IN_PROGRESS")
        expect_raises(lambda: chain.tx(BUYER, "submit_deliverable", aid, "The buyer submits a deliverable here.", default_evidence()), "only the worker")

    def test_buyer_cannot_refund_early_after_a_fail_or_before_the_window_ends(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        expect_raises(lambda: chain.tx(BUYER, "claim_refund", aid), "still open")

    def test_buyer_cannot_join_the_jury_or_dispute_a_fail(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        out = chain.tx(BUYER, "open_dispute", aid, "REQ-002", DISPUTE_TEXT, value=BOND)
        self.assertTrue(out.startswith("REJECTED"))

    def test_buyer_who_disputes_a_pass_risks_the_bond(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        chain.tx(BUYER, "open_dispute", aid, "REQ-001", DISPUTE_TEXT, value=BOND)
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        vote_all(chain, aid, ["WORKER", "WORKER", "WORKER"])
        chain.tx(STRANGER, "finalize_dispute", aid)
        fee = BOND // 2
        self.assertEqual(int(chain.agreement(aid)["settle_worker"]), AMOUNT)
        self.assertEqual(int(chain.view("get_balance", str(BUYER))), 0)
        self.assertEqual(int(chain.view("get_balance", str(WORKER))), AMOUNT + BOND - fee)
        for j in JURORS[:3]:
            self.assertEqual(int(chain.view("get_balance", str(j))), fee // 3)
            self.assertEqual(chain.view("get_juror", str(j))["stake"], str(at.JUROR_STAKE))
        self.assertEqual(int(chain.view("get_accounting")["treasury"]), fee - 3 * (fee // 3))
        chain.ledger_ok()


class DisputeOpeningAbuseTests(unittest.TestCase):
    def open(self, chain, aid, who=WORKER, ids="REQ-002", text=DISPUTE_TEXT, value=BOND):
        return chain.tx(who, "open_dispute", aid, ids, text, value=value)

    def rejected(self, chain, aid, **kw):
        before = chain.status(aid)
        out = self.open(chain, aid, **kw)
        self.assertTrue(out.startswith("REJECTED"), out)
        self.assertEqual(chain.status(aid), before)
        self.assertEqual(int(chain.view("get_balance", str(kw.get("who", WORKER)))), kw.get("value", BOND))
        chain.ledger_ok()

    def test_malformed_disputes_are_rejected_and_refunded(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        self.rejected(chain, aid, value=BOND - 1)
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, value=BOND + 1)
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, ids="")
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, ids="REQ-002,REQ-002")
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, ids="REQ-999")
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, ids="REQ-001")
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, text="too short")
        chain.tx(WORKER, "withdraw")
        self.rejected(chain, aid, who=STRANGER)
        chain.tx(STRANGER, "withdraw")
        self.rejected(chain, aid, who=BUYER)

    def test_dispute_after_the_window_is_rejected(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        chain.advance(at.DISPUTE_WINDOW + 1)
        self.rejected(chain, aid)

    def test_dispute_after_settlement_or_finalization_is_rejected(self):
        for state in ("SETTLED", "FINALIZED", "REFUNDED"):
            chain, llm, aid = reach(state)
            for who in (WORKER, BUYER):
                out = self.open(chain, aid, who=who)
                self.assertTrue(out.startswith("REJECTED"), (state, out))
            self.assertEqual(chain.status(aid), state)
            chain.ledger_ok()

    def test_disputing_twice_is_rejected(self):
        chain, llm, aid = reach("DISPUTED")
        self.assertTrue(self.open(chain, aid).startswith("REJECTED"))
        self.assertTrue(self.open(chain, aid, who=BUYER).startswith("REJECTED"))

    def test_bond_scales_with_the_amount(self):
        chain, llm = new_chain()
        aid = create(chain, amount=1000 * GEN)
        to_pending(chain, aid, amount=1000 * GEN)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        self.assertEqual(at._bond_for(1000 * GEN), 50 * GEN)
        self.assertTrue(self.open(chain, aid, value=at.DISPUTE_BOND_MIN).startswith("REJECTED"))
        self.assertEqual(self.open(chain, aid, value=50 * GEN), "DISPUTED")

    def test_dispute_only_marks_requirements_against_the_disputer(self):
        chain, llm, aid = reach("DISPUTED")
        self.assertEqual([r["status"] for r in chain.view("get_requirements", aid)], ["PASS", "DISPUTED", "PASS"])


class JurorAttackTests(unittest.TestCase):
    def test_registration_rules(self):
        chain, llm = new_chain(jurors=0)
        j = JURORS[0]
        self.assertEqual(chain.tx(j, "register_juror", value=at.JUROR_STAKE), "REGISTERED")
        self.assertTrue(chain.tx(j, "register_juror", value=at.JUROR_STAKE).startswith("REJECTED"))
        self.assertTrue(chain.tx(JURORS[1], "register_juror", value=at.JUROR_STAKE - 1).startswith("REJECTED"))
        self.assertTrue(chain.tx(JURORS[1], "register_juror", value=at.JUROR_STAKE + 1).startswith("REJECTED"))
        expect_raises(lambda: chain.tx(JURORS[1], "register_juror", value=0), "no value")
        self.assertEqual(chain.view("get_protocol_info")["juror_pool_size"], 1)
        self.assertEqual(int(chain.view("get_balance", str(j))), at.JUROR_STAKE)
        self.assertEqual(int(chain.view("get_balance", str(JURORS[1]))), 2 * at.JUROR_STAKE)
        chain.ledger_ok()

    def test_exit_and_withdrawal_of_the_juror_stake(self):
        chain, llm = new_chain(jurors=1)
        j = JURORS[0]
        expect_raises(lambda: chain.tx(j, "withdraw_juror_stake"), "request an exit first")
        expect_raises(lambda: chain.tx(STRANGER, "request_juror_exit"), "not a registered juror")
        self.assertEqual(chain.tx(j, "request_juror_exit"), "EXITING")
        expect_raises(lambda: chain.tx(j, "request_juror_exit"), "already left")
        expect_raises(lambda: chain.tx(j, "withdraw_juror_stake"), "exit delay")
        chain.advance(at.JUROR_EXIT_DELAY + 1)
        expect_raises(lambda: chain.tx(j, "withdraw_juror_stake"), "minimum membership")
        chain.advance(at.JUROR_MIN_MEMBERSHIP + 1)
        self.assertEqual(chain.tx(j, "withdraw_juror_stake"), "WITHDRAWN")
        expect_raises(lambda: chain.tx(j, "withdraw_juror_stake"), "no stake left")
        chain.tx(j, "withdraw")
        self.assertEqual(wallet_of(chain, j), at.JUROR_STAKE)
        chain.ledger_ok()

    def test_a_juror_cannot_be_seated_without_a_full_stake_per_open_seat(self):
        chain, llm, aid = reach("CHALLENGE")
        chain.advance(SEAT_WAIT)
        c = chain.c
        for j in JURORS[:3]:
            c.juror_accounts.get(j).stake = at.u256(0)
        chain.tx(STRANGER, "seat_jury", aid)
        self.assertEqual(chain.status(aid), "FINALIZED")
        self.assertEqual(chain.view("get_dispute", aid)["result"], "NO_JURY_FALLBACK")
        chain.ledger_ok()

    def test_the_verifier_cannot_pick_a_system_detail(self):
        for d in ("TIMEOUT", "CHALLENGE_UPHELD", "EVIDENCE_NOT_FROZEN", "RED_TEAM_MISSING"):
            self.assertFalse(at._check_verifier({"verdict": "INSUFFICIENT_EVIDENCE", "detail": d, "quotes": [], "reason": "x"}, {"evidence": {}}))

    def test_a_seated_juror_cannot_leave_before_the_case_closes(self):
        chain, llm, aid = reach("FINAL_REVIEW")
        j = chain.view("get_dispute", aid)["jurors"][0]["address"]
        chain.tx(j, "request_juror_exit")
        chain.advance(at.JUROR_EXIT_DELAY + 1)
        expect_raises(lambda: chain.tx(j, "withdraw_juror_stake"), "open seats")
        self.assertEqual(chain.view("get_juror", j)["seats"], [aid])

    def test_a_juror_who_exited_before_the_dispute_is_not_seated(self):
        chain, llm = new_chain(jurors=4)
        chain.tx(JURORS[0], "request_juror_exit")
        chain.advance(1)
        aid = create(chain)
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        self.assertEqual(open_and_seat(chain, aid, side_requirements="REQ-002"), "FINAL_REVIEW")
        seated = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
        self.assertEqual(sorted(seated), sorted(str(j).lower() for j in JURORS[1:4]))

    def test_exiting_after_the_dispute_opened_does_not_change_the_draw(self):
        seats = []
        for leave in (False, True):
            chain, llm, aid = reach("CHALLENGE")
            register_jurors(chain, [])
            if leave:
                chain.tx(JURORS[0], "request_juror_exit")
            chain.advance(SEAT_WAIT)
            chain.tx(STRANGER, "seat_jury", aid)
            seats.append([j["address"] for j in chain.view("get_dispute", aid)["jurors"]])
        self.assertEqual(seats[0], seats[1])

    def test_seating_waits_for_the_beacon_and_uses_it(self):
        chain, llm, aid = reach("CHALLENGE")
        chain.advance(at.CHALLENGE_PHASE + 1)
        d = chain.view("get_dispute", aid)
        a = chain.agreement(aid)
        self.assertGreaterEqual(at._beacon_time(d["beacon_round"]), a["stage_deadline"])
        if chain.now < at._beacon_time(d["beacon_round"]) + at.BEACON_MARGIN:
            expect_raises(lambda: chain.tx(STRANGER, "seat_jury", aid), "not published yet")
        chain.advance(at.BEACON_PERIOD + at.BEACON_MARGIN)
        chain.tx(STRANGER, "seat_jury", aid)
        d = chain.view("get_dispute", aid)
        self.assertEqual(d["beacon"], beacon_value(d["beacon_round"]))
        self.assertIn((("get", at.BEACON_URL + str(d["beacon_round"]))), gl.nondet.web.calls)

    def test_an_unavailable_beacon_blocks_seating_until_the_grace_period_then_falls_back(self):
        chain, llm, aid = reach("CHALLENGE")
        gl.nondet.web.handlers.clear()
        chain.advance(SEAT_WAIT)
        expect_raises(lambda: chain.tx(STRANGER, "seat_jury", aid))
        self.assertEqual(chain.status(aid), "CHALLENGE")
        chain.advance(at.SEAT_GRACE)
        self.assertEqual(chain.tx(STRANGER, "seat_jury", aid), "FINALIZED")
        self.assertEqual(chain.view("get_dispute", aid)["result"], "NO_JURY_FALLBACK")
        chain.ledger_ok()

    def test_a_different_beacon_draws_a_different_jury_from_a_large_pool(self):
        seats = set()
        for salt in ("a", "b", "c", "d"):
            chain, llm = new_chain(jurors=8)
            serve_beacon(gl.nondet.web, salt)
            aid = create(chain)
            to_pending(chain, aid)
            set_verdicts(llm, REQ_002="FAIL")
            verify_all(chain, aid)
            open_and_seat(chain, aid, side_requirements="REQ-002")
            seats.add(tuple(sorted(j["address"] for j in chain.view("get_dispute", aid)["jurors"])))
        self.assertGreater(len(seats), 1)

    def test_only_seated_jurors_can_vote(self):
        chain, llm = new_chain(jurors=8)
        aid = create(chain)
        to_pending(chain, aid)
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        chain.tx(WORKER, "open_dispute", aid, "REQ-002", DISPUTE_TEXT, value=BOND)
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        seated = {j["address"] for j in chain.view("get_dispute", aid)["jurors"]}
        unseated = [j for j in JURORS if str(j).lower() not in seated][0]
        expect_raises(lambda: chain.tx(unseated, "commit_vote", aid, "a" * 64), "not a seated juror")
        expect_raises(lambda: chain.tx(STRANGER, "commit_vote", aid, "a" * 64), "not a seated juror")
        expect_raises(lambda: chain.tx(WORKER, "commit_vote", aid, "a" * 64), "not a seated juror")

    def seated(self):
        chain, llm, aid = reach("FINAL_REVIEW")
        return chain, aid, [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]

    def test_commit_rules(self):
        chain, aid, jurors = self.seated()
        j = jurors[0]
        for bad in ("", "abc", "G" * 64, "A" * 64, "a" * 63, "a" * 65, 5, None):
            expect_raises(lambda b=bad: chain.tx(j, "commit_vote", aid, b), "commitment")
        chain.tx(j, "commit_vote", aid, "a" * 64)
        expect_raises(lambda: chain.tx(j, "commit_vote", aid, "b" * 64), "already committed")
        chain.advance(at.COMMIT_WINDOW + 1)
        expect_raises(lambda: chain.tx(jurors[1], "commit_vote", aid, "c" * 64), "deadline has passed")

    def test_reveal_rules(self):
        chain, aid, jurors = self.seated()
        j = jurors[0]
        chain.tx(j, "commit_vote", aid, commit_for(aid, j, "WORKER", "good-salt-1"))
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "WORKER", "good-salt-1"), "commit window is still open")
        chain.advance(at.COMMIT_WINDOW + 1)
        expect_raises(lambda: chain.tx(jurors[1], "reveal_vote", aid, "WORKER", "good-salt-1"), "no commitment")
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "BUYER", "good-salt-1"), "does not match")
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "WORKER", "wrong-salt-1"), "does not match")
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "MAYBE", "good-salt-1"), "WORKER or BUYER")
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "WORKER", "short"), "salt")
        chain.tx(j, "reveal_vote", aid, "WORKER", "good-salt-1")
        expect_raises(lambda: chain.tx(j, "reveal_vote", aid, "WORKER", "good-salt-1"), "already revealed")
        self.assertEqual(chain.view("get_dispute", aid)["votes_worker"], 1)

    def test_reveal_after_the_deadline_is_refused(self):
        chain, aid, jurors = self.seated()
        chain.tx(jurors[0], "commit_vote", aid, commit_for(aid, jurors[0], "WORKER", "good-salt-1"))
        chain.advance(at.COMMIT_WINDOW + at.REVEAL_WINDOW + 1)
        expect_raises(lambda: chain.tx(jurors[0], "reveal_vote", aid, "WORKER", "good-salt-1"), "reveal deadline")

    def test_a_juror_cannot_copy_another_jurors_commitment(self):
        chain, aid, jurors = self.seated()
        a, b = jurors[0], jurors[1]
        copied = commit_for(aid, a, "WORKER", "secret-salt-A")
        chain.tx(a, "commit_vote", aid, copied)
        chain.tx(b, "commit_vote", aid, copied)
        chain.advance(at.COMMIT_WINDOW + 1)
        expect_raises(lambda: chain.tx(b, "reveal_vote", aid, "WORKER", "secret-salt-A"), "does not match")
        chain.tx(a, "reveal_vote", aid, "WORKER", "secret-salt-A")

    def test_votes_stay_hidden_until_revealed(self):
        chain, aid, jurors = self.seated()
        chain.tx(jurors[0], "commit_vote", aid, commit_for(aid, jurors[0], "BUYER", "hidden-salt-1"))
        view = chain.view("get_dispute", aid)
        self.assertEqual(view["jurors"][[j["address"] for j in view["jurors"]].index(jurors[0])]["vote"], "")
        self.assertEqual((view["votes_worker"], view["votes_buyer"]), (0, 0))

    def test_finalization_cannot_be_rushed_or_repeated(self):
        chain, aid, jurors = self.seated()
        expect_raises(lambda: chain.tx(STRANGER, "finalize_dispute", aid), "still open")
        vote_all(chain, aid, ["WORKER", "WORKER", "BUYER"])
        chain.tx(STRANGER, "finalize_dispute", aid)
        expect_raises(lambda: chain.tx(STRANGER, "finalize_dispute", aid), "invalid state")
        expect_raises(lambda: chain.tx(STRANGER, "seat_jury", aid), "invalid state")

    def test_early_finalization_once_every_juror_has_revealed(self):
        chain, aid, jurors = self.seated()
        vote_all(chain, aid, ["BUYER", "BUYER", "BUYER"])
        self.assertLess(chain.now, chain.agreement(aid)["stage_deadline"])
        chain.tx(STRANGER, "finalize_dispute", aid)
        self.assertEqual(chain.status(aid), "FINALIZED")

    def test_cross_agreement_replay_of_a_commitment_fails(self):
        chain, aid, jurors = self.seated()
        other = commit_for("AT-999", jurors[0], "WORKER", "replay-salt-1")
        chain.tx(jurors[0], "commit_vote", aid, other)
        chain.advance(at.COMMIT_WINDOW + 1)
        expect_raises(lambda: chain.tx(jurors[0], "reveal_vote", aid, "WORKER", "replay-salt-1"), "does not match")


class ReplayAndDeadlineTests(unittest.TestCase):
    def test_replaying_any_transition_fails(self):
        chain, llm = new_chain()
        aid = create(chain)
        chain.tx(BUYER, "fund", aid, value=AMOUNT)
        self.assertTrue(chain.tx(BUYER, "fund", aid, value=AMOUNT).startswith("REJECTED"))
        chain.tx(WORKER, "accept", aid)
        expect_raises(lambda: chain.tx(WORKER, "accept", aid), "invalid state")
        chain.tx(WORKER, "start_work", aid)
        expect_raises(lambda: chain.tx(WORKER, "start_work", aid), "invalid state")

    def test_deadline_cannot_be_moved_by_anyone(self):
        chain, llm, aid = reach("IN_PROGRESS")
        d0 = chain.agreement(aid)["deadline"]
        methods = [m for m in dir(chain.c) if not m.startswith("_") and getattr(getattr(chain.c, m), "_gl_kind", "") == "write"]
        self.assertNotIn("set_deadline", methods)
        self.assertNotIn("extend_deadline", methods)
        self.assertEqual(chain.agreement(aid)["deadline"], d0)

    def test_acceptance_and_delivery_are_bound_to_the_deadline(self):
        chain, llm, aid = reach("FUNDED")
        chain.advance(chain.agreement(aid)["deadline"] - chain.now + 1)
        expect_raises(lambda: chain.tx(WORKER, "accept", aid), "deadline has passed")

    def test_the_clock_can_never_run_backwards_for_the_contract(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        chain.now -= 10 * 24 * 3600
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "still open")


if __name__ == "__main__":
    unittest.main()
