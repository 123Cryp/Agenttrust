# Threat model

## Assets

Escrowed funds, juror stakes and dispute bonds; the integrity of the agreement terms; the integrity of the evidence; the integrity of the verdict; the meaning of a certificate.

## Assumptions

* GenLayer consensus is honest-majority: a majority of validators (and the leader-selection process) is not colluding.
* The contract runs as written on GenVM and the SDK behaves as documented.
* GitHub raw and diff URLs at a full commit sha are stable (a commit is content-addressed) and reachable by validators.
* The user's wallet and browser are not compromised, and the frontend is served unmodified.

## Actors and what each can try

| Actor | Attack | Defence | Residual risk |
|---|---|---|---|
| **Worker** | Change terms after funding | No edit function; hashes bind terms | none |
| | Swap the deliverable after freezing | Bytes fetched once and hashed; no rewrite function | none |
| | Point evidence at a branch or a mutable page so the content can later change | Branch references are rejected without touching the network; commits must be full 40-hex shas; URLs only under `PERMISSIVE` and always flagged mutable | With `PERMISSIVE`, content between submit and freeze can differ from what the buyer expected: the buyer should check the frozen evidence before verification |
| | Prompt-inject the verifier via evidence or statement | Untrusted-data framing, content-derived nonce fences, grounded quotes required, statement is not evidence | A subtle injection could still nudge a model toward a wrong-but-grounded verdict; red team, auditor and jury are the backstops |
| | Requirement wording games: make requirements trivially satisfiable | Requirements are frozen at acceptance and visible; the worker only accepts what it can meet | The buyer must write meaningful requirements; the protocol judges what was written |
| | Sybil jurors | Global staked pool; only jurors registered strictly before the dispute opened can be drawn; parties are never drawn; the draw uses a drand round nobody knows in advance; non-revealers lose their stake | A party that owns a large share of the whole pool is drawn proportionally more often. Slot filling and seed grinding are closed; patient pool capture is only priced, not prevented |
| | Make evidence unfreezable (e.g. the buyer deletes a repository it controls) | Items freeze one per transaction; after the freeze window the agreement becomes `INSUFFICIENT_EVIDENCE` with every requirement marked `EVIDENCE_NOT_FROZEN`, which the worker can dispute | The jury then decides without frozen evidence |
| | Refuse to act to stall | Every stage has a deadline with a defined default: no evidence frozen → insufficient, unverified → insufficient, no jury or jury deadlock → the automated result stands, timeout → refund | The escrow is locked until the relevant window elapses |
| **Buyer** | Fund and never let the worker accept | Cancel returns funds; worker never loses anything | none |
| | Withdraw escrow after acceptance | No function does; only the terminal paths pay out | none |
| | Claim failure to avoid paying | Verification needs quotes; challenges and a jury exist for the worker | A dishonest buyer plus a wrong verdict wins until disputed; the worker must post a bond to dispute |
| | Frivolous challenge or dispute to delay | One challenge per side per requirement; the bond's fee half is paid to the jury and its collateral half goes to the other party if the dispute is lost; fixed windows | Delay up to the window lengths |
| | Last-second challenge in the challenge phase | An upheld challenge extends the phase to at least 24 protocol hours from that moment, so the other side can answer | none |
| **Juror** | Copy another juror's vote | Commit-reveal; commitment binds the address and agreement | A juror who sees others' reveals cannot change theirs |
| | Reveal without committing, reveal late, reveal differently | Contract rejects each | none |
| | Collude with a party | Drawn at random from the pool; stake at risk if they do not reveal | Once drawn, three jurors can be bribed; bribes are outside the model |
| **Outsider** | Trigger stages out of order or early | Status and time guards | Anyone may trigger verification steps: this is intended, and each step's outcome does not depend on the caller |
| | Front-run or grind the seating | The beacon round is fixed when the challenge phase starts; eligibility is judged at the dispute's snapshot, so registering, exiting or filing challenges after that cannot change the draw | Whoever seats the jury cannot choose the outcome; if nobody seats it within the grace period the automated result stands |
| **drand beacon** | Serve a biased or different value | Every validator fetches the same round under `strict_eq`; round number and format are checked; value recorded in the certificate for public re-checking | The BLS signature is not verified on-chain; a compromised League of Entropy is out of scope |
| | Send wrong value | Credited to the sender's balance, not lost | none |
| **Leader validator** | Forge the result | Every validator re-checks the value and re-runs its own model; needs a majority | A colluding majority breaks everything, as with any GenLayer contract |
| | Return a plausible verdict with a fabricated quote | Quotes re-checked by every validator | none |
| **Model** | Hallucinate a quote | Quote filter drops it; a PASS without a surviving quote is downgraded | A hallucinated *verdict* with a real quote taken out of context |
| | Disagree with peers | Only the categorical verdict is compared; disagreement means the call fails and can be retried | Repeated failure could stall verification; the verify window then fills missing results as insufficient |
| **Evidence source** | Go down or return different bytes to different validators | `strict_eq` needs identical bytes; otherwise freezing fails and can be retried | A source that never serves stable bytes blocks freezing; the freeze window then ends in `INSUFFICIENT_EVIDENCE` |
| **Owner** | Steal funds | Can only withdraw the treasury, which by construction holds only dust and forfeitures | The owner learns nothing special and can do nothing else, including stopping the contract |
| **Frontend host** | Serve a modified page that sends different transactions | Static files; wallet shows the transaction | Verify the page hash or self-host; certificates can be checked with the CLI without the page |

## Attacks that are out of scope

Compromised validator majority; a bug in GenVM or genlayer-js; a wallet that signs what it is not shown; social engineering of either party; off-chain side agreements; anything that requires the model to know facts outside the frozen evidence.

## Known weak points, ranked

1. **Pool capture.** Someone who registers a large share of the juror pool ahead of time is drawn proportionally more often. The cheap, certain attacks are closed; the remaining defence is economic.
2. **Model quality.** Grounding guarantees a quote exists, not that it means what the model says. The protocol adds friction (red team, audit, jury); it does not add ground truth.
3. **Limited live testing.** One run on Studio; see `LIVE_TEST_REPORT.md` and `SECURITY.md`.
4. **No pause.** A bug found after deployment cannot be stopped in place.
5. **Party index growth.** Anyone can create agreements naming a victim and grow that address's index string; costs rise linearly for that address only. Not fixed.
6. **Contract size** (about 92 KB) is larger than any GenLayer contract this project has seen deployed; a size limit on Studio is unknown.
