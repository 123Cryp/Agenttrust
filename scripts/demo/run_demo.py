#!/usr/bin/env python3
"""
Offline, deterministic AgentTrust demo. It runs the REAL contract (contracts/agenttrust.py)
against the stub GenLayer SDK in tests/, with a scripted stand-in for the validators' models.
Nothing here touches a network or a live chain, and the output says so.

    python3 scripts/demo/run_demo.py            # write frontend/assets/demo_run.{json,js} and examples/demo-agreement/*
    python3 scripts/demo/run_demo.py --check    # regenerate in memory and fail if the committed files differ
    python3 scripts/demo/run_demo.py --print    # print the timeline only

Scenarios (all on one contract instance, all reproducible byte for byte):
  AT-1  every requirement passes under ADVERSARIAL verification, the buyer's challenge is rejected,
        the window closes and the escrow is settled to the worker
  AT-2  a mix of PASS / FAIL / INSUFFICIENT_EVIDENCE, the worker disputes, a staked jury sides with the buyer
  AT-3  funded, waiting for the worker to accept
  AT-4  created, waiting for funding
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from scenario import (at, gl, BUYER, WORKER, STRANGER, JURORS, OWNER, GEN, REQUIREMENTS, REPO, COMMIT_V1, COMMIT_V2,  # noqa: E402
                      new_chain, default_evidence, evidence_json, commit_for, set_verdicts, SEAT_WAIT)

OUT_JSON = os.path.join(ROOT, "frontend", "assets", "demo_run.json")
OUT_JS = os.path.join(ROOT, "frontend", "assets", "demo_run.js")
EXAMPLE = os.path.join(ROOT, "examples", "demo-agreement")
LABELS = {str(BUYER): "buyer", str(WORKER): "worker", str(STRANGER): "anyone", str(OWNER): "owner"}
for i, j in enumerate(JURORS):
    LABELS[str(j)] = "juror-%d" % (i + 1)

DESCRIPTION = "A REST API with token authentication, user creation and lookup, rate limiting and a documented user schema."
SPEC = "Deliver a Flask service exposing POST /users and GET /users/{id} behind token authentication, with rate limiting and the published user JSON schema."
NOTE = ("OFFLINE SIMULATION. This data was produced by running the real contract code against a stub of the GenLayer SDK with a scripted "
        "stand-in for the validators' language models. No network, no live chain, no real funds and no real model judgement were involved. "
        "It demonstrates the protocol's mechanics and outputs; it is not evidence of how a live deployment will judge real work.")


class Demo:
    def __init__(self):
        self.chain, self.llm = new_chain(validators=3, jurors=0)
        self.steps = []

    def tx(self, sender, method, *args, value=0, note=""):
        result = self.chain.tx(sender, method, *args, value=value)
        shown = [a if not isinstance(a, str) or len(a) < 60 else a[:57] + "..." for a in args]
        aid = args[0] if args and isinstance(args[0], str) and args[0].startswith("AT-") else ""
        self.steps.append({
            "n": len(self.steps) + 1, "t": self.chain.now - self.t0, "agreement": aid, "actor": LABELS.get(str(sender), "someone"),
            "method": method, "args": shown[1:] if aid else shown, "value": str(value), "result": result if isinstance(result, (str, int)) else "ok",
            "status_after": self.chain.status(aid) if aid else "", "note": note,
        })
        return result

    def create(self, title, reqs, verification, evidence, amount, dispute="JURY"):
        return self.tx(BUYER, "create_agreement", title, DESCRIPTION, SPEC, str(WORKER), "GEN", amount, self.chain.now + 30 * 24 * 3600,
                       json.dumps(reqs), evidence, verification, dispute)

    def freeze(self, aid, note=""):
        while self.chain.status(aid) == "DELIVERED":
            self.tx(WORKER, "freeze_evidence", aid, note=note)
            note = ""

    def run(self):
        c = self.chain
        self.t0 = c.now
        for j in JURORS[:5]:
            self.tx(j, "register_juror", value=at.JUROR_STAKE, note="joins the global juror pool with a stake, before any dispute exists")
        c.advance(60)
        v2_all = evidence_json(COMMIT_V2, ["src/app.py", "src/auth.py", "docs/schema.json"])

        a1 = self.create("REST API for the acme user service", REQUIREMENTS, "ADVERSARIAL", "STRICT", 10 * GEN)
        self.tx(BUYER, "fund", a1, value=10 * GEN, note="escrow locked in the contract")
        self.tx(WORKER, "accept", a1, note="terms are now frozen")
        self.tx(WORKER, "start_work", a1)
        self.tx(WORKER, "submit_deliverable", a1, "All five requirements are implemented at the pinned commit.", v2_all, note="evidence is pinned to a full commit sha")
        self.freeze(a1, note="one item per call: the bytes are fetched once, hashed and stored; nothing later can change them")
        for r in c.view("get_requirements", a1):
            self.tx(STRANGER, "verify_requirement", a1, r["requirement_id"], note="validators quote the frozen evidence; the contract checks every quote")
        for r in c.view("get_requirements", a1):
            self.tx(STRANGER, "red_team_requirement", a1, r["requirement_id"], note="an adversarial pass tries to break the PASS")
        self.tx(STRANGER, "aggregate", a1, note="the overall result is derived by a fixed rule, not by a model")
        self.tx(BUYER, "challenge_requirement", a1, "REQ-002", "The handler may not return 201 on success.", "E1",
                'return jsonify(user), 201', "The buyer asks the auditor to re-examine the status code of the create handler against the frozen source.",
                note="auditor re-reads the same frozen evidence and rejects the challenge")
        c.advance(at.CHALLENGE_WINDOW_ADVERSARIAL + 1)
        self.tx(STRANGER, "settle", a1, note="challenge window closed; the full amount goes to the worker's withdrawable balance")
        self.tx(WORKER, "withdraw")

        a2 = self.create("REST API, second attempt", REQUIREMENTS, "STANDARD", "STRICT", 4 * GEN)
        self.tx(BUYER, "fund", a2, value=4 * GEN)
        self.tx(WORKER, "accept", a2)
        self.tx(WORKER, "start_work", a2)
        self.tx(WORKER, "submit_deliverable", a2, "Authentication and both endpoints are done; the schema file is in the docs folder.", default_evidence(),
                note="the worker forgot to include the schema file and there is no rate limiter")
        self.freeze(a2)
        set_verdicts(self.llm, REQ_004="FAIL")
        for r in c.view("get_requirements", a2):
            self.tx(STRANGER, "verify_requirement", a2, r["requirement_id"],
                    note={"REQ-004": "no rate limiter in the frozen source: FAIL",
                          "REQ-005": "the model says PASS but cannot quote any frozen evidence, so the contract downgrades it to INSUFFICIENT_EVIDENCE"}.get(r["requirement_id"], ""))
        self.tx(STRANGER, "aggregate", a2, note="one FAIL makes the overall result FAIL")
        bond = at._bond_for(4 * GEN)
        self.tx(WORKER, "open_dispute", a2, "REQ-004,REQ-005", "The verdict on both requirements is wrong and should be reviewed by a jury.", value=bond,
                note="the disputer stakes a bond")
        self.tx(BUYER, "respond_dispute", a2, "The evidence contains no rate limiter and no schema file, as the frozen bundle shows.")
        c.advance(at.RESPONSE_WINDOW + 1)
        self.tx(STRANGER, "start_challenge_phase", a2)
        self.tx(WORKER, "challenge_requirement", a2, "REQ-004", "The limiter may be configured elsewhere in the application.", "E1",
                "app = Flask(__name__)", "The worker asks the auditor to look again but cites only the application factory line, which shows no limiter.",
                note="rejected: the cited quote does not show a limiter")
        c.advance(SEAT_WAIT)
        self.tx(STRANGER, "seat_jury", a2, note="three jurors are drawn from the pool snapshot taken when the dispute opened, using a public drand beacon round fixed in advance")
        jurors = [j["address"] for j in c.view("get_dispute", a2)["jurors"]]
        votes = dict(zip(jurors, ["BUYER", "BUYER", "WORKER"]))
        for j in jurors:
            self.tx(j, "commit_vote", a2, commit_for(a2, j, votes[j], "demo-salt-" + j[-4:]), note="only a hash is visible during the commit window")
        c.advance(at.COMMIT_WINDOW + 1)
        for j in jurors:
            self.tx(j, "reveal_vote", a2, votes[j], "demo-salt-" + j[-4:])
        self.tx(STRANGER, "finalize_dispute", a2, note="majority sides with the buyer: half the bond pays the majority jurors, the other half goes to the buyer")
        self.tx(BUYER, "withdraw")
        for j in JURORS[:5]:
            if c.view("get_balance", str(j)) != "0":
                self.tx(j, "withdraw")

        a3 = self.create("Landing page copy", REQUIREMENTS[:2], "STANDARD", "PERMISSIVE", 2 * GEN)
        self.tx(BUYER, "fund", a3, value=2 * GEN, note="funded and waiting for the worker")
        a4 = self.create("Data cleaning script", REQUIREMENTS[:3], "STANDARD", "STRICT", 1 * GEN, dispute="NONE")
        return [a1, a2, a3, a4]

    def snapshot(self, aid):
        c = self.chain
        cert = c.view("get_certificate", aid)
        return {
            "agreement": c.view("get_agreement", aid), "requirements": c.view("get_requirements", aid),
            "evidence_bundle": c.view("get_evidence_bundle", aid), "challenges": c.view("get_challenges", aid),
            "dispute": c.view("get_dispute", aid), "certificate": cert, "certificate_hash": c.view("get_certificate_hash", aid) if cert else "",
        }


def build():
    d = Demo()
    ids = d.run()
    c = d.chain
    data = {
        "note": NOTE, "offline_simulation": True, "protocol": c.view("get_protocol_info"), "order": ids,
        "actors": {str(BUYER): "buyer", str(WORKER): "worker", str(OWNER): "owner", **{str(j): "juror-%d" % (i + 1) for i, j in enumerate(JURORS)}},
        "agreements": {aid: d.snapshot(aid) for aid in ids}, "timeline": d.steps, "accounting": c.view("get_accounting"),
        "wallets": {LABELS.get(k, k): str(v) for k, v in sorted(c.wallets.items())},
        "jurors": {str(j).lower(): c.view("get_juror", str(j)) for j in JURORS if c.view("get_juror", str(j))},
    }
    return data, d


def dumps(obj, indent=None):
    return json.dumps(obj, sort_keys=True, indent=indent, ensure_ascii=True, separators=(",", ":") if indent is None else (",", ": "))


def outputs(data):
    files = {OUT_JSON: dumps(data) + "\n", OUT_JS: "/* generated by scripts/demo/run_demo.py; do not edit */\nwindow.AGENTTRUST_DEMO = " + dumps(data) + ";\n"}
    a1, a2 = data["agreements"]["AT-1"], data["agreements"]["AT-2"]
    files[os.path.join(EXAMPLE, "agreement-input.json")] = dumps({
        "title": "REST API for the acme user service", "description": DESCRIPTION, "specification": SPEC, "worker": str(WORKER), "currency": "GEN",
        "amount": str(10 * GEN), "requirements": REQUIREMENTS, "evidence_policy": "STRICT", "verification_policy": "ADVERSARIAL", "dispute_policy": "JURY"}, 2) + "\n"
    files[os.path.join(EXAMPLE, "evidence-submission.json")] = dumps(json.loads(evidence_json(COMMIT_V2, ["src/app.py", "src/auth.py", "docs/schema.json"])), 2) + "\n"
    for name, snap in (("settled", a1), ("refunded-after-jury", a2)):
        files[os.path.join(EXAMPLE, "certificate-%s.json" % name)] = snap["certificate"] + "\n"
        files[os.path.join(EXAMPLE, "bundle-%s.json" % name)] = dumps({"evidence": snap["evidence_bundle"], "challenges": snap["challenges"]}, 2) + "\n"
        files[os.path.join(EXAMPLE, "onchain-hash-%s.txt" % name)] = snap["certificate_hash"] + "\n"
    return files


def main(argv):
    data, d = build()
    if "--print" in argv:
        for s in d.steps:
            print("%3d  +%-8s %-8s %-22s %-4s -> %s" % (s["n"], s["t"], s["actor"], s["method"], s["agreement"], s["status_after"] or s["result"]))
        return 0
    files = outputs(data)
    if "--check" in argv:
        stale = [p for p, text in files.items() if not os.path.exists(p) or open(p, encoding="utf-8").read() != text]
        for p in stale:
            print("STALE:", os.path.relpath(p, ROOT))
        print("demo outputs are reproducible and up to date" if not stale else "run: python3 scripts/demo/run_demo.py")
        return 1 if stale else 0
    for path, text in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", os.path.relpath(path, ROOT))
    for aid in ("AT-1", "AT-2"):
        print("%s -> %s (%s)" % (aid, data["agreements"][aid]["agreement"]["status"], json.loads(data["agreements"][aid]["certificate"])["final_verdict"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
