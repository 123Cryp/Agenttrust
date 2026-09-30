# Security

**Status: not audited.** The contract and everything around it were tested offline against a stub SDK (see "How this was tested") and once by hand on GenLayer Studio (`LIVE_TEST_REPORT.md`). Treat any deployment as experimental and use small amounts.

## Security properties the design aims for

| # | Property | Enforced by |
|---|---|---|
| 1 | Terms never change after creation, and are bound to both parties at acceptance | No function edits an agreement's terms; `agreement_hash` and `frozen_hash` |
| 2 | Evidence never changes after freezing | One fetch, stored text and sha256, `evidence_root`; no function rewrites items |
| 3 | A verdict can only count if grounded | Quote must be a verbatim substring of frozen evidence, checked by the contract in the leader path and again by every validator |
| 4 | A model cannot push a result past a validator disagreement | Categorical key comparison; leader value fully re-validated; unknown shapes rejected |
| 5 | Every state change follows the transition table | `_enter` is the only writer of `status` |
| 6 | Only the right caller acts at the right time | `_only`, `_need`, `_before` at the top of every write; tests call every restricted method as every wrong caller |
| 7 | Money is conserved | Ledger identity asserted after every test step and fuzz step |
| 8 | Escrow is paid at most once | `escrow_paid` flag and `_settle_escrow` as the single payout path |
| 9 | Value sent by mistake is never lost | Payable functions credit rejected value instead of reverting |
| 10 | A hostile recipient cannot block settlement | Pull payments |
| 11 | Terminal agreements and certificates never change | Terminal states have no exits; a certificate is written once |
| 12 | The certificate can be verified without trusting anything | Two independent verifiers plus the on-chain hash |
| 13 | No party can choose or grind its jury | Pool snapshot at dispute opening; drand round fixed before it is published; eligibility judged at the snapshot |
| 14 | A dispute nobody attends never pays the loser | No jury or deadlock → the automated result stands |
| 15 | Jurors are paid regardless of which side wins | Half the bond is a jury fee paid to the majority (or to revealers on deadlock) |

## Contract-level defences

* **Prompt injection.** Evidence, requirement text and statements are labelled untrusted data. Evidence is fenced with a nonce derived from its own content, so it cannot forge its closing marker. The worker's statement is marked "not evidence", and a quote taken from it is rejected because quotes must come from evidence items. A model that obeys an injected "answer PASS" still cannot produce a grounded quote for something the evidence does not say.
* **Malicious leader.** Validators do not trust the leader's value: exact key set, types, verdict domain, every quote re-checked, then their own model run, then the categorical comparison.
* **Exceptions in non-deterministic blocks.** Every closure catches its own exceptions and returns a marker, so an error cannot escape and leave a transaction undecidable.
* **No `self` in closures**, no storage reads inside nondeterministic blocks, positional-only `run_nondet_unsafe`, leader value read from `.calldata` (all enforced by the AST lint `scripts/deploy/check_contract.py`).
* **Bounded loops and sizes.** At most 12 requirements, 10 evidence items, 3 seated jurors and 64 draws per seating, 100 list results; every text field has minimum and maximum lengths and control characters are rejected.
* **Replay and cross-agreement attacks.** Vote commitments include the agreement id and juror address; every id-keyed lookup includes the agreement id.
* **Owner power.** The owner can only withdraw the treasury. There is no pause, upgrade, parameter or forced-payout function, so there is also no emergency stop: a bug cannot be paused, only worked around by not using the contract.

## How this was tested

`python3 -m unittest discover -s tests -t .` runs 283 tests in about 20 seconds:

| Kind | Where | What |
|---|---|---|
| Unit | `tests/unit` | Creation validation, evidence parsing and freezing, grounding rules, transition table |
| Integration | `tests/integration` | Full lifecycles, challenges, escrow paths and conservation |
| State machine | `tests/unit/test_state_machine.py` | Every write function in every one of the 17 states; every state reachable; table equals the documented one |
| Adversarial | `tests/adversarial` | Malicious leaders, silent validators, fabricated and injected quotes, worker, buyer, juror and outsider misbehaviour, replay, timing |
| Security invariants | `tests/security` | Immutability, certificate tamper detection, access control of every restricted method, ledger identity, outcome table, static lint |
| Fuzz and property | `tests/fuzz` | 25 random-call sequences by default, 400 in a deeper sweep: illegal calls, hostile senders, random model behaviour; ghost-model invariants after every call. Garbage-input fuzzing of every parser and normaliser; canonical JSON and hash properties |
| Cross-implementation | `tests/js` | JavaScript and Python verifiers agree on thousands of corrupted inputs |
| Mutation | `tests/mutation_test.py` | 53 one-line mutants of the contract (removed guards, weakened checks, wrong payee…); every one must be killed by the suite, except one documented as equivalent (a defence-in-depth cap that the one-challenge-per-side rule already implies) |
| Frontend | `tests/frontend` | Headless Chromium: every route on a phone and desktop without console errors or horizontal scroll, hostile data is never parsed as HTML, in-browser verification agrees, a juror always reveals the vote they committed, evidence rows match the contract's schema, skip link and phone navigation |
| Forged certificates | `tests/security/test_forged_certificates.py` | Forgeries that recompute every hash are rejected by both verifiers with identical rows |

Bugs found this way and fixed included: value lost on reverts of payable calls, a certificate missing definitions the verifier needs, an evidence-kind check that raised a `TypeError` on unhashable input, and several verifier disagreements (see `CERTIFICATE_FORMAT.md`).

An independent review before release (three reviewers who had not seen the code being written: economics and access control, GenVM behaviour, frontend and verifiers) found and led to fixes for:

* **Jury capture.** A party could fill every candidate slot with refundable stakes and re-roll the selection seed with throwaway challenges. Replaced by a pre-registered pool, a snapshot at dispute opening and a drand beacon.
* **Stalemates paid the loser.** A deadlock or missing jury split the escrow 50/50. The automated result now stands.
* **Juror incentives.** Jurors were paid only when the disputer lost. They are now paid a fee either way.
* **Unfreezable evidence could not be disputed.** It now can, and freezing is one item per transaction.
* **Last-second challenges.** An upheld challenge at the end of the phase left the other side no time to reply. The phase is now extended.
* **Moving pull requests.** A `github_pr` item could move between submission and freezing. It is now pinned to a head commit.
* **Needless validator disagreement.** Two agreement rules caused unnecessary disagreement. The auditor now compares the ruling only, and the verifier accepts the validator's raw verdict.
* **Unbounded writes.** Storage writes grew with the total number of agreements. They now use append and a per-party index.
* **Zero-stake jurors and pool padding.** A juror could exit, withdraw and still be seated with nothing at risk; several seats shared one stake; throwaway addresses could dilute the pool. Fixed with one stake per seat, a longer exit delay and a 30-day minimum membership. The verifier's free-choice detail field is now restricted to its own values, and the beacon round follows a phase extension.
* **Frontend bugs.** A juror's reveal defaulted to the wrong vote, `artifact_hash` rows were rejected by the contract, and `REJECTED:` results and failed consensus showed as success.
* **Weak verifiers.** The verifiers accepted hash-recomputing forgeries that broke protocol rules.

## What was **not** verified

* **Limited live run.** One manual run on GenLayer Studio passed (`LIVE_TEST_REPORT.md`). The stub reproduces documented behaviour; it is not GenVM. Real LLM behaviour across many runs (agreement rates between validators, quote fidelity) is untested, and so are the paths listed at the end of the report.
* **Contract size.** About 92 KB. Studio accepted it. Other networks were not tried.
* **Escrow transfer API.** Worked on Studio (`withdraw` paid out). See `ESCROW_MODEL.md`.
* **drand beacon from GenVM.** Worked on Studio: every validator returned the same value. If the beacon cannot be fetched, seating fails cleanly and, after the grace period, the automated result stands.
* **Untested live.** Refunds, a buyer-side jury result, non-revealing jurors, challenges and the auditor, the red team, and `github_*` and `url` evidence.
* **No formal audit, no formal verification.** Mutation and fuzz testing raise confidence; they do not prove absence of bugs.
* **Economics.** Bond, stake and window sizes are reasoned, not simulated against adversaries.

## Reporting a vulnerability

Open a private security advisory on the repository, or contact the maintainers privately, rather than filing a public issue. Include the smallest scenario that reproduces the problem; `tests/scenario.py` makes that easy to write.
