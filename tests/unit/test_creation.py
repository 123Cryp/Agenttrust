import json
import unittest

from scenario import *


def make(chain, **over):
    args = dict(title="Build a REST API", description="A REST API with authentication.",
                specification="Deliver a Flask service exposing POST /users behind token authentication.",
                worker=str(WORKER), currency="GEN", amount=10 * GEN, deadline=chain.now + 7 * 24 * 3600,
                requirements=REQUIREMENTS[:2], evidence="STRICT", verification="STANDARD", dispute="JURY")
    args.update(over)
    reqs = args["requirements"] if isinstance(args["requirements"], str) else json.dumps(args["requirements"])
    return chain.tx(over.pop("sender", BUYER), "create_agreement", args["title"], args["description"], args["specification"],
                    args["worker"], args["currency"], args["amount"], args["deadline"], reqs, args["evidence"],
                    args["verification"], args["dispute"])


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.chain, self.llm = new_chain()

    def bad(self, fragment, **over):
        expect_raises(lambda: make(self.chain, **over), fragment)
        self.assertEqual(self.chain.view("agreement_count"), 0)

    def test_creates_committed_agreement_with_hashes(self):
        aid = make(self.chain)
        a = self.chain.agreement(aid)
        self.assertEqual(a["status"], "CREATED")
        self.assertEqual(a["buyer"], str(BUYER).lower())
        self.assertEqual(a["worker"], str(WORKER).lower())
        for key in ("spec_hash", "requirements_hash", "policies_hash", "agreement_hash"):
            self.assertRegex(a[key], r"^[0-9a-f]{64}$")
        self.assertEqual(a["frozen_hash"], "")
        reqs = self.chain.view("get_requirements", aid)
        self.assertEqual([r["status"] for r in reqs], ["UNVERIFIED", "UNVERIFIED"])

    def test_ids_are_sequential_and_hashes_differ(self):
        a1, a2 = make(self.chain), make(self.chain)
        self.assertEqual((a1, a2), ("AT-1", "AT-2"))
        self.assertNotEqual(self.chain.agreement(a1)["agreement_hash"], self.chain.agreement(a2)["agreement_hash"])

    def test_spec_hash_depends_on_specification(self):
        a1 = make(self.chain)
        a2 = make(self.chain, specification="A different specification text that changes the commitment.")
        self.assertNotEqual(self.chain.agreement(a1)["spec_hash"], self.chain.agreement(a2)["spec_hash"])
        self.assertEqual(self.chain.agreement(a1)["requirements_hash"], self.chain.agreement(a2)["requirements_hash"])

    def test_empty_requirements(self):
        self.bad("at least one requirement", requirements=[])

    def test_requirements_not_json(self):
        self.bad("JSON list", requirements="not json")

    def test_duplicate_requirement_ids(self):
        self.bad("duplicate requirement id", requirements=[REQUIREMENTS[0], REQUIREMENTS[0]])

    def test_bad_requirement_id(self):
        r = dict(REQUIREMENTS[0], id="R1")
        self.bad("REQ-001", requirements=[r])

    def test_unknown_method(self):
        r = dict(REQUIREMENTS[0], method="MAGIC")
        self.bad("unknown verification method", requirements=[r])

    def test_extra_or_missing_requirement_fields(self):
        r = dict(REQUIREMENTS[0], extra="x")
        self.bad("exactly", requirements=[r])
        r = {k: v for k, v in REQUIREMENTS[0].items() if k != "method"}
        self.bad("exactly", requirements=[r])

    def test_too_many_requirements(self):
        reqs = [dict(REQUIREMENTS[0], id="REQ-%03d" % i) for i in range(1, at.MAX_REQUIREMENTS + 2)]
        self.bad("at most", requirements=reqs)

    def test_zero_and_tiny_amount(self):
        self.bad("amount must be", amount=0)
        self.bad("amount must be", amount=at.MIN_AMOUNT - 1)
        self.bad("amount must be", amount=-5)

    def test_amount_upper_bound_and_type(self):
        self.bad("amount must be", amount=at.MAX_AMOUNT + 1)
        self.bad("amount must be", amount=True)
        self.bad("amount must be", amount=1.5 * GEN)

    def test_worker_validation(self):
        self.bad("worker must be", worker="0x123")
        self.bad("worker must be", worker="not an address")
        self.bad("zero address", worker="0x" + "0" * 40)
        self.bad("different addresses", worker=str(BUYER))
        self.bad("different addresses", worker=str(BUYER).upper().replace("0X", "0x"))

    def test_currency(self):
        self.bad("only GEN", currency="ETH")

    def test_deadline_bounds_and_types(self):
        self.bad("deadline", deadline=self.chain.now - 1)
        self.bad("deadline", deadline=self.chain.now + at.MIN_DEADLINE_SECONDS - 1)
        self.bad("deadline", deadline=self.chain.now + at.MAX_DEADLINE_SECONDS + 1)
        self.bad("deadline", deadline=True)
        self.bad("deadline", deadline=float(self.chain.now + 99999))
        self.bad("deadline", deadline="tomorrow")

    def test_policies(self):
        self.bad("evidence_policy", evidence="LAX")
        self.bad("verification_policy", verification="NONE")
        self.bad("dispute_policy", dispute="COURT")

    def test_text_limits_and_control_characters(self):
        self.bad("title", title="ab")
        self.bad("title", title="x" * (at.MAX_TITLE + 1))
        self.bad("control character", title="bad\x00title")
        self.bad("control character", description="line\rbreak that is long enough")
        self.bad("specification", specification="short")

    def test_unicode_text_is_accepted(self):
        aid = make(self.chain, title="قرارداد نرم‌افزار")
        self.assertEqual(self.chain.status(aid), "CREATED")

    def test_worker_case_is_normalised(self):
        aid = make(self.chain, worker="0x" + "AB" * 20)
        self.assertEqual(self.chain.agreement(aid)["worker"], "0x" + "ab" * 20)

    def test_failed_create_does_not_consume_an_id(self):
        expect_raises(lambda: make(self.chain, amount=0))
        self.assertEqual(make(self.chain), "AT-1")


if __name__ == "__main__":
    unittest.main()
