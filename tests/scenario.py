"""
Deterministic scenario fixtures shared by the tests and scripts/demo/run_demo.py:
a fake GitHub repository (two commits), a scripted LLM, and helpers that walk an
agreement through every stage.
"""
import json

from harness import (at, gl, Chain, BUYER, WORKER, STRANGER, JURORS, GEN, START, OWNER, OWNER, Sequence, addr,
                     expect_raises, NondetConsensusError)

REPO = "https://github.com/acme-agent/user-api"
COMMIT_V1 = "1111111111111111111111111111111111111111"
COMMIT_V2 = "2222222222222222222222222222222222222222"
RAW = "https://raw.githubusercontent.com/acme-agent/user-api/"

APP_V1 = '''from flask import Flask, request, jsonify
from auth import require_token

app = Flask(__name__)
USERS = {}


@app.route("/users", methods=["POST"])
@require_token
def create_user():
    data = request.get_json()
    user = {"id": len(USERS) + 1, "name": data["name"], "email": data["email"]}
    USERS[user["id"]] = user
    return jsonify(user), 201


@app.route("/users/<int:user_id>", methods=["GET"])
@require_token
def get_user(user_id):
    user = USERS.get(user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(user), 200
'''

APP_V2 = APP_V1.replace(
    "app = Flask(__name__)\n",
    "app = Flask(__name__)\nlimiter = Limiter(app, default_limits=[\"60 per minute\"])\n",
).replace("from auth import require_token", "from auth import require_token\nfrom flask_limiter import Limiter")

AUTH = '''from functools import wraps
from flask import request, abort

TOKEN = "secret"


def require_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.headers.get("Authorization") != "Bearer " + TOKEN:
            abort(401)
        return fn(*args, **kwargs)
    return wrapper
'''

SCHEMA = '{"User": {"id": "integer", "name": "string", "email": "string"}}\n'

REQUIREMENTS = [
    {"id": "REQ-001", "description": "Authentication is required on every endpoint.", "method": "CODE_INSPECTION",
     "evidence_requirements": "Source showing an authentication check applied to the endpoints."},
    {"id": "REQ-002", "description": "POST /users creates a user and returns 201.", "method": "CODE_INSPECTION",
     "evidence_requirements": "Source of the POST /users handler."},
    {"id": "REQ-003", "description": "GET /users/{id} returns the user or 404.", "method": "CODE_INSPECTION",
     "evidence_requirements": "Source of the GET /users/{id} handler."},
    {"id": "REQ-004", "description": "Rate limiting is implemented.", "method": "CODE_INSPECTION",
     "evidence_requirements": "Source showing a rate limiter configured for the API."},
    {"id": "REQ-005", "description": "API returns the specified JSON schema for users.", "method": "SCHEMA_CHECK",
     "evidence_requirements": "A schema file or handler output showing id, name and email fields."},
]

SNIPPETS = {
    "REQ-001": ("src/auth.py", 'abort(401)'),
    "REQ-002": ("src/app.py", '@app.route("/users", methods=["POST"])'),
    "REQ-003": ("src/app.py", 'return jsonify({"error": "not found"}), 404'),
    "REQ-004": ("src/app.py", 'limiter = Limiter(app, default_limits=["60 per minute"])'),
    "REQ-005": ("docs/schema.json", '"email": "string"'),
}


def demo_pages(web, v1=True):
    web.pages[RAW + COMMIT_V1 + "/src/app.py"] = APP_V1
    web.pages[RAW + COMMIT_V1 + "/src/auth.py"] = AUTH
    web.pages[RAW + COMMIT_V2 + "/src/app.py"] = APP_V2
    web.pages[RAW + COMMIT_V2 + "/src/auth.py"] = AUTH
    web.pages[RAW + COMMIT_V2 + "/docs/schema.json"] = SCHEMA


def evidence_json(commit, paths):
    return json.dumps([{"kind": "github_file", "repository": REPO, "commit": commit, "path": p} for p in paths])


def default_evidence(commit=COMMIT_V1):
    return evidence_json(commit, ["src/app.py", "src/auth.py"])


class ScriptedLLM:
    """A stand-in for the validators' language models.

    verifier[rid] / redteam[rid] / auditor[(rid, side)] hold either a dict
    {"verdict"|"outcome"|"ruling", ...} or a callable(index) -> dict, so a test can
    make validators disagree. Quotes are located in the prompt's evidence block
    by file path, so they are always real quotes of whatever evidence was frozen.
    """

    def __init__(self):
        self.verifier = {}
        self.redteam = {}
        self.auditor = {}
        self.calls = []

    @staticmethod
    def _items(prompt):
        out = {}
        for line in prompt.split("\n"):
            if line.startswith("<<<ITEM "):
                rest = line[len("<<<ITEM "):]
                meta = json.loads(rest[rest.index("{"):rest.rindex("}") + 1])
                out[meta["source"]] = meta["evidence_id"]
        return out

    def _quote(self, prompt, path, snippet):
        for source, eid in self._items(prompt).items():
            if source.endswith(":" + path) or (path and path in source):
                return [{"evidence_id": eid, "quote": snippet}]
        return []

    @staticmethod
    def _rid(prompt):
        for line in prompt.split("\n"):
            if line.startswith("REQUIREMENT ID: "):
                return line[len("REQUIREMENT ID: "):].strip()
        raise Exception("no requirement id in prompt")

    def __call__(self, prompt, mode, index):
        rid = self._rid(prompt)
        self.calls.append((mode, index, rid))
        if "You are one independent verifier" in prompt:
            spec = self.verifier.get(rid)
            if spec is None:
                path, snip = SNIPPETS[rid]
                spec = {"verdict": "PASS", "path": path, "snippet": snip, "reason": "The evidence shows it."}
            spec = spec(index) if callable(spec) else spec
            out = {"verdict": spec["verdict"], "reason": spec.get("reason", "scripted")}
            out["quotes"] = spec.get("quotes") if "quotes" in spec else (
                self._quote(prompt, spec["path"], spec["snippet"]) if spec.get("path") else [])
            return out
        if "You are the CHALLENGER" in prompt:
            spec = self.redteam.get(rid, {"outcome": "NONE_FOUND"})
            spec = spec(index) if callable(spec) else spec
            out = {"outcome": spec["outcome"], "claim": spec.get("claim", "none"), "reason": "scripted"}
            out["quotes"] = spec.get("quotes") if "quotes" in spec else (
                self._quote(prompt, spec["path"], spec["snippet"]) if spec.get("path") else [])
            return out
        if "You are the AUDITOR" in prompt:
            side = "BUYER" if "CHALLENGER SIDE: BUYER" in prompt else "WORKER"
            spec = self.auditor.get((rid, side), {"ruling": "REJECTED"})
            spec = spec(index) if callable(spec) else spec
            out = {"ruling": spec["ruling"], "new_verdict": spec.get("new_verdict", ""), "reason": "scripted"}
            out["quotes"] = spec.get("quotes") if "quotes" in spec else (
                self._quote(prompt, spec["path"], spec["snippet"]) if spec.get("path") else [])
            return out
        raise Exception("unknown prompt")


SEAT_WAIT = at.CHALLENGE_PHASE + at.BEACON_PERIOD + at.BEACON_MARGIN + 1


def beacon_value(round_number, salt=""):
    return at._sha("test-beacon:" + salt + str(round_number))


def serve_beacon(web, salt=""):
    def body(url):
        r = int(url.rsplit("/", 1)[1])
        return json.dumps({"round": r, "randomness": beacon_value(r, salt), "signature": "00", "previous_signature": "00"})
    web.handlers[:] = [h for h in web.handlers if h[0] != at.BEACON_URL] + [(at.BEACON_URL, body)]


def register_jurors(chain, jurors):
    for j in jurors:
        assert chain.tx(j, "register_juror", value=at.JUROR_STAKE) == "REGISTERED"
    if jurors:
        chain.advance(1)


def new_chain(validators=3, jurors=3):
    chain = Chain()
    gl.vm.validators = validators
    llm = ScriptedLLM()
    gl.nondet.llm = llm
    demo_pages(gl.nondet.web)
    serve_beacon(gl.nondet.web)
    register_jurors(chain, JURORS[:jurors])
    return chain, llm


def create(chain, verification="STANDARD", evidence="STRICT", dispute="JURY", amount=10 * GEN, reqs=None,
           worker=WORKER, deadline_in=30 * 24 * 3600, sender=BUYER):
    reqs = REQUIREMENTS[:3] if reqs is None else reqs
    return chain.tx(sender, "create_agreement", "Build a REST API", "A REST API with authentication and users.",
                    "Deliver a Flask service exposing POST /users and GET /users/{id} behind token authentication.",
                    str(worker), "GEN", amount, chain.now + deadline_in, json.dumps(reqs), evidence, verification, dispute)


def to_accepted(chain, aid, amount=10 * GEN):
    chain.tx(BUYER, "fund", aid, value=amount)
    chain.tx(WORKER, "accept", aid)
    return aid


def to_delivered(chain, aid, evidence=None, amount=10 * GEN):
    to_accepted(chain, aid, amount)
    chain.tx(WORKER, "start_work", aid)
    chain.tx(WORKER, "submit_deliverable", aid, "Each requirement is satisfied by src/app.py and src/auth.py.",
             evidence or default_evidence())
    return aid


def freeze_all(chain, aid, who=WORKER):
    out = None
    while chain.status(aid) == "DELIVERED":
        out = chain.tx(who, "freeze_evidence", aid)
    return out


def to_pending(chain, aid, evidence=None, amount=10 * GEN):
    to_delivered(chain, aid, evidence, amount)
    freeze_all(chain, aid)
    return aid


def verify_all(chain, aid, redteam=False):
    for r in chain.view("get_requirements", aid):
        chain.tx(STRANGER, "verify_requirement", aid, r["requirement_id"])
    if redteam:
        for r in chain.view("get_requirements", aid):
            if r["verdict"] == "PASS":
                chain.tx(STRANGER, "red_team_requirement", aid, r["requirement_id"])
    return chain.tx(STRANGER, "aggregate", aid)


def to_verified(chain, aid, **kw):
    to_pending(chain, aid)
    return verify_all(chain, aid, **kw)


def commit_for(aid, juror, vote, salt):
    return at._commit_hash(aid, str(juror).lower(), vote, salt)


def open_and_seat(chain, aid, n_jurors=0, side_requirements="REQ-001"):
    """Disputes the agreement (extra jurors register first) and seats the jury from the pool."""
    register_jurors(chain, JURORS[3:3 + n_jurors])
    st = chain.status(aid)
    disputer = WORKER if st in ("VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE") else BUYER
    bond = at._bond_for(int(chain.agreement(aid)["amount"]))
    out = chain.tx(disputer, "open_dispute", aid, side_requirements, "The verdict on this requirement is wrong.", value=bond)
    assert out == "DISPUTED", out
    chain.advance(at.RESPONSE_WINDOW + 1)
    chain.tx(STRANGER, "start_challenge_phase", aid)
    chain.advance(SEAT_WAIT)
    return chain.tx(STRANGER, "seat_jury", aid)


def set_verdicts(llm, **verdicts):
    """set_verdicts(llm, REQ_002="FAIL", REQ_003="INSUFFICIENT_EVIDENCE") -> scripted verifier answers."""
    for key, verdict in verdicts.items():
        rid = key.replace("_", "-")
        if verdict == "PASS":
            llm.verifier.pop(rid, None)
        else:
            llm.verifier[rid] = {"verdict": verdict, "reason": "scripted " + verdict}


def vote_all(chain, aid, votes, salt_base="salt-value-"):
    """votes: list of 'WORKER'/'BUYER'/None (None = juror never commits) for the seated jurors."""
    jurors = [j["address"] for j in chain.view("get_dispute", aid)["jurors"]]
    for j, vote in zip(jurors, votes):
        if vote is not None:
            chain.tx(j, "commit_vote", aid, commit_for(aid, j, vote, salt_base + j[-4:]))
    chain.advance(at.COMMIT_WINDOW + 1)
    for j, vote in zip(jurors, votes):
        if vote is not None:
            chain.tx(j, "reveal_vote", aid, vote, salt_base + j[-4:])
    if any(v is None for v in votes):
        chain.advance(at.REVEAL_WINDOW + 1)
    return jurors


STATES = ["CREATED", "FUNDED", "ACCEPTED", "IN_PROGRESS", "DELIVERED", "VERIFICATION_PENDING", "VERIFIED_PASS",
          "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE", "DISPUTED", "CHALLENGE", "FINAL_REVIEW", "FINALIZED", "SETTLED",
          "TIMEOUT", "CANCELLED", "REFUNDED"]


def reach(state, verification="STANDARD", dispute="JURY", votes=("WORKER", "WORKER", "BUYER")):
    """Builds a fresh chain and agreement in the requested state. Returns (chain, llm, aid)."""
    chain, llm = new_chain()
    aid = create(chain, verification=verification, dispute=dispute)
    if state == "CREATED":
        return chain, llm, aid
    if state == "CANCELLED":
        chain.tx(BUYER, "cancel", aid)
        return chain, llm, aid
    chain.tx(BUYER, "fund", aid, value=10 * GEN)
    if state == "FUNDED":
        return chain, llm, aid
    if state == "REFUNDED":
        chain.tx(BUYER, "cancel", aid)
        return chain, llm, aid
    if state == "TIMEOUT":
        chain.advance(31 * 24 * 3600)
        chain.tx(STRANGER, "expire_if_timed_out", aid)
        return chain, llm, aid
    chain.tx(WORKER, "accept", aid)
    if state == "ACCEPTED":
        return chain, llm, aid
    chain.tx(WORKER, "start_work", aid)
    if state == "IN_PROGRESS":
        return chain, llm, aid
    chain.tx(WORKER, "submit_deliverable", aid, "Each requirement is satisfied by src/app.py and src/auth.py.", default_evidence())
    if state == "DELIVERED":
        return chain, llm, aid
    freeze_all(chain, aid)
    if state == "VERIFICATION_PENDING":
        return chain, llm, aid
    if state == "INSUFFICIENT_EVIDENCE":
        set_verdicts(llm, REQ_003="INSUFFICIENT_EVIDENCE")
    elif state != "VERIFIED_PASS" and state != "SETTLED":
        set_verdicts(llm, REQ_002="FAIL")
    verify_all(chain, aid, redteam=(verification == "ADVERSARIAL"))
    if state in ("VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"):
        return chain, llm, aid
    if state == "SETTLED":
        chain.advance(at.CHALLENGE_WINDOW_ADVERSARIAL + 1)
        chain.tx(STRANGER, "settle", aid)
        return chain, llm, aid
    out = chain.tx(WORKER, "open_dispute", aid, "REQ-002", "The verdict on this requirement is wrong.",
                   value=at._bond_for(10 * GEN))
    assert out == "DISPUTED", out
    if state == "DISPUTED":
        return chain, llm, aid
    chain.advance(at.RESPONSE_WINDOW + 1)
    chain.tx(STRANGER, "start_challenge_phase", aid)
    if state == "CHALLENGE":
        return chain, llm, aid
    chain.advance(SEAT_WAIT)
    chain.tx(STRANGER, "seat_jury", aid)
    if state == "FINAL_REVIEW":
        return chain, llm, aid
    vote_all(chain, aid, list(votes))
    chain.tx(STRANGER, "finalize_dispute", aid)
    assert state == "FINALIZED", state
    return chain, llm, aid
