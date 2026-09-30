"""
Stateful fuzzing. Random sequences of valid, invalid, hostile and mistimed calls are
run against the contract; after EVERY call the global invariants are re-checked
against a ghost model that only records what has been observed on the way.

Reproduce a failure with:  FUZZ_SEED=<n> python3 -m unittest tests.fuzz.test_fuzz_state_machine
"""
import json
import os
import random
import unittest

from scenario import *
from certs import check_cert

AMOUNTS = [10 * GEN, GEN, 3 * GEN + 7, at.MIN_AMOUNT, 100 * GEN]
ACTORS = [BUYER, WORKER, STRANGER, OWNER] + JURORS
WINDOWS = [0, 1, 60, 3600, at.FREEZE_WINDOW, at.CHALLENGE_WINDOW_STANDARD, at.DISPUTE_WINDOW, at.RESPONSE_WINDOW,
           at.CHALLENGE_PHASE, at.COMMIT_WINDOW, at.REVEAL_WINDOW, 31 * 24 * 3600]
QUOTE = "return jsonify(user), 200"


class FuzzLLM(ScriptedLLM):
    def __init__(self, rng):
        super().__init__()
        self.rng = rng
        self.calm = rng.random() < 0.5

    def __call__(self, prompt, mode, index):
        r = self.rng.random() if not self.calm else 0.9
        if r < 0.05:
            raise Exception("random model failure")
        if r < 0.08:
            return "not json"
        rid = self._rid(prompt)
        verdict = "PASS" if self.calm else self.rng.choice(["PASS", "PASS", "PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "WHATEVER"])
        if "You are one independent verifier" in prompt:
            quotes = self._quote(prompt, "src/app.py", QUOTE) + (self._quote(prompt, "src/auth.py", "abort(401)") if self.rng.random() < 0.5 else [])
            if not self.calm and self.rng.random() < 0.15:
                quotes = [{"evidence_id": "E1", "quote": "fabricated quote that is not in the evidence"}]
            return {"verdict": verdict, "quotes": quotes, "reason": "fuzz"}
        if "You are the CHALLENGER" in prompt:
            quotes = self._quote(prompt, "src/app.py", QUOTE) if self.rng.random() < 0.5 else []
            return {"outcome": "NONE_FOUND" if self.calm else self.rng.choice(["COUNTEREXAMPLE", "NONE_FOUND", "NONE_FOUND", "x"]), "claim": "fuzz", "quotes": quotes}
        return {"ruling": self.rng.choice(["UPHELD", "REJECTED", "REJECTED"]),
                "new_verdict": self.rng.choice(["PASS", "FAIL", "INSUFFICIENT_EVIDENCE", ""]),
                "quotes": self._quote(prompt, "src/app.py", QUOTE) if self.rng.random() < 0.6 else []}


class Ghost:
    def __init__(self):
        self.status = {}
        self.frozen = {}
        self.evidence = {}
        self.terminal = {}
        self.cert = {}
        self.paid = {}
        self.accepted = {}


class Fuzz:
    def __init__(self, seed, steps):
        self.seed, self.steps = seed, steps
        self.rng = random.Random(seed)
        validators = self.rng.choice([1, 1, 3])
        self.chain, _ = new_chain(validators=validators)
        self.chain.check_views = False
        gl.nondet.llm = FuzzLLM(self.rng)
        self.ghost = Ghost()
        self.log = []

    def pick(self):
        n = self.chain.view("agreement_count")
        if n == 0 or self.rng.random() < 0.06:
            return None
        return "AT-%d" % self.rng.randint(1, n)

    def arg_sets(self, aid, a):
        rng = self.rng
        rid = rng.choice(["REQ-001", "REQ-002", "REQ-003", "REQ-999"])
        amount = int(a["amount"]) if a else 10 * GEN
        text = "A sufficiently long statement text for this call."
        salt = "fuzz-salt-%d" % rng.randint(0, 3)
        vote = rng.choice(["WORKER", "BUYER", "MAYBE"])
        juror = rng.choice(JURORS)
        commit = commit_for(aid, juror, vote, salt) if rng.random() < 0.6 else "%064x" % rng.getrandbits(256)
        ev = rng.choice([default_evidence(), default_evidence(COMMIT_V2), evidence_json(COMMIT_V1, ["src/app.py"]),
                         '[{"kind":"github_file","repository":"%s","commit":"main","path":"src/app.py"}]' % REPO, "[]"])
        return [
            ("fund", "fund", [aid], {"value": rng.choice([amount, amount, amount - 1, amount + 1, 0])}, None),
            ("cancel", "cancel", [aid], {}, None),
            ("accept", "accept", [aid], {}, WORKER),
            ("start_work", "start_work", [aid], {}, WORKER),
            ("submit", "submit_deliverable", [aid, text, ev], {}, WORKER),
            ("freeze", "freeze_evidence", [aid], {}, None),
            ("verify", "verify_requirement", [aid, rid], {}, None),
            ("redteam", "red_team_requirement", [aid, rid], {}, None),
            ("aggregate", "aggregate", [aid], {}, None),
            ("expire", "expire_if_timed_out", [aid], {}, None),
            ("challenge", "challenge_requirement", [aid, rid, "A long enough claim text here.", rng.choice(["E1", "E2", "E7"]),
                                                    rng.choice([QUOTE, "abort(401)", "nonexistent quote text"]),
                                                    "A sufficiently long piece of reasoning to pass the length check."], {}, None),
            ("dispute", "open_dispute", [aid, rng.choice([rid, "REQ-001,REQ-002", ""]), "The verdict on this requirement is wrong."],
             {"value": rng.choice([at._bond_for(amount), at._bond_for(amount), at.DISPUTE_BOND_MIN, 1])}, None),
            ("respond", "respond_dispute", [aid, text], {}, None),
            ("join", "join_jury", [aid], {"value": rng.choice([at.JUROR_STAKE, at.JUROR_STAKE, 5])}, juror),
            ("phase", "start_challenge_phase", [aid], {}, None),
            ("seat", "seat_jury", [aid], {}, None),
            ("commit", "commit_vote", [aid, commit], {}, juror),
            ("reveal", "reveal_vote", [aid, vote, salt], {}, juror),
            ("finalize", "finalize_dispute", [aid], {}, None),
            ("settle", "settle", [aid], {}, None),
            ("refund", "claim_refund", [aid], {}, BUYER),
            ("withdraw", "withdraw", [], {}, None),
            ("treasury", "withdraw_treasury", [], {}, OWNER),
        ]

    def create_random(self):
        rng = self.rng
        reqs = rng.choice([REQUIREMENTS[:3], REQUIREMENTS[:2], REQUIREMENTS[:5], REQUIREMENTS[:1], []])
        try:
            aid = create(self.chain, verification=rng.choice(["STANDARD", "ADVERSARIAL"]), evidence=rng.choice(["STRICT", "PERMISSIVE"]),
                         dispute=rng.choice(["JURY", "JURY", "NONE"]), amount=rng.choice(AMOUNTS), reqs=reqs,
                         sender=rng.choice([BUYER, BUYER, STRANGER]), deadline_in=rng.choice([2 * 3600, 30 * 24 * 3600]))
            self.log.append("create -> " + aid)
        except Exception as e:
            self.log.append("create rejected: %s" % e)

    def try_tx(self, aid, sender, method, *args, value=0):
        self.log.append("macro %s %s" % (method, str(sender)[-4:]))
        try:
            self.chain.tx(sender, method, *args, value=value)
        except Exception:
            pass
        self.check(aid)

    def macro(self):
        rng, chain = self.rng, self.chain
        aid = self.pick()
        if aid is None or rng.random() < 0.25:
            self.create_random()
            n = chain.view("agreement_count")
            if n == 0:
                return
            aid = "AT-%d" % n
        a = chain.agreement(aid)
        amount = int(a["amount"])
        stages = rng.randint(1, 9)
        t = self.try_tx
        if stages >= 1:
            t(aid, BUYER, "fund", aid, value=amount)
        if stages >= 2:
            t(aid, WORKER, "accept", aid)
        if stages >= 3:
            t(aid, WORKER, "start_work", aid)
        if stages >= 4:
            t(aid, WORKER, "submit_deliverable", aid, "Each requirement is satisfied by src/app.py and src/auth.py.",
              rng.choice([default_evidence(), default_evidence(), default_evidence(COMMIT_V2)]))
        if stages >= 5:
            [t(aid, rng.choice([WORKER, BUYER]), "freeze_evidence", aid) for _ in range(3)]
        if stages >= 6:
            reqs = chain.view("get_requirements", aid) or []
            for r in reqs:
                if rng.random() < 0.9:
                    t(aid, STRANGER, "verify_requirement", aid, r["requirement_id"])
            if rng.random() < 0.5:
                for r in reqs:
                    t(aid, STRANGER, "red_team_requirement", aid, r["requirement_id"])
            t(aid, STRANGER, "aggregate", aid)
        if stages >= 7:
            if rng.random() < 0.4:
                r = rng.choice(["REQ-001", "REQ-002"])
                t(aid, rng.choice([BUYER, WORKER]), "challenge_requirement", aid, r, "A long enough claim text here.", "E1", QUOTE,
                  "A sufficiently long piece of reasoning to pass the length check.")
            if rng.random() < 0.5:
                st = chain.agreement(aid)["status"]
                who = WORKER if st in ("VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE") else BUYER
                t(aid, who, "open_dispute", aid, rng.choice(["REQ-001", "REQ-001,REQ-002"]), "The verdict on this requirement is wrong.",
                  value=at._bond_for(amount))
        if stages >= 8:
            for j in JURORS[:rng.randint(0, 5)]:
                t(aid, j, "join_jury", aid, value=at.JUROR_STAKE)
            chain.advance(at.RESPONSE_WINDOW + 1)
            t(aid, STRANGER, "start_challenge_phase", aid)
            chain.advance(SEAT_WAIT)
            t(aid, STRANGER, "seat_jury", aid)
        if stages >= 9:
            d = chain.view("get_dispute", aid)
            jurors = [j["address"] for j in d["jurors"]] if d else []
            votes = {j: rng.choice(["WORKER", "BUYER"]) for j in jurors}
            for j in jurors:
                if rng.random() < 0.9:
                    t(aid, j, "commit_vote", aid, commit_for(aid, j, votes[j], "fuzz-salt-1"))
            chain.advance(at.COMMIT_WINDOW + 1)
            for j in jurors:
                if rng.random() < 0.85:
                    t(aid, j, "reveal_vote", aid, votes[j], "fuzz-salt-1")
            chain.advance(at.REVEAL_WINDOW + 1)
            t(aid, STRANGER, "finalize_dispute", aid)
        if rng.random() < 0.6:
            chain.advance(rng.choice([at.CHALLENGE_WINDOW_STANDARD + 1, at.DISPUTE_WINDOW + 1, 40 * 24 * 3600]))
        for m, who in (("settle", STRANGER), ("expire_if_timed_out", STRANGER), ("claim_refund", BUYER), ("withdraw", WORKER),
                       ("withdraw", BUYER), ("withdraw", STRANGER)):
            if rng.random() < 0.6:
                t(aid, who, m, *([aid] if m != "withdraw" else []))

    def step(self):
        rng = self.rng
        r = rng.random()
        if r < 0.12:
            self.macro()
            return
        if r < 0.16:
            self.create_random()
            return
        if r < 0.28:
            secs = rng.choice(WINDOWS)
            self.chain.advance(secs)
            self.log.append("advance %d" % secs)
            return
        aid = self.pick()
        if aid is None:
            self.create_random()
            return
        a = self.chain.agreement(aid)
        choices = self.arg_sets(aid, a)
        name, method, args, kw, forced = rng.choice(choices)
        if rng.random() < 0.7:
            proper = {"fund": BUYER, "cancel": BUYER, "accept": WORKER, "start_work": WORKER, "submit": WORKER,
                      "freeze": rng.choice([BUYER, WORKER]), "dispute": rng.choice([BUYER, WORKER]), "refund": BUYER,
                      "challenge": rng.choice([BUYER, WORKER]), "respond": rng.choice([BUYER, WORKER]),
                      "treasury": OWNER}
            sender = forced or proper.get(name) or rng.choice(ACTORS)
            if name in ("commit", "reveal", "join") and rng.random() < 0.7:
                d = self.chain.view("get_dispute", aid)
                pool = ([j["address"] for j in d.get("jurors", [])] or d.get("candidates", []) or []) if d else []
                if name != "join" and pool:
                    sender = rng.choice(pool)
                    if name == "commit":
                        args = [aid, commit_for(aid, sender, rng.choice(["WORKER", "BUYER"]), "fuzz-salt-1")]
                    else:
                        args = [aid, rng.choice(["WORKER", "BUYER"]), "fuzz-salt-1"]
            if name == "join":
                sender = rng.choice(JURORS + [addr(0x3000 + rng.randint(0, 30))])
        else:
            sender = rng.choice(ACTORS)
        if name == "withdraw":
            sender = rng.choice(ACTORS)
        self.log.append("%s by %s %r" % (name, str(sender)[-4:], kw))
        try:
            self.chain.tx(sender, method, *args, **kw)
        except Exception:
            pass
        self.check(aid)

    def check(self, touched):
        chain, g = self.chain, self.ghost
        chain.ledger_ok()
        acc = chain.view("get_accounting")
        locked = 0
        for i in range(1, chain.view("agreement_count") + 1):
            aid = "AT-%d" % i
            a = chain.agreement(aid)
            old = g.status.get(aid)
            if old is not None and a["status"] != old:
                assert a["status"] in at.ALLOWED_EDGES[old], "illegal transition %s -> %s on %s" % (old, a["status"], aid)
            g.status[aid] = a["status"]
            fz = frozen_terms(a)
            assert g.frozen.setdefault(aid, fz) == fz, "terms of %s changed" % aid
            if a["accepted_at"]:
                assert g.accepted.setdefault(aid, a["frozen_hash"]) == a["frozen_hash"], "frozen_hash changed"
            if a["evidence_root"]:
                bundle = chain.view("get_evidence_bundle", aid)
                assert g.evidence.setdefault(aid, (a["evidence_root"], bundle)) == (a["evidence_root"], bundle), "evidence of %s changed" % aid
            if a["status"] in at.TERMINAL_STATES:
                snap = (a["status"], a["settle_worker"], a["settle_buyer"], a["certificate_hash"], chain.view("get_certificate", aid))
                assert g.terminal.setdefault(aid, snap) == snap, "terminal agreement %s changed" % aid
                if a["status"] != "CANCELLED":
                    assert a["certificate_hash"] and a["escrow_paid"] == 1, "terminal without certificate/payout"
                    assert int(a["settle_worker"]) + int(a["settle_buyer"]) == int(a["amount"])
                    rep = check_cert(chain, aid)
                else:
                    assert a["funded"] == 0
            else:
                assert not a["certificate_hash"] and a["escrow_paid"] == 0
            if a["funded"] and not a["escrow_paid"]:
                locked += int(a["amount"])
            if a["escrow_paid"]:
                assert g.paid.setdefault(aid, (a["settle_worker"], a["settle_buyer"])) == (a["settle_worker"], a["settle_buyer"]), "double payout"
            assert a["status"] not in ("VERIFIED_PASS", "SETTLED") or a["protocol_result"] == "PASS" or a["status"] == "VERIFIED_PASS" and a["protocol_result"] == "PASS", "pass without result"
            if a["status"] == "SETTLED":
                assert a["protocol_result"] == "PASS" and int(a["settle_worker"]) == int(a["amount"])
        assert locked == int(acc["escrow_locked"]), "escrow_locked %s != funded-and-unpaid %s" % (acc["escrow_locked"], locked)

    def run(self):
        for _ in range(self.steps):
            self.step()
        return self


def frozen_terms(a):
    keys = ("agreement_id", "buyer", "worker", "title", "description", "specification", "currency", "amount", "deadline",
            "evidence_policy", "verification_policy", "dispute_policy", "created_at", "spec_hash", "requirements_hash",
            "policies_hash", "agreement_hash", "requirement_ids")
    return tuple((k, json.dumps(a[k])) for k in keys)


def run_seed(seed, steps):
    f = Fuzz(seed, steps)
    try:
        f.run()
    except BaseException:
        print("\nFUZZ FAILURE seed=%d; last actions:\n  %s" % (seed, "\n  ".join(f.log[-25:])))
        raise
    return f


class StatefulFuzzTests(unittest.TestCase):
    def test_random_call_sequences_preserve_every_invariant(self):
        seeds = [int(os.environ["FUZZ_SEED"])] if "FUZZ_SEED" in os.environ else range(int(os.environ.get("FUZZ_RUNS", "25")))
        steps = int(os.environ.get("FUZZ_STEPS", "60"))
        reached = set()
        for seed in seeds:
            f = run_seed(seed, steps)
            reached |= set(f.ghost.status.values())
        if "FUZZ_SEED" not in os.environ:
            for needed in ("FUNDED", "VERIFICATION_PENDING", "VERIFIED_PASS", "SETTLED", "TIMEOUT", "REFUNDED"):
                self.assertIn(needed, reached, "fuzzer never reached " + needed)
            print("\nfuzz reached states:", sorted(reached))


if __name__ == "__main__":
    unittest.main()
