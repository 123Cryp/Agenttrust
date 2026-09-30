"""The ten protocol invariants, each attacked directly."""
import json
import unittest

from scenario import *
from certs import check_cert
import verify_certificate_loader as vcl

AMOUNT = 10 * GEN
QUOTE = "return jsonify(user), 200"

WRITE_METHODS = None


def write_methods(chain):
    return sorted(m for m in dir(chain.c) if not m.startswith("_") and getattr(getattr(chain.c, m), "_gl_kind", "") == "write")


def frozen_fields(a):
    keys = ("agreement_id", "buyer", "worker", "title", "description", "specification", "currency", "amount", "deadline",
            "evidence_policy", "verification_policy", "dispute_policy", "created_at", "spec_hash", "requirements_hash",
            "policies_hash", "agreement_hash", "requirement_ids")
    return {k: a[k] for k in keys}


class Invariant01FundsReleasedOnce(unittest.TestCase):
    def test_settle_path(self):
        chain, llm, aid = reach("SETTLED")
        for m, args, who in (("settle", (aid,), STRANGER), ("claim_refund", (aid,), BUYER), ("cancel", (aid,), BUYER),
                             ("finalize_dispute", (aid,), STRANGER)):
            expect_raises(lambda: chain.tx(who, m, *args))
        self.assertEqual(int(chain.ledger_ok()["claimable_total"]), AMOUNT)

    def test_dispute_path(self):
        chain, llm, aid = reach("FINALIZED")
        for m, who in (("finalize_dispute", STRANGER), ("settle", STRANGER), ("claim_refund", BUYER), ("seat_jury", STRANGER)):
            expect_raises(lambda: chain.tx(who, m, aid))
        a = chain.agreement(aid)
        self.assertEqual(int(a["settle_worker"]) + int(a["settle_buyer"]), AMOUNT)
        chain.ledger_ok()


class Invariant02FundsRefundedOnce(unittest.TestCase):
    def test_refund_paths(self):
        for state in ("REFUNDED", "TIMEOUT", "VERIFIED_FAIL"):
            chain, llm, aid = reach(state)
            if state != "REFUNDED":
                chain.advance(at.DISPUTE_WINDOW + 1)
                chain.tx(BUYER, "claim_refund", aid)
            for m in ("claim_refund", "cancel"):
                expect_raises(lambda: chain.tx(BUYER, m, aid))
            self.assertEqual(int(chain.ledger_ok()["claimable_total"]), AMOUNT)
            self.assertEqual(chain.agreement(aid)["settle_buyer"], str(AMOUNT))


class Invariant03FinalizedAgreementsCannotChange(unittest.TestCase):
    def test_terminal_agreements_are_immutable_under_every_write_method(self):
        sample = {"fund": (BUYER, "AID", ), }
        for state in sorted(at.TERMINAL_STATES):
            chain, llm, aid = reach(state)
            snap = chain.snapshot()
            for m in write_methods(chain):
                if m in ("withdraw", "withdraw_treasury", "create_agreement", "register_juror", "request_juror_exit", "withdraw_juror_stake"):
                    continue
                arity = getattr(chain.c, m).__code__.co_argcount - 1
                args = [aid, "REQ-002", "x" * 40, "E1", "x" * 8, "x" * 60][:arity]
                for who in (BUYER, WORKER, STRANGER, JURORS[0], OWNER):
                    try:
                        chain.tx(who, m, *args, value=0)
                    except Exception:
                        pass
                    else:
                        self.fail("%s succeeded on a %s agreement" % (m, state))
            self.assertEqual(chain.snapshot(), snap)

    def test_certificate_is_written_once(self):
        chain, llm, aid = reach("SETTLED")
        before = chain.view("get_certificate", aid)
        a = chain.c.agreements.get(aid)
        expect_raises(lambda: chain.c._issue_certificate(a, "SETTLED"), "already issued")
        self.assertEqual(chain.view("get_certificate", aid), before)


class Invariant04FrozenSpecificationCannotChange(unittest.TestCase):
    def test_no_write_method_accepts_new_terms(self):
        chain, llm, aid = reach("CREATED")
        names = write_methods(chain)
        for forbidden in ("update_agreement", "edit_agreement", "set_worker", "set_specification", "set_requirements",
                          "set_amount", "set_deadline", "change_worker", "transfer"):
            self.assertNotIn(forbidden, names)

    def test_terms_are_identical_at_every_stage_of_a_full_dispute_lifecycle(self):
        chain, llm = new_chain()
        aid = create(chain)
        base = frozen_fields(chain.agreement(aid))
        reqs = chain.view("get_requirements", aid)
        defs = [(r["requirement_id"], r["description"], r["method"], r["evidence_requirements"], r["requirement_hash"]) for r in reqs]
        steps = [
            lambda: chain.tx(BUYER, "fund", aid, value=AMOUNT), lambda: chain.tx(WORKER, "accept", aid),
            lambda: chain.tx(WORKER, "start_work", aid),
            lambda: chain.tx(WORKER, "submit_deliverable", aid, "Each requirement is satisfied by the app.", default_evidence()),
            lambda: freeze_all(chain, aid), lambda: set_verdicts(llm, REQ_002="FAIL"),
            lambda: verify_all(chain, aid),
            lambda: chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=at._bond_for(AMOUNT)),
        ]
        for step in steps:
            step()
            self.assertEqual(frozen_fields(chain.agreement(aid)), base)
            got = [(r["requirement_id"], r["description"], r["method"], r["evidence_requirements"], r["requirement_hash"]) for r in chain.view("get_requirements", aid)]
            self.assertEqual(got, defs)

    def test_the_agreement_hash_commits_to_every_term(self):
        chain, llm = new_chain()
        aid = create(chain)
        a = chain.agreement(aid)
        parts = {"protocol": at.PROTOCOL, "protocol_version": at.PROTOCOL_VERSION, "agreement_id": aid, "buyer": a["buyer"],
                 "worker": a["worker"], "currency": a["currency"], "amount": a["amount"], "deadline": a["deadline"],
                 "spec_hash": a["spec_hash"], "requirements_hash": a["requirements_hash"], "policies_hash": a["policies_hash"],
                 "created_at": a["created_at"]}
        self.assertEqual(at._sha(at._canon(parts)), a["agreement_hash"])
        for key, val in (("worker", "0x" + "9" * 40), ("amount", "1"), ("deadline", 5), ("spec_hash", "0" * 64),
                         ("requirements_hash", "0" * 64), ("policies_hash", "0" * 64), ("buyer", "0x" + "8" * 40)):
            changed = dict(parts, **{key: val})
            self.assertNotEqual(at._sha(at._canon(changed)), a["agreement_hash"], key)

    def test_beneficiary_cannot_change_after_funding(self):
        chain, llm, aid = reach("FUNDED")
        worker = chain.agreement(aid)["worker"]
        chain.tx(WORKER, "accept", aid)
        self.assertEqual(chain.agreement(aid)["worker"], worker)
        for who in (BUYER, WORKER, STRANGER, OWNER):
            for name in ("set_worker", "transfer_agreement", "change_beneficiary"):
                self.assertFalse(hasattr(chain.c, name))


class Invariant05FrozenEvidenceCannotChange(unittest.TestCase):
    def test_bundle_is_identical_through_verification_challenge_dispute_and_finalization(self):
        chain, llm = new_chain()
        aid = create(chain)
        to_pending(chain, aid)
        bundle = chain.view("get_evidence_bundle", aid)
        root = chain.agreement(aid)["evidence_root"]
        set_verdicts(llm, REQ_002="FAIL")
        verify_all(chain, aid)
        self.assertEqual(chain.view("get_evidence_bundle", aid), bundle)
        chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.", value=at._bond_for(AMOUNT))
        chain.advance(at.RESPONSE_WINDOW + 1)
        chain.tx(STRANGER, "start_challenge_phase", aid)
        chain.tx(BUYER, "challenge_requirement", aid, "REQ-001", "The authentication claim is not established.", "E1", QUOTE,
                 "The quote shows data is returned and this is argued not to satisfy the requirement.")
        chain.advance(SEAT_WAIT)
        chain.tx(STRANGER, "seat_jury", aid)
        vote_all(chain, aid, ["WORKER", "BUYER", "BUYER"])
        chain.tx(STRANGER, "finalize_dispute", aid)
        self.assertEqual(chain.view("get_evidence_bundle", aid), bundle)
        self.assertEqual(chain.agreement(aid)["evidence_root"], root)

    def test_evidence_root_is_a_function_of_content(self):
        chain, llm, aid = reach("VERIFICATION_PENDING")
        a = chain.agreement(aid)
        rows = [[b["item_id"], b["kind"], b["source"], b["content_hash"], b["mutable"]] for b in chain.view("get_evidence_bundle", aid)]
        self.assertEqual(at._evidence_root(aid, rows), a["evidence_root"])
        rows[0][3] = "0" * 64
        self.assertNotEqual(at._evidence_root(aid, rows), a["evidence_root"])


class Invariant06And07ChallengeBounds(unittest.TestCase):
    def call(self, chain, aid, rid="REQ-001", who=BUYER):
        return chain.tx(who, "challenge_requirement", aid, rid, "A long enough claim text here.", "E1", QUOTE,
                        "A sufficiently long piece of reasoning to pass the length check.")

    def test_no_challenge_after_its_deadline_in_either_phase(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        chain.advance(at.CHALLENGE_WINDOW_STANDARD + 1)
        expect_raises(lambda: self.call(chain, aid), "deadline has passed")
        chain, llm, aid = reach("CHALLENGE")
        chain.advance(at.CHALLENGE_PHASE + 1)
        expect_raises(lambda: self.call(chain, aid), "deadline has passed")

    def test_no_challenge_against_a_nonexistent_requirement(self):
        chain, llm, aid = reach("VERIFIED_PASS")
        for rid in ("REQ-999", "", "REQ-01", "req-001", "REQ-001 ", "../x"):
            expect_raises(lambda r=rid: self.call(chain, aid, r), "unknown requirement")
        self.assertEqual(chain.view("get_challenges", aid), [])


class Invariant08CertificateCannotBeModified(unittest.TestCase):
    def certs(self):
        out = []
        chain, llm, aid = reach("SETTLED")
        out.append((chain, aid))
        chain, llm, aid = reach("FINALIZED")
        out.append((chain, aid))
        chain, llm, aid = reach("VERIFIED_FAIL")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        out.append((chain, aid))
        return out

    def test_any_edit_is_detected_by_the_hash_and_by_the_on_chain_anchor(self):
        for chain, aid in self.certs():
            cert = json.loads(chain.view("get_certificate", aid))
            onchain = chain.view("get_certificate_hash", aid)
            paths = list(leaf_paths(cert))
            self.assertGreater(len(paths), 40)
            for path in paths:
                forged = mutate(cert, path)
                rep = vcl.verify(json.dumps(forged), None, onchain)
                self.assertFalse(rep.valid(), "edit at %s went undetected" % (path,))

    def test_a_forger_who_recomputes_the_hash_is_caught_by_consistency_checks(self):
        undetected = []
        for chain, aid in self.certs():
            cert = json.loads(chain.view("get_certificate", aid))
            bundle = {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)}
            for path in leaf_paths(cert):
                if path == ("certificate_hash",):
                    continue
                forged = mutate(cert, path)
                forged["certificate_hash"] = vcl.sha(vcl.canon({k: v for k, v in forged.items() if k != "certificate_hash"}))
                if vcl.verify(json.dumps(forged), bundle).valid():
                    undetected.append(".".join(str(p) for p in path))
        allowed = {"finalized_at", "verification_timestamp", "dispute.beacon_round", "dispute.pool_size", "dispute.beacon"}
        unexpected = [p for p in undetected if p.split(".")[0] not in allowed and p not in allowed and not p.startswith("dispute.jurors")]
        self.assertEqual(unexpected, [], "hash-recomputing forgeries that verify: %r" % unexpected)

    def test_the_verifier_and_the_contract_share_the_same_scope_statement(self):
        self.assertEqual(vcl.module.STATEMENT, at.STATEMENT)
        self.assertEqual(vcl.module.JURY_SIZE, at.JURY_SIZE)
        self.assertEqual(vcl.module.JURY_QUORUM, at.JURY_QUORUM)
        self.assertEqual((vcl.module.DISPUTE_BOND_MIN, vcl.module.DISPUTE_BOND_DIVISOR), (at.DISPUTE_BOND_MIN, at.DISPUTE_BOND_DIVISOR))

    def test_verdict_and_settlement_forgeries_are_always_caught(self):
        chain, llm, aid = reach("VERIFIED_FAIL")
        chain.advance(at.DISPUTE_WINDOW + 1)
        chain.tx(BUYER, "claim_refund", aid)
        cert = json.loads(chain.view("get_certificate", aid))
        forgeries = [
            lambda c: c.update(final_verdict="PASS"),
            lambda c: c["settlement"].update(to_worker=c["amount"], to_buyer="0"),
            lambda c: c.update(terminal_state="SETTLED"),
            lambda c: c["requirements"][1].update(status="PASS"),
            lambda c: c["evidence"].update(root="0" * 64),
            lambda c: c["evidence"]["items"][0].update(content_hash="0" * 64),
            lambda c: c["requirements"][1]["verification"].update(verdict="PASS"),
            lambda c: c.update(worker="0x" + "9" * 40),
            lambda c: c.update(amount="1"),
            lambda c: c["policies"].update(dispute="NONE"),
            lambda c: c.update(dispute={"result": "WORKER_PREVAILED"}),
        ]
        for forge in forgeries:
            forged = json.loads(json.dumps(cert))
            forge(forged)
            forged["certificate_hash"] = vcl.sha(vcl.canon({k: v for k, v in forged.items() if k != "certificate_hash"}))
            self.assertFalse(vcl.verify(json.dumps(forged)).valid())


def leaf_paths(obj, prefix=()):
    if isinstance(obj, dict):
        for k in obj:
            yield from leaf_paths(obj[k], prefix + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaf_paths(v, prefix + (i,))
    else:
        yield prefix


def mutate(cert, path):
    forged = json.loads(json.dumps(cert))
    node = forged
    for p in path[:-1]:
        node = node[p]
    old = node[path[-1]]
    if isinstance(old, bool):
        node[path[-1]] = not old
    elif isinstance(old, int):
        node[path[-1]] = old + 1
    elif isinstance(old, str):
        node[path[-1]] = old + "x" if old else "x"
    else:
        node[path[-1]] = "changed"
    return forged


class Invariant09OnlyAuthorizedActors(unittest.TestCase):
    def test_every_restricted_action_refuses_every_unauthorized_caller(self):
        cases = [
            ("cancel", "FUNDED", (BUYER,), lambda a: (a,)),
            ("accept", "FUNDED", (WORKER,), lambda a: (a,)),
            ("start_work", "ACCEPTED", (WORKER,), lambda a: (a,)),
            ("submit_deliverable", "IN_PROGRESS", (WORKER,), lambda a: (a, "A statement that is long enough.", default_evidence())),
            ("freeze_evidence", "DELIVERED", (WORKER, BUYER), lambda a: (a,)),
            ("claim_refund", "TIMEOUT", (BUYER,), lambda a: (a,)),
            ("respond_dispute", "DISPUTED", (BUYER,), lambda a: (a, "A response that is long enough to pass.")),
            ("challenge_requirement", "CHALLENGE", (BUYER, WORKER), lambda a: (a, "REQ-001", "A long enough claim text here.", "E1", QUOTE,
                                                                             "A sufficiently long piece of reasoning to pass the length check.")),
        ]
        everyone = [BUYER, WORKER, STRANGER, OWNER, JURORS[6]]
        for method, state, allowed, args in cases:
            for who in everyone:
                if who in allowed:
                    continue
                chain, llm, aid = reach(state)
                snap = chain.snapshot()
                expect_raises(lambda: chain.tx(who, method, *args(aid)))
                self.assertEqual(chain.snapshot(), snap, "%s by %s changed state" % (method, who))

    def test_juror_only_actions(self):
        chain, llm, aid = reach("FINAL_REVIEW")
        for who in (BUYER, WORKER, STRANGER, OWNER):
            expect_raises(lambda: chain.tx(who, "commit_vote", aid, "a" * 64), "not a seated juror")
            expect_raises(lambda: chain.tx(who, "reveal_vote", aid, "WORKER", "saltsalt"), "not a seated juror")

    def test_owner_power_is_limited_to_the_treasury(self):
        chain, llm, aid = reach("FUNDED")
        for m, args in (("cancel", (aid,)), ("accept", (aid,)), ("claim_refund", (aid,))):
            expect_raises(lambda: chain.tx(OWNER, m, *args))
        expect_raises(lambda: chain.tx(OWNER, "withdraw"), "nothing to withdraw")
        self.assertEqual(int(chain.ledger_ok()["escrow_locked"]), AMOUNT)


class Invariant10TerminalStatesSettleDeterministically(unittest.TestCase):
    def test_every_terminal_state(self):
        for state in sorted(at.TERMINAL_STATES):
            chain, llm, aid = reach(state)
            a = chain.agreement(aid)
            chain.ledger_ok()
            if state == "CANCELLED":
                self.assertEqual((a["funded"], a["escrow_paid"], a["certificate_hash"]), (0, 0, ""))
                continue
            self.assertEqual((a["funded"], a["escrow_paid"]), (1, 1))
            self.assertEqual(int(a["settle_worker"]) + int(a["settle_buyer"]), AMOUNT)
            self.assertRegex(a["certificate_hash"], r"^[0-9a-f]{64}$")
            self.assertEqual(int(chain.view("get_accounting")["escrow_locked"]), 0)
            check_cert(chain, aid)

    def test_outcome_table(self):
        expected = {"SETTLED": (AMOUNT, 0), "REFUNDED": (0, AMOUNT)}
        for state, pair in expected.items():
            chain, llm, aid = reach(state)
            a = chain.agreement(aid)
            self.assertEqual((int(a["settle_worker"]), int(a["settle_buyer"])), pair)
        for votes, pair in ((("WORKER", "WORKER", "BUYER"), (AMOUNT, 0)), (("BUYER", "BUYER", "WORKER"), (0, AMOUNT)),
                            ((None, None, None), (0, AMOUNT)), (("WORKER", "BUYER", None), (0, AMOUNT))):
            chain, llm, aid = reach("FINALIZED", votes=votes)
            a = chain.agreement(aid)
            self.assertEqual((int(a["settle_worker"]), int(a["settle_buyer"])), pair)

    def test_same_inputs_give_the_same_certificate_hash(self):
        hashes = set()
        for _ in range(3):
            chain, llm, aid = reach("SETTLED")
            hashes.add(chain.view("get_certificate_hash", aid))
        self.assertEqual(len(hashes), 1)


if __name__ == "__main__":
    unittest.main()
