#!/usr/bin/env python3
"""
AgentTrust certificate verifier (protocol version 1.0).

Written from docs/CERTIFICATE_FORMAT.md, not by importing the contract. It
re-derives every hash and every derived field of a certificate and reports each
check as PASS, FAIL or SKIP (SKIP means the data needed for the check was not
supplied; a SKIP is never counted as a pass).

    python3 scripts/verification/verify_certificate.py cert.json
    python3 scripts/verification/verify_certificate.py cert.json --bundle bundle.json --onchain-hash <hash>

cert.json   the string returned by get_certificate(agreement_id)
bundle.json optional JSON {"evidence": <get_evidence_bundle>, "challenges": <get_challenges>}
            (a bare list is treated as the evidence bundle)

Exit status 0 only if no check FAILED. This proves the certificate is
self-consistent and grounded in the frozen evidence; anchoring it to a real
deployment needs --onchain-hash from get_certificate_hash().
"""
import hashlib
import json
import re
import sys

PROTOCOL = "AgentTrust"
VERSION = "1.0"
STATUSES = {"UNVERIFIED", "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"}
VERDICTS = {"PASS", "FAIL", "INSUFFICIENT_EVIDENCE"}
FINAL_VERDICTS = {"PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "NOT_VERIFIED"}
TERMINALS = {"SETTLED", "FINALIZED", "REFUNDED", "REFUNDED_BEFORE_ACCEPTANCE"}
DISPUTE_RESULTS = {"WORKER_PREVAILED", "BUYER_PREVAILED", "DEADLOCK_FALLBACK", "NO_JURY_FALLBACK"}
JURY_QUORUM = 2
MIN_AMOUNT = 10 ** 15
MAX_AMOUNT = 10 ** 30
POLICIES = {"evidence": {"STRICT", "PERMISSIVE"}, "verification": {"STANDARD", "ADVERSARIAL"}, "dispute": {"JURY", "NONE"}}
JURY_SIZE = 3
DISPUTE_BOND_MIN = 10 ** 17
DISPUTE_BOND_DIVISOR = 20
RESULT_NOTES = {"", "COMPLETE", "TIMEOUT_FILLED", "EVIDENCE_NOT_FROZEN"}
ADDR = re.compile(r"^0x[0-9a-f]{40}\Z")
STATEMENT = (
    "This certificate establishes that the submitted evidence, frozen at the recorded evidence root, "
    "satisfied or failed to satisfy the declared requirements under the declared verification protocol, "
    "as judged by GenLayer validator consensus and, where applicable, a staked jury. "
    "It is not a guarantee that the deliverable is correct, secure or fit for any purpose beyond those requirements."
)
REQ_ID = re.compile(r"^REQ-[0-9]{3}\Z")
SHA40 = re.compile(r"^[0-9a-f]{40}\Z")
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
DEC = re.compile(r"^[0-9]+\Z")
REQUIRED = [
    "protocol", "protocol_version", "statement", "agreement_id", "buyer", "worker", "currency", "amount", "deadline",
    "created_at", "accepted_at", "agreement_hash", "frozen_hash", "specification", "specification_hash",
    "requirements_hash", "policies", "policies_hash", "evidence", "requirements", "challenges", "final_verdict",
    "result_note", "terminal_state", "dispute", "settlement", "verification_timestamp", "finalized_at",
    "certificate_hash",
]


def is_int(value):
    return type(value) is int


def num(value):
    if not isinstance(value, str) or not DEC.match(value):
        raise ValueError("expected a decimal digit string, got %r" % (value,))
    return int(value)


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_ws(text):
    return " ".join(str(text).lower().split())


def grounded(quote, text):
    q = norm_ws(quote)
    return len(q) > 0 and q in norm_ws(text)


class Report:
    def __init__(self):
        self.rows = []

    def add(self, name, ok, detail=""):
        self.rows.append((name, "PASS" if ok else "FAIL", detail))

    def skip(self, name, detail):
        self.rows.append((name, "SKIP", detail))

    @property
    def failed(self):
        return [r for r in self.rows if r[1] == "FAIL"]

    def valid(self):
        return not self.failed

    def text(self):
        width = max(len(r[0]) for r in self.rows) if self.rows else 10
        lines = []
        for name, status, detail in self.rows:
            lines.append("%-4s  %s%s" % (status, name.ljust(width), ("  " + detail) if detail else ""))
        counts = {k: sum(1 for r in self.rows if r[1] == k) for k in ("PASS", "FAIL", "SKIP")}
        lines.append("")
        lines.append("CERTIFICATE %s  (%d passed, %d failed, %d skipped)" % (
            "VALID" if self.valid() else "INVALID", counts["PASS"], counts["FAIL"], counts["SKIP"]))
        return "\n".join(lines)


def derive_overall(pairs):
    statuses = [p[0] for p in pairs]
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(p[1] == "CONFLICTING_EVIDENCE" for p in pairs):
        return "CONFLICTING_EVIDENCE"
    if any(s != "PASS" for s in statuses):
        return "INSUFFICIENT_EVIDENCE"
    return "PASS"


def derive_requirement(req, challenges, adversarial, not_frozen=False):
    v = req.get("verification")
    if not_frozen:
        return "INSUFFICIENT_EVIDENCE", "EVIDENCE_NOT_FROZEN"
    if v is None:
        status, detail = "INSUFFICIENT_EVIDENCE", "TIMEOUT"
    else:
        status, detail = v["verdict"], v["detail"]
        if adversarial and status == "PASS":
            rt = req.get("redteam")
            if rt is None:
                status, detail = "INSUFFICIENT_EVIDENCE", "RED_TEAM_MISSING"
            elif rt["outcome"] == "COUNTEREXAMPLE":
                status, detail = "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"
    for ch in challenges:
        if ch["requirement_id"] == req["requirement_id"] and ch["status"] == "UPHELD":
            status, detail = ch["resolved_status"], "CHALLENGE_UPHELD"
    return status, detail


def verify(cert_text, bundle=None, onchain_hash=None):
    rep = Report()
    try:
        _verify_into(rep, cert_text, bundle, onchain_hash)
    except Exception as e:
        rep.add("certificate is structurally well formed", False, "%s: %s" % (type(e).__name__, e))
    return rep


def _verify_into(rep, cert_text, bundle, onchain_hash):
    try:
        cert = json.loads(cert_text) if isinstance(cert_text, str) else cert_text
    except Exception as e:
        rep.add("certificate is valid JSON", False, str(e))
        return
    if not isinstance(cert, dict):
        rep.add("certificate is a JSON object", False)
        return
    missing = [k for k in REQUIRED if k not in cert]
    rep.add("required fields present", not missing, "missing: " + ", ".join(missing) if missing else "")
    if missing:
        return
    rep.add("protocol and version", cert["protocol"] == PROTOCOL and cert["protocol_version"] == VERSION,
            "%s %s" % (cert["protocol"], cert["protocol_version"]))
    body = {k: v for k, v in cert.items() if k != "certificate_hash"}
    rep.add("certificate_hash matches contents", sha(canon(body)) == cert["certificate_hash"])

    spec = cert["specification"]
    rep.add("specification_hash", isinstance(spec, dict) and sha(canon(spec)) == cert["specification_hash"])

    reqs = cert["requirements"]
    defs = [r["definition"] for r in reqs]
    ids = [d["id"] for d in defs]
    rep.add("requirement ids well formed and unique", all(REQ_ID.match(i) for i in ids) and len(set(ids)) == len(ids) and len(ids) > 0)
    rep.add("requirements_hash", sha(canon(defs)) == cert["requirements_hash"])
    rep.add("each requirement_hash", all(sha(canon(r["definition"])) == r["requirement_hash"] for r in reqs))
    rep.add("policies_hash", sha(canon({"evidence": cert["policies"]["evidence"], "verification": cert["policies"]["verification"],
                                        "dispute": cert["policies"]["dispute"]})) == cert["policies_hash"])
    agreement_hash = sha(canon({
        "protocol": cert["protocol"], "protocol_version": cert["protocol_version"], "agreement_id": cert["agreement_id"],
        "buyer": cert["buyer"], "worker": cert["worker"], "currency": cert["currency"], "amount": cert["amount"],
        "deadline": cert["deadline"], "spec_hash": cert["specification_hash"], "requirements_hash": cert["requirements_hash"],
        "policies_hash": cert["policies_hash"], "created_at": cert["created_at"],
    }))
    rep.add("agreement_hash recomputed from its parts", agreement_hash == cert["agreement_hash"])
    if cert["accepted_at"] > 0:
        rep.add("frozen_hash (agreement frozen at acceptance)", sha(canon({
            "agreement_hash": cert["agreement_hash"], "accepted_at": cert["accepted_at"], "worker": cert["worker"]})) == cert["frozen_hash"])
    else:
        rep.add("frozen_hash empty when never accepted", cert["frozen_hash"] == "")

    amount = num(cert["amount"])
    pol = cert["policies"]
    rep.add("currency and amount within protocol limits", cert["currency"] == "GEN" and MIN_AMOUNT <= amount <= MAX_AMOUNT)
    rep.add("policies are known values", isinstance(pol, dict) and set(pol) == set(POLICIES) and all(pol[k] in POLICIES[k] for k in POLICIES))
    ev = cert["evidence"]
    items = ev["items"]
    iids = [i["item_id"] for i in items]
    rep.add("evidence item ids unique and sequential (E1, E2, ...)", iids == ["E" + str(n + 1) for n in range(len(iids))])
    ints = [cert[k] for k in ("deadline", "created_at", "accepted_at", "verification_timestamp", "finalized_at")]
    ints += [ev["any_mutable_source"]] + [i[k] for i in items for k in ("mutable", "length")]
    ints += [r[k] for r in cert["requirements"] for k in ("disputed", "challenge_count")]
    if cert["dispute"] is not None:
        ints += [cert["dispute"][k] for k in ("votes_worker", "votes_buyer", "revealed", "pool_size", "beacon_round")]
    rep.add("integer fields are integers (not booleans or strings)", all(is_int(x) for x in ints))
    if items:
        rows = [[i["item_id"], i["kind"], i["source"], i["content_hash"], i["mutable"]] for i in items]
        rep.add("evidence root recomputed", sha(canon({"agreement_id": cert["agreement_id"], "items": rows})) == ev["root"])
    else:
        rep.add("evidence root empty when nothing was frozen", ev["root"] == "")
    rep.add("any_mutable_source flag", is_int(ev["any_mutable_source"]) and ev["any_mutable_source"] == (1 if any(is_int(i["mutable"]) and i["mutable"] == 1 for i in items) else 0))
    kinds_ok = True
    for i in items:
        expected_mutable = 1 if i["kind"] == "url" else 0
        kinds_ok = kinds_ok and is_int(i["mutable"]) and i["mutable"] == expected_mutable
        if i["kind"] in ("github_file", "github_diff"):
            kinds_ok = kinds_ok and bool(re.search(r"@[0-9a-f]{40}(:|#)", i["source"]))
        if i["kind"] == "github_pr":
            kinds_ok = kinds_ok and bool(re.search(r"@[0-9a-f]{40}#pr", i["source"]))
    rep.add("mutable flags match kinds; github sources pinned to a full commit sha", kinds_ok)
    if cert["policies"]["evidence"] == "STRICT":
        rep.add("STRICT policy: no mutable evidence", not any(is_int(i["mutable"]) and i["mutable"] == 1 for i in items))

    adversarial = cert["policies"]["verification"] == "ADVERSARIAL"
    challenges = cert["challenges"]
    unverified_ok = cert["final_verdict"] == "NOT_VERIFIED"
    not_frozen = cert["result_note"] == "EVIDENCE_NOT_FROZEN"
    statuses_ok, quotes_ok, derived_pairs = True, True, []
    for r in reqs:
        if unverified_ok:
            statuses_ok = statuses_ok and r["status"] == "UNVERIFIED" and r["detail"] == "" and r["verification"] is None
            derived_pairs.append((r["status"], r["detail"]))
            continue
        if not_frozen:
            statuses_ok = statuses_ok and r["verification"] is None and r["redteam"] is None
        status, detail = derive_requirement(r, challenges, adversarial, not_frozen)
        statuses_ok = statuses_ok and r["status"] == status and r["detail"] == detail and r["status"] in STATUSES
        derived_pairs.append((status, detail))
        if r["verification"] is not None:
            statuses_ok = statuses_ok and sha(canon(r["verification"])) == r["verification_hash"]
            if r["verification"]["verdict"] == "PASS":
                statuses_ok = statuses_ok and len(r["verification"]["quotes"]) >= 1 and r["verification"]["detail"] == ""
            for q in r["verification"]["quotes"] + ((r["redteam"] or {}).get("quotes") or []):
                quotes_ok = quotes_ok and q["evidence_id"] in iids
        else:
            statuses_ok = statuses_ok and r["verification_hash"] == ""
        if r["redteam"] is not None:
            statuses_ok = statuses_ok and sha(canon(r["redteam"])) == r["redteam_hash"]
    rep.add("requirement statuses re-derived from their verification, red-team and challenge records", statuses_ok)
    rep.add("every cited quote names an existing evidence item", quotes_ok)
    struct_ok = True
    dispute_ids = set(cert["dispute"]["requirement_ids"].split(",")) if cert["dispute"] is not None else set()
    for r in reqs:
        n_ch = sum(1 for ch in challenges if ch["requirement_id"] == r["requirement_id"])
        struct_ok = struct_ok and r["requirement_id"] == r["definition"]["id"] and is_int(r["challenge_count"]) and r["challenge_count"] == n_ch
        struct_ok = struct_ok and is_int(r["disputed"]) and r["disputed"] == (1 if r["requirement_id"] in dispute_ids else 0)
        struct_ok = struct_ok and (r["redteam_hash"] == "") == (r["redteam"] is None)
        struct_ok = struct_ok and (r["redteam"] is None or adversarial)
    rep.add("requirement bookkeeping (ids, challenge counts, disputed flags, red-team fields)", struct_ok)

    if unverified_ok:
        rep.add("unverified work carries no verification, evidence or challenges",
                not items and not challenges and cert["result_note"] == "" and is_int(cert["verification_timestamp"]) and cert["verification_timestamp"] == 0)
    else:
        rep.add("final_verdict re-derived by the aggregation rule", derive_overall(derived_pairs) == cert["final_verdict"],
                "%s vs %s" % (derive_overall(derived_pairs), cert["final_verdict"]))
    rep.add("final_verdict is a known value", cert["final_verdict"] in FINAL_VERDICTS)

    ch_ok = True
    status_before = {}
    for r in reqs:
        v = r.get("verification")
        if v is not None:
            s = v["verdict"]
            if adversarial and s == "PASS":
                rt = r.get("redteam")
                s = "INSUFFICIENT_EVIDENCE" if (rt is None or rt["outcome"] == "COUNTEREXAMPLE") else s
            status_before[r["requirement_id"]] = s
    seen_pairs = set()
    for ch in challenges:
        key = (ch["requirement_id"], ch["side"])
        ch_ok = ch_ok and key not in seen_pairs and ch["requirement_id"] in ids and ch["side"] in ("BUYER", "WORKER")
        seen_pairs.add(key)
        ch_ok = ch_ok and ch["status"] in ("UPHELD", "REJECTED") and bool(HEX64.match(ch["challenge_hash"]))
        if ch["status"] == "REJECTED":
            ch_ok = ch_ok and ch["resolved_status"] == ch["original_status"]
        else:
            ch_ok = ch_ok and ch["resolved_status"] != ch["original_status"]
            ch_ok = ch_ok and (ch["resolved_status"] in ("FAIL", "INSUFFICIENT_EVIDENCE") if ch["side"] == "BUYER" else ch["resolved_status"] == "PASS")
        if ch["side"] == "BUYER":
            ch_ok = ch_ok and ch["original_status"] == "PASS"
        else:
            ch_ok = ch_ok and ch["original_status"] in ("FAIL", "INSUFFICIENT_EVIDENCE")
    for n, ch in enumerate(challenges, 1):
        ch_ok = ch_ok and ch["challenge_id"] == "CH-" + str(n)
        ch_ok = ch_ok and ch["challenger"] == (cert["buyer"] if ch["side"] == "BUYER" else cert["worker"])
    rep.add("challenges are structurally valid (one per side per requirement, side rules, outcome rules)", ch_ok)

    terminal = cert["terminal_state"]
    st = cert["settlement"]
    to_worker, to_buyer = num(st["to_worker"]), num(st["to_buyer"])
    rep.add("settlement adds up to the escrowed amount", to_worker >= 0 and to_buyer >= 0 and to_worker + to_buyer == amount)
    rep.add("terminal_state is known", terminal in TERMINALS)
    d = cert["dispute"]
    if terminal == "SETTLED":
        rep.add("SETTLED: passing verdict, no dispute, all to worker",
                cert["final_verdict"] == "PASS" and d is None and to_worker == amount)
    elif terminal == "REFUNDED":
        rep.add("REFUNDED: no dispute, everything back to buyer, never a passing verdict",
                d is None and to_buyer == amount and cert["final_verdict"] != "PASS")
    elif terminal == "REFUNDED_BEFORE_ACCEPTANCE":
        rep.add("REFUNDED_BEFORE_ACCEPTANCE: never accepted, everything back to buyer",
                d is None and to_buyer == amount and is_int(cert["accepted_at"]) and cert["accepted_at"] == 0)
    pre = True
    if terminal in ("SETTLED", "FINALIZED"):
        pre = pre and cert["accepted_at"] > 0 and cert["verification_timestamp"] > 0
    if terminal == "REFUNDED_BEFORE_ACCEPTANCE":
        pre = pre and cert["final_verdict"] == "NOT_VERIFIED" and is_int(cert["verification_timestamp"]) and cert["verification_timestamp"] == 0
    if d is not None:
        pre = pre and pol["dispute"] == "JURY"
    if challenges:
        pre = pre and cert["verification_timestamp"] > 0 and len(items) > 0
    if cert["final_verdict"] != "NOT_VERIFIED":
        pre = pre and cert["accepted_at"] > 0 and (len(items) == 0) == not_frozen
    rep.add("terminal state preconditions (acceptance, verification, evidence, dispute policy)", pre)
    if terminal == "FINALIZED":
        ok = d is not None and d["result"] in DISPUTE_RESULTS
        if ok:
            rw, rb, n = d["votes_worker"], d["votes_buyer"], d["votes_worker"] + d["votes_buyer"]
            ok = ok and is_int(d["revealed"]) and n == d["revealed"] and n <= len(d["jurors"])
            if d["result"] == "WORKER_PREVAILED":
                ok = ok and n >= JURY_QUORUM and rw * 2 > n and to_worker == amount
            elif d["result"] == "BUYER_PREVAILED":
                ok = ok and n >= JURY_QUORUM and rb * 2 > n and to_buyer == amount
            else:
                if d["result"] == "DEADLOCK_FALLBACK":
                    ok = ok and (n < JURY_QUORUM or rw * 2 == n)
                else:
                    ok = ok and len(d["jurors"]) == 0 and n == 0
                ok = ok and (to_worker == amount if cert["final_verdict"] == "PASS" else to_buyer == amount)
        rep.add("FINALIZED: dispute result follows the quorum and majority rule and the settlement follows the result", ok)
        if d is not None:
            dd_ok = d["side"] in ("BUYER", "WORKER")
            dd_ok = dd_ok and d["opened_by"] == (cert["buyer"] if d["side"] == "BUYER" else cert["worker"])
            dd_ok = dd_ok and num(d["bond"]) == max(DISPUTE_BOND_MIN, amount // DISPUTE_BOND_DIVISOR)
            ids_d = d["requirement_ids"].split(",")
            dd_ok = dd_ok and len(ids_d) == len(set(ids_d)) and all(i in ids for i in ids_d)
            by_id = {r["requirement_id"]: r for r in reqs}
            dd_ok = dd_ok and all(i in by_id for i in ids_d)
            dd_ok = dd_ok and len(d["jurors"]) == (0 if d["result"] == "NO_JURY_FALLBACK" else JURY_SIZE)
            dd_ok = dd_ok and len(set(d["jurors"])) == len(d["jurors"]) and all(ADDR.match(j) for j in d["jurors"])
            dd_ok = dd_ok and cert["buyer"] not in d["jurors"] and cert["worker"] not in d["jurors"]
            dd_ok = dd_ok and bool(HEX64.match(d["statement_hash"])) and bool(HEX64.match(d["response_hash"]))
            if d["result"] == "NO_JURY_FALLBACK":
                dd_ok = dd_ok and (d["beacon"] == "" or bool(HEX64.match(d["beacon"])))
            else:
                dd_ok = dd_ok and bool(HEX64.match(d["beacon"])) and d["beacon_round"] > 0 and d["pool_size"] >= JURY_SIZE
            rep.add("dispute block is well formed (opener, bond, targets, jurors, beacon)", dd_ok)
    rep.add("dispute block absent unless FINALIZED", (d is not None) == (terminal == "FINALIZED"))

    t = [cert["created_at"], cert["finalized_at"]]
    order_ok = cert["deadline"] > cert["created_at"] and cert["finalized_at"] >= cert["created_at"]
    if cert["accepted_at"] > 0:
        order_ok = order_ok and cert["accepted_at"] >= cert["created_at"]
    if cert["verification_timestamp"] > 0:
        order_ok = order_ok and cert["verification_timestamp"] <= cert["finalized_at"]
    rep.add("timestamps are ordered", order_ok and all(is_int(x) and x > 0 for x in t))
    rep.add("scope statement is the protocol's statement", cert["statement"] == STATEMENT)
    rep.add("result_note is a known value", cert["result_note"] in RESULT_NOTES)
    aggregated = cert["verification_timestamp"] > 0
    rep.add("verification_timestamp is set exactly when verification ran", aggregated == (cert["final_verdict"] != "NOT_VERIFIED" or cert["result_note"] == "EVIDENCE_NOT_FROZEN"))
    rep.add("parties are well-formed distinct addresses", bool(ADDR.match(cert["buyer"])) and bool(ADDR.match(cert["worker"])) and cert["buyer"] != cert["worker"])

    if bundle is None:
        rep.skip("evidence contents and quotes", "no --bundle supplied")
    else:
        evidence = bundle.get("evidence") if isinstance(bundle, dict) else bundle
        by_id = {e["item_id"]: e for e in (evidence or [])}
        ok = set(by_id) == set(iids)
        for i in items:
            e = by_id.get(i["item_id"])
            ok = ok and e is not None and sha(e["content"]) == i["content_hash"] == e["content_hash"] and len(e["content"]) == i["length"]
            ok = ok and e is not None and all(e[k] == i[k] and type(e[k]) is type(i[k]) for k in ("kind", "source", "mutable", "length"))
        rep.add("evidence bundle matches every frozen content hash and length", ok)
        gq = True
        for r in reqs:
            v = r.get("verification")
            for q in (v["quotes"] if v else []) + ((r.get("redteam") or {}).get("quotes") or []):
                gq = gq and q["evidence_id"] in by_id and grounded(q["quote"], by_id[q["evidence_id"]]["content"])
        rep.add("every quoted passage exists in the frozen evidence", gq)
        chs = bundle.get("challenges") if isinstance(bundle, dict) else None
        if chs is None:
            rep.skip("challenge hashes and quotes", "bundle has no challenges")
        else:
            cq = True
            for c in chs:
                body = {"challenge_id": c["challenge_id"], "requirement_id": c["requirement_id"], "side": c["side"],
                        "challenger": c["challenger"], "claim": c["claim"], "evidence_id": c["evidence_id"], "quote": c["quote"],
                        "reasoning": c["reasoning"], "original_status": c["original_status"], "status": c["status"],
                        "resolved_status": c["resolved_status"], "resolution": c["resolution"]}
                cq = cq and sha(canon(body)) == c["challenge_hash"]
                cq = cq and c["evidence_id"] in by_id and grounded(c["quote"], by_id[c["evidence_id"]]["content"])
                res = c["resolution"]
                upheld = c["status"] == "UPHELD"
                cq = cq and isinstance(res, dict) and res.get("ruling") == c["status"]
                cq = cq and res.get("new_verdict") == (c["resolved_status"] if upheld else "")
                rq = res.get("quotes") if isinstance(res.get("quotes"), list) else None
                cq = cq and rq is not None and all(isinstance(q, dict) and q.get("evidence_id") in by_id
                                                   and grounded(q.get("quote", ""), by_id[q["evidence_id"]]["content"]) for q in rq)
                cq = cq and not (upheld and c["side"] == "WORKER" and not rq)
            cq = cq and sorted(c["challenge_hash"] for c in chs) == sorted(c["challenge_hash"] for c in challenges)
            rep.add("challenge hashes recomputed, quotes grounded, auditor rulings consistent", cq)

    if onchain_hash is None:
        rep.skip("on-chain anchor", "no --onchain-hash supplied; the certificate is only self-consistent")
    else:
        rep.add("certificate_hash equals the hash recorded by the contract", onchain_hash.strip().lower() == cert["certificate_hash"])
    return


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    bundle, onchain = None, None
    if "--bundle" in argv:
        bundle = json.load(open(argv[argv.index("--bundle") + 1], encoding="utf-8"))
    if "--onchain-hash" in argv:
        onchain = argv[argv.index("--onchain-hash") + 1]
    report = verify(open(argv[0], encoding="utf-8").read(), bundle, onchain)
    print(report.text())
    return 0 if report.valid() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
