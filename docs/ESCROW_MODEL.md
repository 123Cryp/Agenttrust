# Escrow model

Native GEN is the only currency. Value enters the contract through three payable functions (`fund`, `open_dispute`, `register_juror`) and leaves through two (`withdraw`, `withdraw_treasury`); `withdraw_juror_stake` only moves a juror's stake into their withdrawable balance. Nothing else moves value.

## The ledger identity

The contract keeps counters and asserts a single identity that the tests check after every step of every scenario and every fuzz run:

```
total_in - total_out == escrow_locked + stakes_locked + bonds_locked + claimable_total + treasury
```

and, in the test harness where the chain's real balance is known, `contract balance - value stuck by reverts == total_in - total_out`.

| Counter | Meaning |
|---|---|
| `escrow_locked` | Sum of amounts of funded agreements not yet paid out |
| `stakes_locked` | Stakes of jurors in the pool (held while registered, reduced when a non-revealing juror is slashed or a juror withdraws) |
| `bonds_locked` | Dispute bonds held |
| `claimable_total` | Sum of all withdrawable balances |
| `treasury` | Rounding dust and forfeited stakes with no eligible recipient |

## Payable functions never revert after receiving value

On a revert in GenVM the attached value stays in the contract with no record of it: this is how a payable call can silently destroy a user's funds. So `fund`, `open_dispute` and `register_juror` record `total_in` first, and every validation failure after that point does **not** revert. It credits the attached value to the sender's withdrawable balance and returns a message starting with `REJECTED:`. The only revert on a payable path is "no value attached", when there is nothing to lose. Tests check that a wrong amount, a wrong sender, a wrong state and an unknown agreement all leave the sender's money withdrawable.

## Pull payments

Settlement never sends anything. `_settle_escrow` credits `balances[worker]` and `balances[buyer]`, and each party calls `withdraw()`. A recipient whose address rejects transfers therefore can never block settlement, a certificate or another party's funds.

## One payout, exactly once

`_settle_escrow(agreement, to_worker, to_buyer)` requires `escrow_paid == 0`, `funded == 1` and `to_worker + to_buyer == amount`, sets `escrow_paid = 1`, releases `escrow_locked`, and credits the two balances. It is the only function that touches escrow, and every terminal transition calls it exactly once together with `_issue_certificate`, which refuses to run twice.

## Payout table

| Outcome | To worker | To buyer |
|---|---|---|
| `settle` after a passing result | amount | 0 |
| `claim_refund` after fail, insufficient evidence or timeout | 0 | amount |
| `cancel` after funding, before acceptance | 0 | amount |
| Jury: worker prevails | amount | 0 |
| Jury: buyer prevails | 0 | amount |
| Jury deadlock, too few reveals, or no jury seated, automated result PASS | amount | 0 |
| Jury deadlock, too few reveals, or no jury seated, automated result not PASS | 0 | amount |

Bond and stake movements are in `DISPUTE_MODEL.md`.

## Amount limits

Minimum 0.001 GEN, maximum 10^12 GEN. `fund` needs the attached value to equal the agreement amount exactly, so a partial or excess payment is never silently accepted.

## Not verified live

The behaviour of `gl.get_contract_at(Address(x)).emit_transfer(value=...)` (no `on=` argument) is taken from the GenVM documentation and from the sibling projects' notes; it was confirmed on GenLayer Studio (`LIVE_TEST_REPORT.md`): `withdraw` paid out and the balances matched. The stub reproduces the one failure mode reported in those notes (passing `on=` raises). Use a small amount before any real value is involved.
