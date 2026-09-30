"""
Offline stub of the GenLayer SDK surface that contracts/agenttrust.py uses.

It is NOT GenVM. It runs no real LLM and no real network. It exists to test
the contract's own logic, and it is deliberately stricter than a naive mock:

  - run_nondet_unsafe runs the leader once and then EVERY validator with an
    independent LLM call; an exception raised by a validator is a disagreement
  - strict_eq re-executes the function for every validator and needs equality
  - the leader value reaches validator_fn as an object with `.calldata`
  - a hook forges the leader's result (malicious leader)
  - TreeMap / DynArray fields are zero-initialised, and assigning a plain dict
    to a TreeMap field raises (as GenVM does)
  - emit_transfer(value=...) records a payout; passing on= to it raises
  - gl.message.value models attached GEN

Transactional rollback and the value ledger live in tests/harness.py.
"""
import dataclasses
import sys
import types


class Address(str):
    pass


class u256(int):
    pass


class TreeMap(dict):
    def __class_getitem__(cls, item):
        return cls


class DynArray(list):
    def __class_getitem__(cls, item):
        return cls


def allow_storage(cls):
    return cls


dataclass = dataclasses.dataclass


class Contract:
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        for klass in reversed(cls.__mro__):
            for name, annotation in getattr(klass, "__annotations__", {}).items():
                if annotation is TreeMap:
                    object.__setattr__(instance, name, TreeMap())
                elif annotation is DynArray:
                    object.__setattr__(instance, name, DynArray())
        return instance

    def __setattr__(self, name, value):
        annotation = None
        for klass in type(self).__mro__:
            annotation = getattr(klass, "__annotations__", {}).get(name, annotation)
        if annotation is TreeMap and not isinstance(value, TreeMap):
            raise AssertionError("Is right the same storage type? TreeMap <- " + type(value).__name__)
        if annotation is DynArray and not isinstance(value, DynArray):
            value = DynArray(value)
        object.__setattr__(self, name, value)


class _Message:
    def __init__(self):
        self.sender_address = Address("0x00000000000000000000000000000000000000A1")
        self.value = u256(0)


class NondetConsensusError(Exception):
    pass


class _Return:
    def __init__(self, calldata):
        self.calldata = calldata


class _VM:
    NondetConsensusError = NondetConsensusError
    Return = _Return

    def __init__(self):
        self.validators = 1
        self.validator_runs = 0
        self.rounds = 0
        self._forced = None

    def force_leader_result(self, value):
        self._forced = (value,)

    def run_nondet_unsafe(self, leader_fn, validator_fn):
        nd = gl.nondet
        self.rounds += 1
        nd._enter("leader", 0)
        try:
            if self._forced is not None:
                leader_result = self._forced[0]
                self._forced = None
            else:
                leader_result = leader_fn()
        finally:
            nd._exit()
        agree = 0
        for i in range(self.validators):
            nd._enter("validator", i)
            try:
                ok = validator_fn(_Return(leader_result))
            except Exception:
                ok = False
            finally:
                nd._exit()
            self.validator_runs += 1
            if ok is True:
                agree += 1
        if agree * 2 <= self.validators:
            raise NondetConsensusError("validators rejected the leader result (%d/%d agreed)" % (agree, self.validators))
        return leader_result


class _EqPrinciple:
    def __init__(self):
        self._force_fail_once = False

    def force_fail_next(self):
        self._force_fail_once = True

    def strict_eq(self, fn):
        if self._force_fail_once:
            self._force_fail_once = False
            raise NondetConsensusError("forced disagreement (test)")
        nd = gl.nondet
        nd._enter("leader", 0)
        try:
            leader_value = fn()
        finally:
            nd._exit()
        agree = 0
        for i in range(gl.vm.validators):
            nd._enter("validator", i)
            try:
                same = fn() == leader_value
            except Exception:
                same = False
            finally:
                nd._exit()
            if same:
                agree += 1
        if agree * 2 <= gl.vm.validators:
            raise NondetConsensusError("strict_eq: validators saw a different value")
        return leader_value


class _Response:
    def __init__(self, status, body):
        self.status = status
        self.body = body


class Sequence:
    """A page whose body changes on every fetch (a source that moves)."""

    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def next(self):
        body = self.bodies[min(self.calls, len(self.bodies) - 1)]
        self.calls += 1
        return body


class _Web:
    def __init__(self):
        self.pages = {}
        self.statuses = {}
        self.calls = []
        self.handlers = []

    def _body(self, url):
        for prefix, fn in self.handlers:
            if url.startswith(prefix) and url not in self.pages:
                return fn(url)
        page = self.pages[url]
        return page.next() if isinstance(page, Sequence) else page

    def _known(self, url):
        return url in self.pages or any(url.startswith(p) for p, _ in self.handlers)

    def render(self, url, mode="text"):
        self.calls.append(("render", url))
        if not self._known(url):
            raise Exception("[stub] no page registered for url: " + url)
        return self._body(url)

    def get(self, url, headers=None):
        self.calls.append(("get", url))
        if not self._known(url):
            raise Exception("[stub] no page registered for url: " + url)
        return _Response(self.statuses.get(url, 200), self._body(url).encode("utf-8"))


class _Nondet:
    def __init__(self):
        self.web = _Web()
        self.llm = None
        self.prompts = []
        self.mode = None
        self.index = 0
        self._stack = []

    def _enter(self, mode, index):
        self._stack.append((self.mode, self.index))
        self.mode, self.index = mode, index

    def _exit(self):
        self.mode, self.index = self._stack.pop()

    def exec_prompt(self, prompt, response_format=None, images=None):
        self.prompts.append(prompt)
        if self.llm is None:
            raise Exception("[stub] exec_prompt called but no LLM handler is installed")
        return self.llm(prompt, self.mode, self.index)


def _view(fn):
    fn._gl_kind = "view"
    return fn


def _write(fn):
    fn._gl_kind = "write"
    return fn


def _payable(fn):
    fn._gl_kind = "write"
    fn._gl_payable = True
    return fn


class _WriteDecorator:
    payable = staticmethod(_payable)

    def __call__(self, fn):
        return _write(fn)


class _Public:
    write = _WriteDecorator()
    view = staticmethod(_view)


class _ContractHandle:
    def __init__(self, address):
        self.address = str(address)

    def emit_transfer(self, value=0, on=None):
        if on is not None:
            raise TypeError("SystemError: 2: inval (emit_transfer to an EOA takes only value=)")
        gl.transfers.append((self.address.lower(), int(value)))


class _GL:
    def __init__(self):
        self.Contract = Contract
        self.message = _Message()
        self.vm = _VM()
        self.eq_principle = _EqPrinciple()
        self.nondet = _Nondet()
        self.public = _Public()
        self.transfers = []

    def get_contract_at(self, address):
        return _ContractHandle(address)


gl = _GL()


def install():
    module = types.ModuleType("genlayer")
    module.gl = gl
    module.Address = Address
    module.u256 = u256
    module.TreeMap = TreeMap
    module.DynArray = DynArray
    module.allow_storage = allow_storage
    module.dataclass = dataclass
    module.Contract = Contract
    module.__all__ = ["gl", "Address", "u256", "TreeMap", "DynArray", "allow_storage", "dataclass", "Contract"]
    sys.modules["genlayer"] = module
    return module


def reset():
    gl.message.sender_address = Address("0x00000000000000000000000000000000000000A1")
    gl.message.value = u256(0)
    gl.eq_principle._force_fail_once = False
    gl.nondet.web.pages.clear()
    gl.nondet.web.statuses.clear()
    gl.nondet.web.calls.clear()
    gl.nondet.web.handlers.clear()
    gl.nondet.llm = None
    gl.nondet.prompts.clear()
    gl.nondet.mode = None
    gl.nondet.index = 0
    gl.nondet._stack.clear()
    gl.vm.validators = 1
    gl.vm.validator_runs = 0
    gl.vm.rounds = 0
    gl.vm._forced = None
    gl.transfers.clear()
