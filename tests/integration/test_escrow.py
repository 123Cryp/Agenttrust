import unittest

from scenario import *

AMOUNT = 10 * GEN


class FundingTests(unittest.TestCase):
    def setUp(self):
        self.chain, self.llm = new_chain()
        self.aid = create(self.chain)

    def rejected(self, out):
        self.assertTrue(out.startswith("REJECTED"), out)

    def test_exact_funding_locks_the_escrow(self):
        self.assertEqual(self.chain.tx(BUYER, "fund", self.aid, value=AMOUNT), "FUNDED")
        acc = self.chain.ledger_ok()
        self.assertEqual(int(acc["escrow_locked"]), AMOUNT)
        self.assertEqual(self.chain.agreement(self.aid)["funded"], 1)

    def test_wrong_amounts_are_rejected_and_credited_back(self):
        for value in (AMOUNT - 1, AMOUNT + 1, 1, 2 * AMOUNT):
            self.rejected(self.chain.tx(BUYER, "fund", self.aid, value=value))
            self.assertEqual(self.chain.status(self.aid), "CREATED")
            self.assertEqual(int(self.chain.view("get_balance", str(BUYER))), value)
            self.chain.tx(BUYER, "withdraw")
            self.assertEqual(int(self.chain.view("get_balance", str(BUYER))), 0)
        self.assertEqual(self.chain.wallets[str(BUYER).lower()], sum((AMOUNT - 1, AMOUNT + 1, 1, 2 * AMOUNT)))
        self.chain.ledger_ok()

    def test_only_the_buyer_can_fund(self):
        for who in (WORKER, STRANGER, OWNER):
            self.rejected(self.chain.tx(who, "fund", self.aid, value=AMOUNT))
            self.chain.tx(who, "withdraw")
        self.assertEqual(self.chain.status(self.aid), "CREATED")
        self.chain.ledger_ok()

    def test_zero_value_funding_reverts(self):
        expect_raises(lambda: self.chain.tx(BUYER, "fund", self.aid, value=0), "no value attached")

    def test_unknown_agreement_is_rejected_not_swallowed(self):
        self.rejected(self.chain.tx(BUYER, "fund", "AT-99", value=AMOUNT))
        self.assertEqual(int(self.chain.view("get_balance", str(BUYER))), AMOUNT)
        self.chain.ledger_ok()

    def test_funding_twice_is_rejected(self):
        self.chain.tx(BUYER, "fund", self.aid, value=AMOUNT)
        self.rejected(self.chain.tx(BUYER, "fund", self.aid, value=AMOUNT))
        self.assertEqual(int(self.chain.ledger_ok()["escrow_locked"]), AMOUNT)

    def test_funding_after_the_deadline_is_rejected(self):
        self.chain.advance(31 * 24 * 3600)
        self.rejected(self.chain.tx(BUYER, "fund", self.aid, value=AMOUNT))
        self.assertEqual(self.chain.status(self.aid), "CREATED")

    def test_a_reverting_payable_call_records_the_value_as_stuck_not_as_credit(self):
        expect_raises(lambda: self.chain.tx(BUYER, "fund", self.aid, value=0))
        self.chain.ledger_ok()
        self.assertEqual(self.chain.stuck, 0)


class WithdrawTests(unittest.TestCase):
    def test_withdraw_pays_exactly_the_credit_once(self):
        chain, llm, aid = reach("SETTLED")
        self.assertEqual(int(chain.view("get_balance", str(WORKER))), AMOUNT)
        self.assertEqual(chain.tx(WORKER, "withdraw"), AMOUNT)
        expect_raises(lambda: chain.tx(WORKER, "withdraw"), "nothing to withdraw")
        self.assertEqual(chain.wallets[str(WORKER).lower()], AMOUNT)
        self.assertEqual(chain.balance, int(chain.view("get_accounting")["stakes_locked"]))
        chain.ledger_ok()

    def test_nobody_can_withdraw_someone_elses_credit(self):
        chain, llm, aid = reach("SETTLED")
        for who in (BUYER, STRANGER, OWNER):
            expect_raises(lambda w=who: chain.tx(w, "withdraw"), "nothing to withdraw")
        self.assertEqual(int(chain.view("get_balance", str(WORKER))), AMOUNT)

    def test_treasury_is_owner_only_and_single_use(self):
        chain, llm, aid = reach("FINALIZED", votes=(None, None, None))
        self.assertEqual(int(chain.view("get_accounting")["treasury"]), 3 * at.JUROR_STAKE)
        for who in (WORKER, BUYER, STRANGER):
            expect_raises(lambda w=who: chain.tx(w, "withdraw_treasury"), "only the owner")
        chain.tx(OWNER, "withdraw_treasury")
        expect_raises(lambda: chain.tx(OWNER, "withdraw_treasury"), "treasury is empty")
        chain.ledger_ok()


class DoublePayoutTests(unittest.TestCase):
    def test_no_second_release_after_settlement(self):
        chain, llm, aid = reach("SETTLED")
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "invalid state")
        expect_raises(lambda: chain.tx(BUYER, "claim_refund", aid), "invalid state")
        expect_raises(lambda: chain.tx(BUYER, "cancel", aid), "invalid state")
        a = chain.c.agreements.get(aid)
        expect_raises(lambda: chain.c._settle_escrow(a, AMOUNT, 0), "already paid out")
        expect_raises(lambda: chain.c._settle_escrow(a, 0, AMOUNT), "already paid out")
        acc = chain.ledger_ok()
        self.assertEqual(int(acc["claimable_total"]), AMOUNT)

    def test_no_second_refund(self):
        for state in ("REFUNDED", "TIMEOUT"):
            chain, llm, aid = reach(state)
            if state == "TIMEOUT":
                chain.tx(BUYER, "claim_refund", aid)
            expect_raises(lambda: chain.tx(BUYER, "claim_refund", aid), "invalid state")
            expect_raises(lambda: chain.tx(BUYER, "cancel", aid), "invalid state")
            a = chain.c.agreements.get(aid)
            expect_raises(lambda: chain.c._settle_escrow(a, 0, AMOUNT), "already paid out")
            self.assertEqual(int(chain.ledger_ok()["claimable_total"]), AMOUNT)

    def test_no_release_after_a_refund_and_no_refund_after_a_release(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        expect_raises(lambda: chain.tx(STRANGER, "settle", aid), "invalid state")
        out = chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=at._bond_for(AMOUNT))
        self.assertTrue(out.startswith("REJECTED"))
        self.assertEqual(chain.status(aid), "REFUNDED")
        chain.ledger_ok()

    def test_settlement_must_add_up(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        a = chain.c.agreements.get(aid)
        for w, b in ((AMOUNT, 1), (AMOUNT - 1, 0), (-1, AMOUNT + 1), (0, 0)):
            expect_raises(lambda w=w, b=b: chain.c._settle_escrow(a, w, b), "add up")

    def test_unfunded_agreements_cannot_pay_out(self):
        chain, llm, aid = reach("CREATED")
        a = chain.c.agreements.get(aid)
        expect_raises(lambda: chain.c._settle_escrow(a, AMOUNT, 0), "never funded")

    def test_every_dispute_outcome_conserves_value(self):
        for votes in (("WORKER",) * 3, ("BUYER",) * 3, ("WORKER", "BUYER", None), (None, None, None), ("WORKER", None, None)):
            chain, llm, aid = reach("FINALIZED", votes=votes)
            a = chain.agreement(aid)
            self.assertEqual(int(a["settle_worker"]) + int(a["settle_buyer"]), AMOUNT)
            for who in [WORKER, BUYER, OWNER] + JURORS:
                if int(chain.view("get_balance", str(who))) > 0:
                    chain.tx(who, "withdraw")
            acc = chain.ledger_ok()
            self.assertEqual(int(acc["escrow_locked"]) + int(acc["bonds_locked"]) + int(acc["claimable_total"]), 0)
            remaining = sum(int(chain.view("get_juror", str(j)).get("stake", "0")) for j in JURORS)
            self.assertEqual(int(acc["stakes_locked"]), remaining)
            self.assertEqual(chain.balance, int(acc["treasury"]) + remaining)


if __name__ == "__main__":
    unittest.main()
