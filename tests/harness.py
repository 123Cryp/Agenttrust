"""
Shared test harness. Loads contracts/agenttrust.py against the stub SDK and
models a chain with a controllable clock, transactional rollback (a reverting
transaction leaves no state change), and a native-value ledger:

  - value attached to a reverting payable call stays in the contract with no
    record (the ForesightVault lesson), tracked here as `stuck`
  - emit_transfer payouts leave the contract balance and land in `wallets`

    AT_MODULE=agenttrust python3 -m unittest discover -s tests -t .
"""
import copy
import importlib
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.environ.get("AT_CONTRACT_DIR") or os.path.join(ROOT, "contracts"))

import genlayer_stub  # noqa: E402

genlayer_stub.install()
at = importlib.import_module(os.environ.get("AT_MODULE", "agenttrust"))
gl = genlayer_stub.gl
NondetConsensusError = genlayer_stub.NondetConsensusError
Sequence = genlayer_stub.Sequence

START = 1_800_000_000
GEN = 10 ** 18


def addr(n):
    return genlayer_stub.Address("0x" + format(n, "040x"))


OWNER = addr(0xA0)
BUYER = addr(0xB1)
WORKER = addr(0xC2)
STRANGER = addr(0xD3)
JURORS = [addr(0xE0 + i) for i in range(8)]


class Chain:
    def __init__(self):
        genlayer_stub.reset()
        self.now = START
        at._now = lambda: self.now
        gl.message.sender_address = OWNER
        gl.message.value = genlayer_stub.u256(0)
        self.c = at.AgentTrust()
        self.balance = 0
        self.stuck = 0
        self.wallets = defaultdict(int)
        self.txs = 0
        self.check_views = True

    def advance(self, seconds):
        self.now += seconds

    def snapshot(self):
        return copy.deepcopy(self.c.__dict__)

    def tx(self, sender, method, *args, value=0):
        at._now = lambda: self.now
        before = self.snapshot()
        gl.message.sender_address = sender
        gl.message.value = genlayer_stub.u256(value)
        gl.transfers.clear()
        try:
            result = getattr(self.c, method)(*args)
        except BaseException:
            self.c.__dict__.clear()
            self.c.__dict__.update(before)
            self.balance += value
            self.stuck += value
            gl.transfers.clear()
            raise
        self.balance += value
        for who, amount in gl.transfers:
            self.balance -= amount
            self.wallets[who] += amount
        gl.transfers.clear()
        self.txs += 1
        return result

    def view(self, method, *args):
        at._now = lambda: self.now
        if not self.check_views:
            return getattr(self.c, method)(*args)
        before = self.snapshot()
        result = getattr(self.c, method)(*args)
        assert self.snapshot() == before, "view " + method + " mutated state"
        return result

    def agreement(self, aid):
        return self.view("get_agreement", aid)

    def status(self, aid):
        return self.view("get_agreement", aid)["status"]

    def ledger_ok(self):
        acc = self.view("get_accounting")
        i = {k: int(v) for k, v in acc.items()}
        held = i["escrow_locked"] + i["stakes_locked"] + i["bonds_locked"] + i["claimable_total"] + i["treasury"]
        assert i["total_in"] - i["total_out"] == held, "ledger identity broken: %r" % (acc,)
        assert self.balance - self.stuck == i["total_in"] - i["total_out"], "contract balance != ledger: %r" % (acc,)
        return acc


def expect_raises(fn, fragment=None):
    try:
        fn()
    except NondetConsensusError as e:
        if fragment is not None and fragment not in str(e):
            raise AssertionError("raised %s (expected %r)" % (e, fragment))
        return e
    except Exception as e:
        if fragment is not None and fragment not in str(e):
            raise AssertionError("raised %s: %s (expected to contain %r)" % (type(e).__name__, e, fragment))
        return e
    raise AssertionError("expected an exception containing %r, none raised" % (fragment,))
