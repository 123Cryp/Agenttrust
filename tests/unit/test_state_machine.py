import unittest

from scenario import *

QUOTE = "return jsonify(user), 200"


def actions():
    def challenge(chain, aid):
        return chain.tx(BUYER, "challenge_requirement", aid, "REQ-001", "The authentication claim is not established.", "E1",
                        QUOTE, "This quote shows the handler returns user data without any visible check in this function.")

    return {
        "cancel": ({"CREATED", "FUNDED"}, lambda c, a: c.tx(BUYER, "cancel", a)),
        "accept": ({"FUNDED"}, lambda c, a: c.tx(WORKER, "accept", a)),
        "start_work": ({"ACCEPTED"}, lambda c, a: c.tx(WORKER, "start_work", a)),
        "submit_deliverable": ({"IN_PROGRESS"}, lambda c, a: c.tx(WORKER, "submit_deliverable", a, "A statement that is long enough.", default_evidence())),
        "freeze_evidence": ({"DELIVERED"}, lambda c, a: c.tx(WORKER, "freeze_evidence", a)),
        "verify_requirement": ({"VERIFICATION_PENDING"}, lambda c, a: c.tx(STRANGER, "verify_requirement", a, "REQ-001")),
        "red_team_requirement": (set(), lambda c, a: c.tx(STRANGER, "red_team_requirement", a, "REQ-001")),
        "aggregate": ({"VERIFICATION_PENDING"}, lambda c, a: c.tx(STRANGER, "aggregate", a)),
        "challenge_requirement": ({"VERIFIED_PASS", "CHALLENGE"}, challenge),
        "respond_dispute": ({"DISPUTED"}, lambda c, a: c.tx(BUYER, "respond_dispute", a, "The verdict was right, here is why.")),
        "start_challenge_phase": ({"DISPUTED"}, lambda c, a: c.tx(STRANGER, "start_challenge_phase", a)),
        "seat_jury": ({"CHALLENGE"}, lambda c, a: c.tx(STRANGER, "seat_jury", a)),
        "commit_vote": ({"FINAL_REVIEW"}, lambda c, a: c.tx(JURORS[0], "commit_vote", a, "0" * 64)),
        "reveal_vote": ({"FINAL_REVIEW"}, lambda c, a: c.tx(JURORS[0], "reveal_vote", a, "WORKER", "saltsalt")),
        "finalize_dispute": ({"FINAL_REVIEW"}, lambda c, a: c.tx(STRANGER, "finalize_dispute", a)),
        "settle": ({"VERIFIED_PASS"}, lambda c, a: c.tx(STRANGER, "settle", a)),
        "claim_refund": ({"TIMEOUT", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"}, lambda c, a: c.tx(BUYER, "claim_refund", a)),
    }


EXPECTED_EDGES = {
    "CREATED": {"FUNDED", "CANCELLED"},
    "FUNDED": {"ACCEPTED", "REFUNDED", "TIMEOUT"},
    "ACCEPTED": {"IN_PROGRESS", "TIMEOUT"},
    "IN_PROGRESS": {"DELIVERED", "TIMEOUT"},
    "DELIVERED": {"VERIFICATION_PENDING", "INSUFFICIENT_EVIDENCE"},
    "VERIFICATION_PENDING": {"VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"},
    "VERIFIED_PASS": {"SETTLED", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE", "DISPUTED"},
    "VERIFIED_FAIL": {"DISPUTED", "REFUNDED"},
    "INSUFFICIENT_EVIDENCE": {"DISPUTED", "REFUNDED"},
    "DISPUTED": {"CHALLENGE"},
    "CHALLENGE": {"FINAL_REVIEW", "FINALIZED"},
    "FINAL_REVIEW": {"FINALIZED"},
    "TIMEOUT": {"REFUNDED"},
    "SETTLED": set(), "FINALIZED": set(), "REFUNDED": set(), "CANCELLED": set(),
}


class GraphTests(unittest.TestCase):
    def test_edge_table_equals_the_documented_state_machine(self):
        self.assertEqual(at.ALLOWED_EDGES, EXPECTED_EDGES)

    def test_every_state_has_an_entry_and_targets_are_states(self):
        self.assertEqual(set(at.ALLOWED_EDGES), set(STATES))
        for src, dsts in at.ALLOWED_EDGES.items():
            self.assertTrue(dsts <= set(STATES), src)

    def test_terminal_states_have_no_exits(self):
        for s in at.TERMINAL_STATES:
            self.assertEqual(at.ALLOWED_EDGES[s], set())
        self.assertEqual(at.TERMINAL_STATES, {"SETTLED", "FINALIZED", "REFUNDED", "CANCELLED"})

    def test_every_state_is_reachable_from_created(self):
        seen, todo = {"CREATED"}, ["CREATED"]
        while todo:
            for nxt in at.ALLOWED_EDGES[todo.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        self.assertEqual(seen, set(STATES))

    def test_every_non_terminal_state_can_reach_a_terminal_state(self):
        for s in STATES:
            seen, todo = {s}, [s]
            while todo:
                for nxt in at.ALLOWED_EDGES[todo.pop()]:
                    if nxt not in seen:
                        seen.add(nxt)
                        todo.append(nxt)
            self.assertTrue(seen & at.TERMINAL_STATES, s)

    def test_illegal_edges_are_refused_by_enter(self):
        chain, llm, aid = reach("CREATED")
        a = chain.c.agreements.get(aid)
        for bad in ("SETTLED", "ACCEPTED", "FINALIZED", "REFUNDED", "VERIFIED_PASS", "DISPUTED"):
            expect_raises(lambda b=bad: chain.c._enter(a, b), "illegal transition")
        self.assertEqual(a.status, "CREATED")


class ReachTests(unittest.TestCase):
    def test_every_state_is_reachable_through_the_public_api(self):
        for state in STATES:
            chain, llm, aid = reach(state)
            self.assertEqual(chain.status(aid), state, state)
            chain.ledger_ok()


class WrongStateTests(unittest.TestCase):
    def test_every_action_is_refused_in_every_state_it_does_not_belong_to(self):
        table = actions()
        for state in STATES:
            for name, (allowed, call) in table.items():
                if state in allowed:
                    continue
                chain, llm, aid = reach(state)
                before = chain.snapshot()
                expect_raises(lambda: call(chain, aid))
                self.assertEqual(chain.snapshot(), before, name + " changed state in " + state)
                self.assertEqual(chain.status(aid), state)

    def test_nothing_moves_a_terminal_agreement(self):
        table = actions()
        for state in sorted(at.TERMINAL_STATES):
            chain, llm, aid = reach(state)
            for name, (allowed, call) in table.items():
                expect_raises(lambda: call(chain, aid))
            expect_raises(lambda: chain.tx(STRANGER, "expire_if_timed_out", aid), "nothing to expire")
            self.assertEqual(chain.status(aid), state)

    def test_payable_calls_in_wrong_states_are_rejected_and_credited(self):
        for state in STATES:
            chain, llm, aid = reach(state)
            before_status = chain.status(aid)
            if state != "CREATED":
                out = chain.tx(BUYER, "fund", aid, value=10 * GEN)
                self.assertTrue(out.startswith("REJECTED"), (state, out))
                self.assertEqual(chain.status(aid), before_status)
            if state not in ("VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"):
                out = chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=at._bond_for(10 * GEN))
                self.assertTrue(out.startswith("REJECTED"), (state, out))
            chain.ledger_ok()


if __name__ == "__main__":
    unittest.main()
