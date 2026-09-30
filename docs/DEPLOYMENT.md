# Deployment

Everything below works from a phone browser and GitHub's web interface, except the optional command-line steps.

**Honest status:** the contract was never executed on a live GenLayer network by this project. This procedure follows the sibling projects' notes and the documented Studio flow. If a step fails, that is information: please file it.

## 0. Install and test locally (optional but recommended)

```bash
git clone <your fork> agenttrust && cd agenttrust
python3 --version                     # 3.10 or newer; only the standard library is used
python3 scripts/deploy/check_contract.py
python3 -m unittest discover -s tests -t .      # 283 tests, about 20 seconds
python3 tests/mutation_test.py                  # about 10 minutes, checks the tests catch bugs
python3 scripts/demo/run_demo.py --check        # the offline demo is reproducible
```

The browser test (`tests.frontend`) needs `pip install playwright && playwright install chromium`; it is skipped automatically when they are missing. GitHub Actions runs all of this on every push (`.github/workflows/tests.yml`), so you do not need a computer.

## 1. Deploy the contract on GenLayer Studio

1. Open GenLayer Studio and create a new contract file.
2. Paste the entire contents of `contracts/agenttrust.py`. It already has the two required header lines and no other comments, so no build step is needed. Check that the first line is `# v0.2.16`.
3. Deploy with **no constructor arguments**. The account that deploys becomes the owner (treasury only).
4. In Studio, call `get_protocol_info` and confirm it returns `AgentTrust 1.0`. Copy the contract address.

If Studio rejects the file for size (about 92 KB), tell the maintainers. Do not trim comments (there are none); the fix is to split the contract, which is a redesign.

### Testing the time windows without waiting days

```bash
python3 scripts/deploy/build_short_window.py 60
```

writes `build/agenttrust_short_window.py` where one protocol hour is 60 seconds (the script checks that the only change is the `WINDOW_UNIT` line). Deploy that copy **for testing only, never for real value**: the windows are too short to be safe. Minimum deadline becomes 60 seconds, so create test agreements with a deadline a few minutes ahead. With unit 60 the challenge phase lasts 48 minutes; `seat_jury` additionally waits until the drand round for the end of that phase is published (at most 30 seconds later) plus 60 seconds.

### Optional: deploy from a command line

`scripts/deploy/deploy.mjs` uses `genlayer-js@1.1.8`. It is untested here.

```bash
cd scripts/deploy && npm install
PRIVATE_KEY=0x<64 hex> node deploy.mjs
```

## 2. Point the frontend at the contract

Either paste the address into **Settings** on the page (stored in the browser only), or edit `frontend/assets/config.js`:

```js
window.AGENTTRUST_CONFIG = {
  contractAddress: "0x...",       // the address from step 1
  chain: "studionet",
  defaultMode: "live",            // "demo" shows the recorded offline demo
  ...
};
```

The frontend is static. Serve it from anywhere:

```bash
cd frontend && python3 -m http.server 8000     # then open http://localhost:8000
```

or enable GitHub Pages for the `frontend` folder (Settings → Pages → deploy from branch, folder `/frontend`; or copy its contents to a `gh-pages` branch).

In Live mode the page loads `genlayer-js@1.1.8` from esm.sh on demand and uses `createClient({ chain: studionet, account })` with an injected wallet. Reads need no wallet. Model steps (verify, red-team, challenge) can take minutes to reach consensus; the page waits up to ten minutes per transaction.

## 3. A first live walkthrough (small amounts)

Use three accounts (buyer, worker, anyone) and a short-window build.

1. Buyer: **Create** with the demo example, worker = the worker account, amount 1 GEN.
2. Buyer: **Fund** exactly 1 GEN. Worker: **Accept**, **Start work**.
3. Worker: **Submit** a `github_file` item pinned to a full commit sha of a public repository you control, then anyone: **Freeze evidence** (this fetches the file through validators).
4. Anyone: **Verification** → Verify each requirement, then Aggregate.
5. Wait for the challenge window, then **Settle**; the worker **withdraws**.
6. Open the **Certificate** page and confirm the in-browser check says VALID with the on-chain hash. Also run the command-line verifier on the downloaded files.

Then repeat with a failing requirement to test the refund path, and once with a dispute. For the dispute, register **three juror accounts** (neither the buyer nor the worker) on the **Jury** page with `register_juror` and 0.1 GEN each **before** the dispute is opened; only jurors registered earlier can be drawn. After the challenge phase, **Seat jury** fetches the drand round through validators: this is the first live test of the beacon, so record whether it reached consensus. Then each seated juror commits, reveals, and anyone finalizes.

## 4. What to record during your first live run

The first live run answers the open questions in `SECURITY.md`. Please note: whether the contract deployed (size), whether `freeze_evidence` reached consensus on real validators, how often two validators disagreed on a verdict, whether `withdraw` paid out, whether `seat_jury` fetched the drand round, and any transaction that ended `UNDETERMINED`. An `UNDETERMINED` transaction writes no state and can be sent again before its stage deadline.

## 5. Studio input hygiene

Type inputs with an English keyboard (a Persian comma after an id is a different string), clear left-over values from previous calls, and use full-width-free ASCII quotes in JSON arguments. Studio's read view can drop commas in some displays; the frontend does not use that view.
