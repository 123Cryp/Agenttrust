# Live test report: GenLayer Studio

One manual campaign (five agreements, `AT-1` to `AT-5`) on GenLayer Studio, 30 September to 1 October 2026. It answers most of the open questions listed in `SECURITY.md`. It is a single run by one person with small amounts, not an audit.

## What was deployed

| | |
|---|---|
| Network | GenLayer Studio (explorer: explorer-studio.genlayer.com), full consensus, 5 initial validators per transaction |
| Contract | `0x9d04ea1E3C0BBA11c85e7325C87D2E009AcF3ccc` |
| Source | `contracts/agenttrust.py` with three constants changed for testing: `WINDOW_UNIT = 60` (one protocol hour is one minute), `JUROR_STAKE = 1 GEN` and `DISPUTE_BOND_MIN = 1 GEN` (Studio's value field accepts whole GEN only). Everything else is byte-identical. |
| Size | about 92 KB. Studio accepted it: the deploy transaction finalized with `SUCCESS`. |
| Accounts | five: buyer (also the deployer), worker, three jurors |

## Runs

**`AT-1`: simple path.** `create_agreement`, `fund` (1 GEN), `accept`, `start_work`, `submit_deliverable` (one `text` evidence item), `freeze_evidence`, `verify_requirement`, `aggregate`, `settle`, `withdraw`. The early `settle` reverted with "the challenge window is still open", as designed; the retry after the window returned `SETTLED`. The worker's `withdraw` returned `1000000000000000000` and the contract balance dropped by 1 GEN.

**`AT-2`: dispute path.** Three jurors registered first (`register_juror`, pool size 3). The worker submitted evidence that does not meet the requirement; verification returned `FAIL` with a grounded quote. Then:

| Step | Result |
|---|---|
| `open_dispute` (bond 1 GEN, from the worker) | `DISPUTED` |
| `respond_dispute` | `RESPONDED` |
| `start_challenge_phase` | `CHALLENGE`, `beacon_round` 6511907 |
| `seat_jury` | `FINAL_REVIEW`; every validator fetched the drand round and returned the same 64-hex value `7336b9f9…aeb2e0b3` |
| three `commit_vote`, three `reveal_vote` | all `SUCCESS` |
| `finalize_dispute` | `WORKER_PREVAILED`, votes 3 to 0 |
| balances | worker 1.5 GEN (escrow plus half the bond back), each juror `166666666666666666` wei (the jury fee split three ways) |
| four `withdraw` calls | all `SUCCESS`; contract balance fell from 5 GEN towards 3 GEN, the three juror stakes that stay in the pool |

The certificate hash (`8fa2c46f…d442`) equals the hash recorded by the contract. `scripts/verification/verify_certificate.py`, run on the real certificate and the real evidence bundle, passed all 38 checks. One caveat: that run used a copy of the verifier with the minimum bond set to 1 GEN, because the verifier checks the production minimum of 0.1 GEN and the test build uses 1 GEN.

**`AT-3`: refund path.** The verifier returned `VERIFIED_FAIL` for a requirement that the deliverable did not meet. With no dispute policy, `claim_refund` was immediate; the buyer's `withdraw` then returned the escrow. Both calls were `SUCCESS`.

**`AT-4`: challenge path.** After a passing verification the buyer called `challenge_requirement`. The auditor returned `REJECTED` and the requirement stayed passed. `settle` then succeeded and the worker's `withdraw` returned `1000000000000000000`.

**`AT-5`: jury rules for the buyer, one juror does not reveal.** The worker opened a dispute over a failed requirement (bond 1 GEN) and the buyer responded. Jury seating used the drand beacon (round 6512229). Three jurors committed; two revealed `BUYER` and the third deliberately did not.

| Step | Result |
|---|---|
| `finalize_dispute` | `BUYER_PREVAILED`, `votes_buyer` 2, `votes_worker` 0, `revealed` 2, `settled` 1 |
| buyer balance | `1500000000000000000` (escrow plus half the bond) |
| each revealing juror | `750000000000000000` (fee share plus returned stake) |
| non-revealing juror (`get_juror`) | `stake` 0, `removed_at` set, `open_seats` 0: stake forfeited and juror removed from the pool |
| `withdraw` by the buyer and both revealing jurors | all `SUCCESS`; contract balance fell from 5 GEN to 2 GEN, the two revealing jurors' stakes that stay in the pool |

**Frontend, live mode (read-only).** The hosted frontend, set to Live with the contract address, listed all five agreements and opened `AT-2` with its terms, frozen evidence, escrow and hashes; the certificate hash shown (`8fa2c46f…d442`) matches the one verified offline. Reads from the browser sometimes failed with `Failed to fetch` when many requests ran at once, so the frontend now reads one or two at a time and retries.

## What this confirms

* The contract loads and deploys under GenVM at about 92 KB.
* `payable` writes and `gl.message.value`: the exact-amount check works, and a wrong-sized `fund` was rejected with the value credited back instead of reverting.
* `emit_transfer(value=...)` pays out: `withdraw` moved money and the balances matched the ledger.
* Consensus on frozen evidence, on the verifier's verdict, and on the drand beacon fetch (`strict_eq`) was reached with the first attempt every time. No transaction ended `UNDETERMINED`; the one `ERROR` was the intended revert above.
* `DynArray.append` on storage records (`item_ids`, `all_ids`, juror seats) works.
* Every payout, fee and bond amount matched the hand-computed figures exactly, including the forfeited stake of a non-revealing juror: the 1 GEN stake went half to each revealer, and with the bond fee (0.25 GEN each) that gives the 0.75 GEN balances.
* The certificate produced on a live network verifies offline.

## Observations

* Studio lists each outbound transfer as a separate row with method `(constructor)` and status `ERROR`. The money did move; this appears to be how the explorer renders a transfer to an account.
* Studio's value field takes whole GEN, which is why the test build uses whole-GEN stakes and bonds.
* `seat_jury` is ready about 90 seconds after the challenge phase ends (the round is published within 30 seconds, and the contract waits a further 60).

## What this run did not exercise

* A deadlock and `NO_JURY_FALLBACK`.
* An upheld challenge, the red team, and `ADVERSARIAL` verification (a rejected challenge was exercised in `AT-4`).
* `github_file`, `github_diff`, `github_pr`, `url` and `artifact_hash` evidence; only `text` evidence was used.
* More than one evidence item, and the freeze-window expiry paths.
* Disagreement between validators, and sending transactions from the frontend with a wallet.
