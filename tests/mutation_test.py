"""
Mutation check of the test suite. Each mutant is a one-line semantic change to a copy
of the contract; the suite must FAIL against every one of them. A surviving mutant
means a security-relevant behaviour is not pinned by any test.

    python3 tests/mutation_test.py            # all mutants
    python3 tests/mutation_test.py -k escrow  # only mutants whose name contains 'escrow'
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "contracts", "agenttrust.py")

MUTANTS = [
    ("stalemate-ignores-verdict", "        elif str(a.protocol_result) == R_PASS:\n            self._settle_escrow(a, amount, 0)", "        elif False:\n            self._settle_escrow(a, amount, 0)"),
    ("stalemate-pays-loser", "        else:\n            self._settle_escrow(a, 0, amount)\n        d.result", "        else:\n            self._settle_escrow(a, amount // 2, amount - amount // 2)\n        d.result"),
    ("edge-table-allows-skip", "    S_FUNDED: {S_ACCEPTED, S_REFUNDED, S_TIMEOUT},", "    S_FUNDED: {S_ACCEPTED, S_REFUNDED, S_TIMEOUT, S_SETTLED},"),
    ("terminal-state-reopens", "    S_SETTLED: set(),", "    S_SETTLED: {S_DISPUTED},"),
    ("transition-check-removed", "        if new_status not in ALLOWED_EDGES.get(a.status, set()):", "        if False:"),
    ("role-check-removed", "        if who != expected:\n            raise Exception(\"only the \" + role + \" can do this\")", "        if False:\n            raise Exception(\"only the \" + role + \" can do this\")"),
    ("fund-any-amount", "        if value != int(a.amount):\n            return self._reject_value", "        if value < int(a.amount):\n            return self._reject_value"),
    ("fund-any-sender", "        if who != a.buyer:\n            return self._reject_value(value, who, \"only the buyer can fund\")", "        if False:\n            return self._reject_value(value, who, \"only the buyer can fund\")"),
    ("reject-loses-value", "        self._credit(who, value)\n        return \"REJECTED: \"", "        return \"REJECTED: \""),
    ("escrow-double-payout-guard", "        if int(a.escrow_paid) != 0:\n            raise Exception(\"escrow already paid out\")", "        if False:\n            raise Exception(\"escrow already paid out\")"),
    ("escrow-sum-check", "        if to_worker < 0 or to_buyer < 0 or to_worker + to_buyer != amount:", "        if to_worker < 0 or to_buyer < 0:"),
    ("escrow-unfunded-guard", "        if int(a.funded) != 1:\n            raise Exception(\"agreement was never funded\")", "        if False:\n            raise Exception(\"agreement was never funded\")"),
    ("escrow-locked-not-released", "        self._sub(\"escrow_locked\", amount)\n        self._credit(str(a.worker), to_worker)", "        self._credit(str(a.worker), to_worker)"),
    ("settle-before-window", "        if _now() <= int(a.stage_deadline):\n            raise Exception(\"the challenge window is still open\")", "        if False:\n            raise Exception(\"the challenge window is still open\")"),
    ("settle-pays-buyer", "        self._settle_escrow(a, int(a.amount), 0)\n        self._issue_certificate(a, \"SETTLED\")", "        self._settle_escrow(a, 0, int(a.amount))\n        self._issue_certificate(a, \"SETTLED\")"),
    ("refund-anyone", "        self._only(self._sender(), a.buyer, \"buyer\")\n        self._need(a, S_TIMEOUT, S_FAIL, S_INSUFFICIENT)", "        self._need(a, S_TIMEOUT, S_FAIL, S_INSUFFICIENT)"),
    ("refund-skips-dispute-window", "        if a.status != S_TIMEOUT and a.dispute_policy == \"JURY\" and _now() <= int(a.stage_deadline):", "        if False:"),
    ("withdraw-keeps-balance", "        self.balances[who] = u256(0)\n        self._sub(\"claimable_total\", amount)\n        self._add(\"total_out\", amount)\n        gl.get_contract_at(Address(who))", "        self._sub(\"claimable_total\", amount)\n        self._add(\"total_out\", amount)\n        gl.get_contract_at(Address(who))"),
    ("treasury-any-caller", "        self._only(self._sender(), self.owner, \"owner\")\n        amount = int(self.treasury)", "        amount = int(self.treasury)"),
    ("treasury-not-reset", "        self.treasury = u256(0)\n        self._add(\"total_out\", amount)", "        self._add(\"total_out\", amount)"),
    ("fund-after-deadline", "        if _now() >= int(a.deadline):\n            return self._reject_value(value, who, \"the agreement deadline has passed\")", "        if False:\n            return self._reject_value(value, who, \"the agreement deadline has passed\")"),
    ("grounding-always-true", "    return len(q) > 0 and q in _norm_ws(text)", "    return True"),
    ("ungrounded-pass-accepted", "    if verdict == R_PASS and not quotes:\n        verdict, detail = R_INSUFFICIENT, \"UNGROUNDED_PASS\"", "    if False:\n        verdict, detail = R_INSUFFICIENT, \"UNGROUNDED_PASS\""),
    ("conflict-threshold", "        detail = \"CONFLICTING_EVIDENCE\" if len(ids) >= 2 else \"UNGROUNDED_CONFLICT\"", "        detail = \"CONFLICTING_EVIDENCE\" if len(ids) >= 1 else \"UNGROUNDED_CONFLICT\""),
    ("validator-checks-nothing", "def _check_verifier(value: dict, ctx: dict) -> bool:\n    if set(value.keys())", "def _check_verifier(value: dict, ctx: dict) -> bool:\n    return True\n    if set(value.keys())"),
    ("validator-key-constant", "def _key_verifier(value: dict) -> str:\n    return value[\"verdict\"]", "def _key_verifier(value: dict) -> str:\n    return \"PASS\""),
    ("counterexample-without-quote", "    return value[\"outcome\"] != \"COUNTEREXAMPLE\" or len(value[\"quotes\"]) >= 1", "    return True"),
    ("commit-hash-ignores-juror", "def _commit_hash(agreement_id: str, juror: str, vote: str, salt: str) -> str:", "def _commit_hash(agreement_id: str, juror: str, vote: str, salt: str) -> str:\n    juror = \"\""),
    ("reveal-before-commit-close", "        if now <= int(d.commit_deadline):\n            raise Exception(\"the commit window is still open\")", "        if False:\n            raise Exception(\"the commit window is still open\")"),
    ("double-reveal", "        if int(j.revealed) != 0:\n            raise Exception(\"already revealed\")", "        if False:\n            raise Exception(\"already revealed\")"),
    ('jury-late-registrants-eligible', '        if acc is None or int(acc.registered_at) >= snapshot:', '        if acc is None:'),
    ('jury-parties-eligible', '        if who == a.buyer or who == a.worker:\n            return False\n        acc = self.juror_accounts.get(who)', '        acc = self.juror_accounts.get(who)'),
    ('jury-exited-eligible', '        if int(acc.exit_at) != 0 and int(acc.exit_at) <= snapshot:\n            return False', '        if False:\n            return False'),
    ('jury-pool-not-snapshotted', '        pool_size = int(d.pool_size)\n', '        pool_size = len(self.juror_pool)\n'),
    ('jury-seed-ignores-beacon', '    return int(_sha(beacon + ":" + agreement_id + ":" + str(k)), 16) % n', '    return int(_sha(agreement_id + ":" + str(k)), 16) % n'),
    ('jury-beacon-margin-skipped', '        if now < _beacon_time(r) + BEACON_MARGIN:', '        if False:'),
    ('jury-duplicate-seat', '            if who not in chosen and self._eligible(a, who, snapshot):', '            if self._eligible(a, who, snapshot):'),
    ('juror-leaves-with-open-seat', '        if int(acc.open_seats) != 0:\n            raise Exception("the juror still has open seats")', '        if False:\n            raise Exception("the juror still has open seats")'),
    ('juror-exit-delay-skipped', '        if int(acc.exit_at) != 0 and _now() <= int(acc.exit_at) + JUROR_EXIT_DELAY:', '        if False:'),
    ('non-revealer-not-slashed', '                pool += self._close_seat(j, True)', '                pool += self._close_seat(j, False)'),
    ('collateral-to-disputer-on-loss', '            self._credit(opener if disputer_won else respondent, collateral)', '            self._credit(opener, collateral)'),
    ('fee-only-when-disputer-loses', '            self._distribute(majority, fee + pool)', '            self._distribute(majority, pool)\n            self._credit(opener, fee)'),
    ('seat-grace-ignored', '        if pool_size < JURY_SIZE or now > int(a.stage_deadline) + SEAT_GRACE:', '        if pool_size < JURY_SIZE:'),
    ('late-challenge-no-reply-window', '            elif a.status == S_CHALLENGE and int(a.stage_deadline) < _now() + REPLY_WINDOW:', '            elif False:'),
    ('pr-head-not-pinned', '        if head_sha != p["head"]:', '        if False:'),
    ('unfrozen-evidence-not-disputable', '                r.detail = "EVIDENCE_NOT_FROZEN"\n', '                r.status = R_UNVERIFIED\n'),
    ('freeze-duplicate-content', '            if str(prev.content_hash) == chash:', '            if False:'),
    ('auditor-key-includes-verdict', '    return value["ruling"]\n', '    return value["ruling"] + "|" + value["new_verdict"]\n'),
    ("challenge-cap", "        if len(a.challenge_ids) >= 2 * len(a.requirement_ids):", "        if False:"),
    ("buyer-only-challenge-pass", "            raise Exception(\"only the buyer can challenge a passing result\")", "            pass"),
    ("canon-unsorted", "    return json.dumps(obj, sort_keys=True, separators=(\",\", \":\"), ensure_ascii=True)", "    return json.dumps(obj, sort_keys=False, separators=(\",\", \":\"), ensure_ascii=True)"),
    ("canon-non-ascii", "    return json.dumps(obj, sort_keys=True, separators=(\",\", \":\"), ensure_ascii=True)", "    return json.dumps(obj, sort_keys=True, separators=(\",\", \":\"), ensure_ascii=False)"),
    ("evidence-kind-unchecked", "        if not isinstance(kind, str) or kind not in EVIDENCE_KINDS:", "        if False:"),
]


EQUIVALENT = {
    "challenge-cap": "unreachable: one challenge per side per requirement already bounds the count at 2 * requirements; kept as defence in depth",
}


def run(name, old, new, workdir):
    text = open(SOURCE, encoding="utf-8").read()
    if text.count(old) != 1:
        return "BROKEN", "pattern occurs %d times" % text.count(old)
    d = os.path.join(workdir, name)
    os.makedirs(d)
    with open(os.path.join(d, "agenttrust.py"), "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    env = dict(os.environ, AT_CONTRACT_DIR=d, PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-f"]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    return ("KILLED" if p.returncode != 0 else "SURVIVED"), p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""


def main(argv):
    only = argv[argv.index("-k") + 1] if "-k" in argv else ""
    workdir = tempfile.mkdtemp(prefix="at-mutants-")
    survived, broken, equivalent = [], [], []
    try:
        chosen = [m for m in MUTANTS if only in m[0]]
        for name, old, new in chosen:
            status, note = run(name, old, new, workdir)
            print("%-9s %s" % (status, name))
            if status == "SURVIVED" and name in EQUIVALENT:
                equivalent.append(name)
                print("          (equivalent mutant: %s)" % EQUIVALENT[name])
            elif status == "SURVIVED":
                survived.append(name)
            elif status == "BROKEN":
                broken.append((name, note))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    total = len(chosen)
    print("\n%d mutants: %d killed, %d equivalent (documented), %d survived, %d broken patterns" % (
        total, total - len(survived) - len(broken) - len(equivalent), len(equivalent), len(survived), len(broken)))
    for b in broken:
        print("  broken:", *b)
    for s in survived:
        print("  SURVIVED:", s)
    return 1 if survived or broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
