# Verification protocol

The guiding rule: **language models propose, code verifies.** A model can suggest a verdict and a quote. Only a quote that the contract itself finds verbatim in the frozen evidence can make a verdict count.

## 1. Requirements

Each requirement is one statement (`id` `REQ-001`…, `description`, `method`, `evidence_requirements`). Methods: `CODE_INSPECTION`, `DOCUMENT_INSPECTION`, `SCHEMA_CHECK`, `EXISTENCE_CHECK`. Each becomes a `Requirement` record with `req_hash = sha256(canonical JSON of the definition)`, and all of them together are bound by `requirements_hash`.

## 2. Evidence: submit, then freeze

`submit_deliverable` stores only references (a canonical JSON list). Nothing is fetched. Each `freeze_evidence` call fetches **the next item** once and stores it; the call that freezes the last item seals the evidence root. Freezing one item per transaction means a source that cannot reach consensus only blocks itself and never throws away items already frozen:

| Kind | Fetched with | Mutable? |
|---|---|---|
| `github_file` (repository, full 40-hex commit, path) | `web.get` of raw.githubusercontent.com at that commit, under `strict_eq` | no |
| `github_diff` (repository, commit) | `web.get` of the commit `.diff`, must start with `diff --git` | no |
| `github_pr` (repository, number, **head**: the full 40-hex head commit) | PR API via `web.render` under `strict_eq`; the resolved head must equal the pinned `head`, otherwise freezing is refused; then the compare `.diff` at the base and head shas | no: pinned to `head` |
| `url` | `web.render(mode="text")`, trimmed and cut to 20,000 characters inside the consensus block (rendered text is far more stable across validators than raw HTML) | **yes**, allowed only under `PERMISSIVE` |
| `text` | none | no |
| `artifact_hash`, `tx_reference` | none (a reference the verifier can only read as text) | no |

Each fetch runs in a closure that catches its own exceptions and returns a failure marker with a fixed message (never the host's error text, which can differ between validators), so an error can never escape a non-deterministic block and cause an undecidable transaction. `strict_eq` needs every validator to see byte-identical content. Content must be non-empty valid UTF-8, at most 20,000 characters per item and 60,000 in total, and no two items may have identical content.

If the freeze window (24 protocol hours) passes before every item is frozen, `expire_if_timed_out` discards the partial set, marks every requirement `INSUFFICIENT_EVIDENCE / EVIDENCE_NOT_FROZEN` and opens the dispute window, so the worker can still take the case to a jury.

The result is stored per item (`E1`, `E2`, …) with `content_hash = sha256(content)` and sealed by `evidence_root = sha256(canonical {agreement_id, items: [[id, kind, source, content_hash, mutable], …]})`. From this point the contract has no function that changes evidence.

## 3. Per-requirement verification

`verify_requirement(aid, rid)` may be called by anyone, once per requirement, while the agreement is `VERIFICATION_PENDING` and inside the verify window.

1. The contract builds a prompt containing the requirement, the frozen evidence in delimited blocks with a per-agreement nonce (so evidence cannot forge its own delimiters), and the worker's statement marked as untrusted and not evidence. The prompt tells the model that everything inside is data and never instructions.
2. The **leader** validator runs the model and normalises the JSON output in code: unknown verdicts are rejected, quotes are filtered down to those that are 6–400 characters, name an existing evidence item, and appear as a substring of that item after case- and whitespace-insensitive normalisation. At most four quotes survive.
3. Code applies the grounding rules:
   * `PASS` with no surviving quote becomes `INSUFFICIENT_EVIDENCE` with detail `UNGROUNDED_PASS`.
   * `CONFLICTING_EVIDENCE` is honoured only with quotes from at least two different items, otherwise it becomes `INSUFFICIENT_EVIDENCE` (`UNGROUNDED_CONFLICT`).
4. Every other **validator** independently (a) checks the leader's value has exactly the expected keys and types, (b) re-runs the quote filter on it (so a forged or fabricated quote is rejected even if the verdict matches), (c) runs its own model call, and (d) compares **only the categorical verdict**. It accepts either its own normalised verdict or its model's raw verdict (conflicting evidence counted as insufficient): a validator whose own PASS failed the quote filter can still confirm a leader PASS whose quotes did pass it, which avoids needless disagreement without weakening grounding, since the leader's quotes are re-checked in (b). Free text, quotes and reasons are not compared, because models never phrase things identically and consensus on prose is what makes LLM contracts undecidable.

The stored `result_json` is canonical JSON of `{verdict, detail, quotes, reason}`; the certificate carries its hash.

## 4. Adversarial pass (`ADVERSARIAL` policy)

For each requirement that currently `PASS`es, anyone can call `red_team_requirement`. A separate prompt asks a model to find a counterexample. `COUNTEREXAMPLE` counts only with at least one grounded quote (otherwise it is recorded as `UNSUBSTANTIATED` and changes nothing). A grounded counterexample turns the requirement into `INSUFFICIENT_EVIDENCE / CONFLICTING_EVIDENCE`, which the aggregation rule treats as not passing. Validators compare `COUNTEREXAMPLE` against `NO_ATTACK`. Under this policy `aggregate` refuses to run until every pass has been red-teamed, unless the verify window has expired (then un-red-teamed passes become `INSUFFICIENT_EVIDENCE / RED_TEAM_MISSING`). The challenge window is also longer (72 protocol hours instead of 24).

## 5. Aggregation

The overall result is derived by a fixed rule from the per-requirement `(status, detail)` pairs, never by a model:

1. any `FAIL` → `FAIL`
2. else any `CONFLICTING_EVIDENCE` detail → `CONFLICTING_EVIDENCE` (stored as `INSUFFICIENT_EVIDENCE` state)
3. else any non-`PASS` → `INSUFFICIENT_EVIDENCE`
4. else `PASS`

Requirements never judged before the window closes are filled as `INSUFFICIENT_EVIDENCE / TIMEOUT`, so a stalled verification can never turn into a pass. The verifiers re-derive the overall result from the certificate with the same rule.

## 6. Challenges

`challenge_requirement` lets the buyer challenge a passing requirement (while `VERIFIED_PASS`) and either party challenge in the `CHALLENGE` phase of a dispute (the worker a failing or insufficient requirement). A challenge must cite an existing evidence item and quote it; the contract rejects the transaction before any model runs if the quote is not verbatim in the frozen evidence. An auditor prompt then re-reads the same frozen evidence:

* buyer challenge: may only move the result to `FAIL` or `INSUFFICIENT_EVIDENCE`
* worker challenge: may only move it to `PASS`, and only with a grounded quote

Each side gets at most one challenge per requirement. An upheld challenge sets the requirement to its new verdict with detail `CHALLENGE_UPHELD`, recomputes the overall result and, if a pass turned into a non-pass, opens a fresh dispute window. An upheld challenge during the `CHALLENGE` phase extends that phase to at least 24 protocol hours from that moment, so a last-second challenge always leaves the other side time to answer. Validators compare only the ruling (`UPHELD` or `REJECTED`); the leader's `new_verdict` is applied after every validator has checked it is one the side is allowed to obtain, because models that agree a buyer's challenge is right often differ on FAIL versus INSUFFICIENT_EVIDENCE.

## 7. What this does not do

* It cannot verify anything not in the frozen evidence, so requirements like "is fast" or "has no bugs" should be written so that evidence can show them, or they will (correctly) come out `INSUFFICIENT_EVIDENCE`.
* A quote proves the words exist, not that they mean what the model says. That is why there is a red team, an auditor, a challenge and a jury.
* A model that is wrong in the same way on every validator is not caught by consensus. See `THREAT_MODEL.md`.
