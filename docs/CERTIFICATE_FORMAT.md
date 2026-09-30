# Certificate format (protocol 1.0)

A certificate is a JSON document sealed in the same transaction that moves the money (`SETTLED`, `FINALIZED`, or `REFUNDED`, including a refund before acceptance). `get_certificate(aid)` returns it as a string; `get_certificate_hash(aid)` returns its hash; `get_evidence_bundle(aid)` and `get_challenges(aid)` return the material the hashes refer to.

## Canonicalisation and hashing

```
canon(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
sha(s)   = sha256(utf8(s)).hexdigest()
```

All hashes below are `sha(canon(...))` of the described object. Keys are sorted by Unicode code point, all non-ASCII characters and everything outside space…`~` are `\uXXXX`-escaped (surrogate pairs for characters above U+FFFF), and only integers, strings, booleans, `null`, arrays and objects appear. **Amounts and payouts are decimal strings** so no JavaScript number can lose precision; timestamps are integers well below 2^53.

## Fields

| Field | Content |
|---|---|
| `protocol`, `protocol_version` | `"AgentTrust"`, `"1.0"` |
| `statement` | Fixed scope statement: what the certificate does and does not establish |
| `agreement_id`, `buyer`, `worker`, `currency`, `amount`, `deadline`, `created_at`, `accepted_at` | The agreement's identity and terms (`accepted_at` is 0 if never accepted) |
| `specification` | `{title, description, specification}`; `specification_hash = sha(canon(specification))` |
| `requirements[]` | See below; `requirements_hash = sha(canon([definitions]))` |
| `policies` | `{evidence, verification, dispute}`; `policies_hash = sha(canon(policies))` |
| `agreement_hash` | `sha(canon({protocol, protocol_version, agreement_id, buyer, worker, currency, amount, deadline, spec_hash, requirements_hash, policies_hash, created_at}))` |
| `frozen_hash` | `sha(canon({agreement_hash, accepted_at, worker}))`, or `""` if never accepted |
| `evidence` | `{root, items[], any_mutable_source}`; each item `{item_id, kind, source, content_hash, length, mutable}`; `root = sha(canon({agreement_id, items: [[item_id, kind, source, content_hash, mutable], …]}))`, or `""` if nothing was frozen |
| `challenges[]` | `{challenge_id, requirement_id, side, challenger, status, original_status, resolved_status, challenge_hash}` |
| `final_verdict` | `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE` or `NOT_VERIFIED` |
| `result_note` | `COMPLETE`, `TIMEOUT_FILLED`, `EVIDENCE_NOT_FROZEN` or empty |
| `terminal_state` | `SETTLED`, `FINALIZED`, `REFUNDED`, `REFUNDED_BEFORE_ACCEPTANCE` |
| `dispute` | `null`, or `{opened_by, side, requirement_ids, bond, result, votes_worker, votes_buyer, revealed, jurors[], pool_size, beacon_round, beacon, statement_hash, response_hash}`; `result` is `WORKER_PREVAILED`, `BUYER_PREVAILED`, `DEADLOCK_FALLBACK` or `NO_JURY_FALLBACK`; `beacon` is the drand randomness used to draw the jury (checkable against drand's public API) |
| `settlement` | `{to_worker, to_buyer}` as decimal strings summing to `amount` |
| `verification_timestamp`, `finalized_at` | Integers |
| `certificate_hash` | `sha(canon(certificate without this field))` |

Each `requirements[]` entry is `{requirement_id, definition, requirement_hash, status, detail, disputed, verification, verification_hash, redteam, redteam_hash, challenge_count}`; `verification_hash = sha(canon(verification))`, likewise for `redteam`.

The certificate contains hashes of challenge text, dispute statements and evidence contents rather than the text, to stay small. The text is in the **bundle** (`get_evidence_bundle`, `get_challenges`), which the verifier checks against those hashes.

## What the verifiers check (up to 40 checks with a full bundle)

1. **Structure:** required fields, protocol and version, currency `GEN` and an amount inside the protocol limits, known policy values and enums, evidence ids `E1, E2, …` in order, integer fields that really are integers (a boolean or a string is rejected, in both verifiers), well-formed distinct addresses, ordered timestamps, the exact scope statement.
2. **Hash tree:** `certificate_hash`, `specification_hash`, `requirements_hash`, each `requirement_hash`, `policies_hash`, `agreement_hash`, `frozen_hash`, `evidence.root`, every `verification_hash`, `redteam_hash`, `challenge_hash`.
3. **Evidence rules:** mutable flag matches kind, GitHub sources pinned to a 40-hex commit, no mutable evidence under `STRICT`, `any_mutable_source` consistent.
4. **Derivation:** each requirement's `(status, detail)` is re-derived from its verification, red-team and upheld-challenge records; the overall `final_verdict` is re-derived by the aggregation rule; a `PASS` verification must have a quote and empty detail.
5. **Challenges:** ids sequential, one per side per requirement, the right side for the original status, upheld challenges move to an allowed status.
6. **Preconditions of the terminal state:** `SETTLED` and `FINALIZED` need an accepted and verified agreement; a refund before acceptance carries no verdict, evidence or challenges; a dispute needs the `JURY` policy; challenges need verified, frozen evidence; frozen evidence is absent exactly when the note is `EVIDENCE_NOT_FROZEN`, in which case every requirement is `INSUFFICIENT_EVIDENCE / EVIDENCE_NOT_FROZEN`.
7. **Settlement:** sums to the amount; matches the terminal state (`SETTLED` all to worker with a `PASS`; `REFUNDED` all to buyer and never `PASS`; `FINALIZED` follows the jury quorum and majority rule, and for `DEADLOCK_FALLBACK` / `NO_JURY_FALLBACK` the payout follows the final verdict); the dispute block exists exactly when `FINALIZED`; bond equals `max(0.1 GEN, amount/20)`; three distinct jurors who are not the parties, drawn with a recorded beacon from a pool of at least three (none for `NO_JURY_FALLBACK`).
8. **With the bundle:** every evidence text hashes to its recorded `content_hash`, and its metadata and length match exactly; every cited quote is found in the corresponding evidence; every challenge recomputes to its hash, its quote is found in the evidence, and the auditor's record agrees with the outcome (same ruling, `new_verdict` equal to the resolved status when upheld, every auditor quote grounded, at least one for an upheld worker challenge).
9. **With the on-chain hash:** the certificate's `certificate_hash` equals the one the contract recorded.

A check whose input was not supplied is reported `SKIP`, never `PASS`. The document is **VALID** only if nothing FAILED.

## What VALID means

The document is internally consistent, the protocol's rules were followed, every recorded verdict follows from the recorded records, every quote exists in the frozen text, and (with the on-chain hash) this is the document the contract sealed. It does **not** mean the deliverable is correct.

Without the on-chain hash, anybody can construct a self-consistent forgery, because the hash is not a signature. Always compare against `get_certificate_hash` obtained from a node you trust, or against a block explorer.

## Two verifiers

`scripts/verification/verify_certificate.py` (Python 3, standard library) and `frontend/assets/verify.js` (Node and browsers, no dependencies, includes its own SHA-256) implement the same checks. `tests/js/test_js_verifier.py` feeds both thousands of randomly corrupted certificates and bundles and requires that they agree on validity and on every check row, and that every genuinely changed input is rejected. Differences found that way were fixed in both (for instance, trailing newlines accepted by Python's `$`, `0x7f` escaping, lenient integer parsing, and Python treating `True` as `1`). `tests/security/test_forged_certificates.py` additionally builds forgeries that recompute every hash (a jury result under the `NONE` policy, a settlement without acceptance, a foreign currency, boolean flags, a contradictory auditor record, …) and requires both verifiers to reject them with identical rows.

```
python3 scripts/verification/verify_certificate.py certificate.json --bundle bundle.json --onchain-hash <hash>
node frontend/assets/verify.js certificate.json --bundle bundle.json --onchain-hash <hash>
```

Both exit with status 0 only if nothing failed.

## Known limits of the format

* `lower()` and whitespace splitting in the grounding check follow Python semantics; the JavaScript port replicates the Python whitespace set explicitly. Exotic Unicode case-folding could in principle differ between engines; the shipped cases and a random-Unicode test agree.
* The certificate does not contain the model's raw output, only the normalised verdict, detail, quotes and reason.
* The certificate is not signed. Authenticity comes from the on-chain hash.
* The offline verifiers cannot recompute the jury draw (they do not hold the juror pool) or check the beacon against drand; `pool_size`, `beacon_round` and `beacon` are checked for form, and the draw can be re-derived from the contract's public pool with `_draw_index(beacon, agreement_id, k, pool_size)`.
