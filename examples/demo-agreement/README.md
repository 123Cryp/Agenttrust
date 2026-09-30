# Demo agreement

Produced by `python3 scripts/demo/run_demo.py`: the real contract on the offline stub with scripted model answers. **This is a simulation, not evidence of how a live deployment behaves.** Regenerate with the command above; `--check` proves the committed files match.

| File | What it is |
|---|---|
| `agreement-input.json` | The arguments used to create agreement `AT-1` |
| `evidence-submission.json` | The evidence references submitted for `AT-1` |
| `certificate-settled.json` | Certificate of `AT-1`: passed, settled to the worker |
| `bundle-settled.json` | Frozen evidence texts and challenges for `AT-1` |
| `onchain-hash-settled.txt` | The hash the contract recorded for that certificate |
| `certificate-refunded-after-jury.json` | Certificate of `AT-2`: failed, disputed, buyer prevailed |
| `bundle-refunded-after-jury.json`, `onchain-hash-refunded-after-jury.txt` | Same for `AT-2` |

```bash
python3 ../../scripts/verification/verify_certificate.py certificate-settled.json \
    --bundle bundle-settled.json --onchain-hash "$(cat onchain-hash-settled.txt)"
node ../../frontend/assets/verify.js certificate-refunded-after-jury.json \
    --bundle bundle-refunded-after-jury.json --onchain-hash "$(cat onchain-hash-refunded-after-jury.txt)"
```

Try tampering: change any character of a certificate (for example the payout `to_worker`) and run the verifier again. It reports INVALID and names the checks that failed.
