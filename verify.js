/*
 * AgentTrust certificate verifier (protocol version 1.0), JavaScript port of
 * scripts/verification/verify_certificate.py. Runs in Node and in the browser and
 * has no dependencies. It re-derives every hash and derived field of a certificate.
 * A SKIP is never counted as a pass. A VALID result proves self-consistency and
 * grounding in the supplied evidence; anchoring to a deployment needs the on-chain hash.
 *
 *   node frontend/assets/verify.js cert.json [--bundle bundle.json] [--onchain-hash HASH]
 */
(function (root) {
  "use strict";

  var PROTOCOL = "AgentTrust", VERSION = "1.0";
  var STATUSES = ["UNVERIFIED", "PASS", "FAIL", "INSUFFICIENT_EVIDENCE"];
  var FINAL_VERDICTS = ["PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "NOT_VERIFIED"];
  var TERMINALS = ["SETTLED", "FINALIZED", "REFUNDED", "REFUNDED_BEFORE_ACCEPTANCE"];
  var DISPUTE_RESULTS = ["WORKER_PREVAILED", "BUYER_PREVAILED", "DEADLOCK_FALLBACK", "NO_JURY_FALLBACK"];
  var JURY_QUORUM = 2, JURY_SIZE = 3;
  var MIN_AMOUNT = 1000000000000000n, MAX_AMOUNT = 1000000000000000000000000000000n;
  var POLICIES = { evidence: ["STRICT", "PERMISSIVE"], verification: ["STANDARD", "ADVERSARIAL"], dispute: ["JURY", "NONE"] };
  var DISPUTE_BOND_MIN = 100000000000000000n, DISPUTE_BOND_DIVISOR = 20n;
  var RESULT_NOTES = ["", "COMPLETE", "TIMEOUT_FILLED", "EVIDENCE_NOT_FROZEN"];
  var ADDR = /^0x[0-9a-f]{40}$/, REQ_ID = /^REQ-[0-9]{3}$/, HEX64 = /^[0-9a-f]{64}$/;
  var STATEMENT =
    "This certificate establishes that the submitted evidence, frozen at the recorded evidence root, " +
    "satisfied or failed to satisfy the declared requirements under the declared verification protocol, " +
    "as judged by GenLayer validator consensus and, where applicable, a staked jury. " +
    "It is not a guarantee that the deliverable is correct, secure or fit for any purpose beyond those requirements.";
  var REQUIRED = [
    "protocol", "protocol_version", "statement", "agreement_id", "buyer", "worker", "currency", "amount", "deadline",
    "created_at", "accepted_at", "agreement_hash", "frozen_hash", "specification", "specification_hash",
    "requirements_hash", "policies", "policies_hash", "evidence", "requirements", "challenges", "final_verdict",
    "result_note", "terminal_state", "dispute", "settlement", "verification_timestamp", "finalized_at",
    "certificate_hash"
  ];

  function has(list, v) { return list.indexOf(v) !== -1; }
  function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function isInt(v) { return typeof v === "number" && Number.isInteger(v); }

  function cmpCodepoints(a, b) {
    var ia = Array.from(a), ib = Array.from(b), n = Math.min(ia.length, ib.length);
    for (var i = 0; i < n; i++) {
      var x = ia[i].codePointAt(0), y = ib[i].codePointAt(0);
      if (x !== y) return x < y ? -1 : 1;
    }
    return ia.length - ib.length;
  }

  function jsonString(s) {
    var out = '"';
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i), ch = s.charAt(i);
      if (ch === '"') out += '\\"';
      else if (ch === "\\") out += "\\\\";
      else if (c === 10) out += "\\n";
      else if (c === 13) out += "\\r";
      else if (c === 9) out += "\\t";
      else if (c === 8) out += "\\b";
      else if (c === 12) out += "\\f";
      else if (c < 0x20 || c > 0x7e) out += "\\u" + ("0000" + c.toString(16)).slice(-4);
      else out += ch;
    }
    return out + '"';
  }

  // Python json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
  function canon(obj) {
    if (obj === null) return "null";
    if (obj === true) return "true";
    if (obj === false) return "false";
    if (typeof obj === "number") {
      if (!Number.isInteger(obj) || !Number.isSafeInteger(obj)) throw new Error("non-integer or unsafe number in canonical JSON");
      return String(obj);
    }
    if (typeof obj === "bigint") return obj.toString();
    if (typeof obj === "string") return jsonString(obj);
    if (Array.isArray(obj)) return "[" + obj.map(canon).join(",") + "]";
    if (isObj(obj)) {
      return "{" + Object.keys(obj).sort(cmpCodepoints).map(function (k) { return jsonString(k) + ":" + canon(obj[k]); }).join(",") + "}";
    }
    throw new Error("unsupported value in canonical JSON");
  }

  var K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]);

  function utf8(str) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str);
    return Uint8Array.from(Buffer.from(str, "utf8"));
  }

  function sha(text) {
    var bytes = utf8(text), n = bytes.length;
    var total = ((n + 9 + 63) >> 6) << 6, buf = new Uint8Array(total);
    buf.set(bytes); buf[n] = 0x80;
    var view = new DataView(buf.buffer);
    view.setUint32(total - 8, Math.floor(n / 0x20000000), false);
    view.setUint32(total - 4, (n << 3) >>> 0, false);
    var h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    var w = new Uint32Array(64);
    function rotr(x, k) { return (x >>> k) | (x << (32 - k)); }
    for (var off = 0; off < total; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4, false);
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
      }
      var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25), ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22), mj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + mj) >>> 0;
        hh = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0; h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
      h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0; h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
    }
    var out = "";
    for (i = 0; i < 8; i++) out += ("00000000" + h[i].toString(16)).slice(-8);
    return out;
  }

  // Python str.split() whitespace
  var PY_WS = /[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/;
  function normWs(text) {
    return String(text).toLowerCase().split(PY_WS).filter(function (p) { return p.length > 0; }).join(" ");
  }
  function grounded(quote, text) {
    var q = normWs(quote);
    return q.length > 0 && normWs(text).indexOf(q) !== -1;
  }

  function Report() { this.rows = []; }
  Report.prototype.add = function (name, ok, detail) { this.rows.push({ name: name, status: ok ? "PASS" : "FAIL", detail: detail || "" }); };
  Report.prototype.skip = function (name, detail) { this.rows.push({ name: name, status: "SKIP", detail: detail }); };
  Report.prototype.failed = function () { return this.rows.filter(function (r) { return r.status === "FAIL"; }); };
  Report.prototype.valid = function () { return this.failed().length === 0; };
  Report.prototype.counts = function () {
    var c = { PASS: 0, FAIL: 0, SKIP: 0 };
    this.rows.forEach(function (r) { c[r.status]++; });
    return c;
  };
  Report.prototype.text = function () {
    var width = 10;
    this.rows.forEach(function (r) { width = Math.max(width, r.name.length); });
    var lines = this.rows.map(function (r) {
      return (r.status + "    ").slice(0, 4) + "  " + (r.name + new Array(width + 1).join(" ")).slice(0, width) + (r.detail ? "  " + r.detail : "");
    });
    var c = this.counts();
    lines.push("");
    lines.push("CERTIFICATE " + (this.valid() ? "VALID" : "INVALID") + "  (" + c.PASS + " passed, " + c.FAIL + " failed, " + c.SKIP + " skipped)");
    return lines.join("\n");
  };

  function deriveOverall(pairs) {
    var statuses = pairs.map(function (p) { return p[0]; });
    if (statuses.some(function (s) { return s === "FAIL"; })) return "FAIL";
    if (pairs.some(function (p) { return p[1] === "CONFLICTING_EVIDENCE"; })) return "CONFLICTING_EVIDENCE";
    if (statuses.some(function (s) { return s !== "PASS"; })) return "INSUFFICIENT_EVIDENCE";
    return "PASS";
  }

  function deriveRequirement(req, challenges, adversarial, notFrozen) {
    var v = req.verification, status, detail;
    if (notFrozen) return ["INSUFFICIENT_EVIDENCE", "EVIDENCE_NOT_FROZEN"];
    if (v === null || v === undefined) { status = "INSUFFICIENT_EVIDENCE"; detail = "TIMEOUT"; }
    else {
      status = v.verdict; detail = v.detail;
      if (adversarial && status === "PASS") {
        var rt = req.redteam;
        if (rt === null || rt === undefined) { status = "INSUFFICIENT_EVIDENCE"; detail = "RED_TEAM_MISSING"; }
        else if (rt.outcome === "COUNTEREXAMPLE") { status = "INSUFFICIENT_EVIDENCE"; detail = "CONFLICTING_EVIDENCE"; }
      }
    }
    challenges.forEach(function (ch) {
      if (ch.requirement_id === req.requirement_id && ch.status === "UPHELD") { status = ch.resolved_status; detail = "CHALLENGE_UPHELD"; }
    });
    return [status, detail];
  }

  function quotesOf(r) {
    var out = [];
    if (r.verification) out = out.concat(r.verification.quotes || []);
    if (r.redteam && r.redteam.quotes) out = out.concat(r.redteam.quotes);
    return out;
  }

  function big(v) {
    if (typeof v !== "string" || !/^[0-9]+$/.test(v)) throw new Error("expected a decimal digit string");
    return BigInt(v);
  }
  function allOk(list, fn) { for (var i = 0; i < list.length; i++) if (!fn(list[i])) return false; return true; }
  function unique(list) { return new Set(list).size === list.length; }

  function verifyInto(rep, certText, bundle, onchainHash) {
    var cert;
    try { cert = typeof certText === "string" ? JSON.parse(certText) : certText; }
    catch (e) { rep.add("certificate is valid JSON", false, String(e.message || e)); return; }
    if (!isObj(cert)) { rep.add("certificate is a JSON object", false); return; }
    var missing = REQUIRED.filter(function (k) { return !(k in cert); });
    rep.add("required fields present", missing.length === 0, missing.length ? "missing: " + missing.join(", ") : "");
    if (missing.length) return;
    rep.add("protocol and version", cert.protocol === PROTOCOL && cert.protocol_version === VERSION, cert.protocol + " " + cert.protocol_version);
    var body = {};
    Object.keys(cert).forEach(function (k) { if (k !== "certificate_hash") body[k] = cert[k]; });
    rep.add("certificate_hash matches contents", sha(canon(body)) === cert.certificate_hash);

    var spec = cert.specification;
    rep.add("specification_hash", isObj(spec) && sha(canon(spec)) === cert.specification_hash);

    var reqs = cert.requirements;
    var defs = reqs.map(function (r) { return r.definition; });
    var ids = defs.map(function (d) { return d.id; });
    rep.add("requirement ids well formed and unique", allOk(ids, function (i) { return typeof i === "string" && REQ_ID.test(i); }) && unique(ids) && ids.length > 0);
    rep.add("requirements_hash", sha(canon(defs)) === cert.requirements_hash);
    rep.add("each requirement_hash", allOk(reqs, function (r) { return sha(canon(r.definition)) === r.requirement_hash; }));
    rep.add("policies_hash", sha(canon({ evidence: cert.policies.evidence, verification: cert.policies.verification, dispute: cert.policies.dispute })) === cert.policies_hash);
    var agreementHash = sha(canon({
      protocol: cert.protocol, protocol_version: cert.protocol_version, agreement_id: cert.agreement_id,
      buyer: cert.buyer, worker: cert.worker, currency: cert.currency, amount: cert.amount,
      deadline: cert.deadline, spec_hash: cert.specification_hash, requirements_hash: cert.requirements_hash,
      policies_hash: cert.policies_hash, created_at: cert.created_at
    }));
    rep.add("agreement_hash recomputed from its parts", agreementHash === cert.agreement_hash);
    if (cert.accepted_at > 0) {
      rep.add("frozen_hash (agreement frozen at acceptance)", sha(canon({ agreement_hash: cert.agreement_hash, accepted_at: cert.accepted_at, worker: cert.worker })) === cert.frozen_hash);
    } else {
      rep.add("frozen_hash empty when never accepted", cert.frozen_hash === "");
    }

    var amount = big(cert.amount);
    var pol = cert.policies;
    rep.add("currency and amount within protocol limits", cert.currency === "GEN" && amount >= MIN_AMOUNT && amount <= MAX_AMOUNT);
    rep.add("policies are known values", isObj(pol) && Object.keys(pol).sort().join(",") === "dispute,evidence,verification" &&
      Object.keys(POLICIES).every(function (k) { return has(POLICIES[k], pol[k]); }));
    var ev = cert.evidence, items = ev.items;
    var iids = items.map(function (i) { return i.item_id; });
    rep.add("evidence item ids unique and sequential (E1, E2, ...)", allOk(iids.map(function (x, n) { return [x, n]; }), function (p) { return p[0] === "E" + (p[1] + 1); }));
    var ints = [cert.deadline, cert.created_at, cert.accepted_at, cert.verification_timestamp, cert.finalized_at, ev.any_mutable_source];
    items.forEach(function (i) { ints.push(i.mutable, i.length); });
    cert.requirements.forEach(function (r) { ints.push(r.disputed, r.challenge_count); });
    if (cert.dispute !== null) ["votes_worker", "votes_buyer", "revealed", "pool_size", "beacon_round"].forEach(function (k) { ints.push(cert.dispute[k]); });
    rep.add("integer fields are integers (not booleans or strings)", allOk(ints, isInt));
    if (items.length) {
      var rows = items.map(function (i) { return [i.item_id, i.kind, i.source, i.content_hash, i.mutable]; });
      rep.add("evidence root recomputed", sha(canon({ agreement_id: cert.agreement_id, items: rows })) === ev.root);
    } else {
      rep.add("evidence root empty when nothing was frozen", ev.root === "");
    }
    rep.add("any_mutable_source flag", isInt(ev.any_mutable_source) && ev.any_mutable_source === (items.some(function (i) { return i.mutable === 1; }) ? 1 : 0));
    var kindsOk = true;
    items.forEach(function (i) {
      kindsOk = kindsOk && isInt(i.mutable) && i.mutable === (i.kind === "url" ? 1 : 0);
      if (i.kind === "github_file" || i.kind === "github_diff") kindsOk = kindsOk && /@[0-9a-f]{40}(:|#)/.test(i.source);
      if (i.kind === "github_pr") kindsOk = kindsOk && /@[0-9a-f]{40}#pr/.test(i.source);
    });
    rep.add("mutable flags match kinds; github sources pinned to a full commit sha", kindsOk);
    if (cert.policies.evidence === "STRICT") rep.add("STRICT policy: no mutable evidence", !items.some(function (i) { return i.mutable === 1; }));

    var adversarial = cert.policies.verification === "ADVERSARIAL";
    var challenges = cert.challenges;
    var unverifiedOk = cert.final_verdict === "NOT_VERIFIED";
    var notFrozen = cert.result_note === "EVIDENCE_NOT_FROZEN";
    var statusesOk = true, quotesOk = true, derivedPairs = [];
    reqs.forEach(function (r) {
      if (unverifiedOk) {
        statusesOk = statusesOk && r.status === "UNVERIFIED" && r.detail === "" && r.verification === null;
        derivedPairs.push([r.status, r.detail]);
        return;
      }
      if (notFrozen) statusesOk = statusesOk && r.verification === null && r.redteam === null;
      var d = deriveRequirement(r, challenges, adversarial, notFrozen);
      statusesOk = statusesOk && r.status === d[0] && r.detail === d[1] && has(STATUSES, r.status);
      derivedPairs.push(d);
      if (r.verification !== null && r.verification !== undefined) {
        statusesOk = statusesOk && sha(canon(r.verification)) === r.verification_hash;
        if (r.verification.verdict === "PASS") statusesOk = statusesOk && r.verification.quotes.length >= 1 && r.verification.detail === "";
        quotesOk = quotesOk && allOk(quotesOf(r), function (q) { return has(iids, q.evidence_id); });
      } else {
        statusesOk = statusesOk && r.verification_hash === "";
      }
      if (r.redteam !== null && r.redteam !== undefined) statusesOk = statusesOk && sha(canon(r.redteam)) === r.redteam_hash;
    });
    rep.add("requirement statuses re-derived from their verification, red-team and challenge records", statusesOk);
    rep.add("every cited quote names an existing evidence item", quotesOk);
    var structOk = true;
    var disputeIds = cert.dispute !== null ? cert.dispute.requirement_ids.split(",") : [];
    reqs.forEach(function (r) {
      var nCh = challenges.filter(function (ch) { return ch.requirement_id === r.requirement_id; }).length;
      var hasRt = r.redteam !== null && r.redteam !== undefined;
      structOk = structOk && r.requirement_id === r.definition.id && r.challenge_count === nCh;
      structOk = structOk && isInt(r.disputed) && r.disputed === (has(disputeIds, r.requirement_id) ? 1 : 0);
      structOk = structOk && ((r.redteam_hash === "") === !hasRt);
      structOk = structOk && (!hasRt || adversarial);
    });
    rep.add("requirement bookkeeping (ids, challenge counts, disputed flags, red-team fields)", structOk);

    if (unverifiedOk) {
      rep.add("unverified work carries no verification, evidence or challenges",
        items.length === 0 && challenges.length === 0 && cert.result_note === "" && cert.verification_timestamp === 0);
    } else {
      var overall = deriveOverall(derivedPairs);
      rep.add("final_verdict re-derived by the aggregation rule", overall === cert.final_verdict, overall + " vs " + cert.final_verdict);
    }
    rep.add("final_verdict is a known value", has(FINAL_VERDICTS, cert.final_verdict));

    var chOk = true, seen = {};
    challenges.forEach(function (ch) {
      var key = ch.requirement_id + "\u0000" + ch.side;
      chOk = chOk && !(key in seen) && has(ids, ch.requirement_id) && (ch.side === "BUYER" || ch.side === "WORKER");
      seen[key] = true;
      chOk = chOk && (ch.status === "UPHELD" || ch.status === "REJECTED") && HEX64.test(String(ch.challenge_hash));
      if (ch.status === "REJECTED") chOk = chOk && ch.resolved_status === ch.original_status;
      else {
        chOk = chOk && ch.resolved_status !== ch.original_status;
        chOk = chOk && (ch.side === "BUYER" ? (ch.resolved_status === "FAIL" || ch.resolved_status === "INSUFFICIENT_EVIDENCE") : ch.resolved_status === "PASS");
      }
      if (ch.side === "BUYER") chOk = chOk && ch.original_status === "PASS";
      else chOk = chOk && (ch.original_status === "FAIL" || ch.original_status === "INSUFFICIENT_EVIDENCE");
    });
    challenges.forEach(function (ch, n) {
      chOk = chOk && ch.challenge_id === "CH-" + (n + 1);
      chOk = chOk && ch.challenger === (ch.side === "BUYER" ? cert.buyer : cert.worker);
    });
    rep.add("challenges are structurally valid (one per side per requirement, side rules, outcome rules)", chOk);

    var terminal = cert.terminal_state, st = cert.settlement;
    var toWorker = big(st.to_worker), toBuyer = big(st.to_buyer);
    rep.add("settlement adds up to the escrowed amount", toWorker >= 0n && toBuyer >= 0n && toWorker + toBuyer === amount);
    rep.add("terminal_state is known", has(TERMINALS, terminal));
    var d = cert.dispute;
    var pre = true;
    if (terminal === "SETTLED" || terminal === "FINALIZED") pre = pre && cert.accepted_at > 0 && cert.verification_timestamp > 0;
    if (terminal === "REFUNDED_BEFORE_ACCEPTANCE") pre = pre && cert.final_verdict === "NOT_VERIFIED" && cert.verification_timestamp === 0;
    if (d !== null) pre = pre && pol.dispute === "JURY";
    if (challenges.length) pre = pre && cert.verification_timestamp > 0 && items.length > 0;
    if (cert.final_verdict !== "NOT_VERIFIED") pre = pre && cert.accepted_at > 0 && ((items.length === 0) === notFrozen);
    if (terminal === "SETTLED") {
      rep.add("SETTLED: passing verdict, no dispute, all to worker", cert.final_verdict === "PASS" && d === null && toWorker === amount);
    } else if (terminal === "REFUNDED") {
      rep.add("REFUNDED: no dispute, everything back to buyer, never a passing verdict", d === null && toBuyer === amount && cert.final_verdict !== "PASS");
    } else if (terminal === "REFUNDED_BEFORE_ACCEPTANCE") {
      rep.add("REFUNDED_BEFORE_ACCEPTANCE: never accepted, everything back to buyer", d === null && toBuyer === amount && cert.accepted_at === 0);
    }
    rep.add("terminal state preconditions (acceptance, verification, evidence, dispute policy)", pre);
    if (terminal === "FINALIZED") {
      var ok = d !== null && has(DISPUTE_RESULTS, d.result);
      if (ok) {
        var rw = d.votes_worker, rb = d.votes_buyer, n = rw + rb;
        ok = ok && n === d.revealed && n <= d.jurors.length;
        if (d.result === "WORKER_PREVAILED") ok = ok && n >= JURY_QUORUM && rw * 2 > n && toWorker === amount;
        else if (d.result === "BUYER_PREVAILED") ok = ok && n >= JURY_QUORUM && rb * 2 > n && toBuyer === amount;
        else {
          if (d.result === "DEADLOCK_FALLBACK") ok = ok && (n < JURY_QUORUM || rw * 2 === n);
          else ok = ok && d.jurors.length === 0 && n === 0;
          ok = ok && (cert.final_verdict === "PASS" ? toWorker === amount : toBuyer === amount);
        }
      }
      rep.add("FINALIZED: dispute result follows the quorum and majority rule and the settlement follows the result", ok);
      if (d !== null) {
        var dd = d.side === "BUYER" || d.side === "WORKER";
        dd = dd && d.opened_by === (d.side === "BUYER" ? cert.buyer : cert.worker);
        var minBond = amount / DISPUTE_BOND_DIVISOR;
        dd = dd && big(d.bond) === (minBond > DISPUTE_BOND_MIN ? minBond : DISPUTE_BOND_MIN);
        var idsD = d.requirement_ids.split(",");
        var reqIds = reqs.map(function (r) { return r.requirement_id; });
        dd = dd && unique(idsD) && allOk(idsD, function (i) { return has(ids, i); }) && allOk(idsD, function (i) { return has(reqIds, i); });
        dd = dd && d.jurors.length === (d.result === "NO_JURY_FALLBACK" ? 0 : JURY_SIZE);
        dd = dd && unique(d.jurors) && allOk(d.jurors, function (j) { return ADDR.test(j); });
        dd = dd && !has(d.jurors, cert.buyer) && !has(d.jurors, cert.worker);
        dd = dd && HEX64.test(String(d.statement_hash)) && HEX64.test(String(d.response_hash));
        if (d.result === "NO_JURY_FALLBACK") dd = dd && (d.beacon === "" || HEX64.test(String(d.beacon)));
        else dd = dd && HEX64.test(String(d.beacon)) && d.beacon_round > 0 && d.pool_size >= JURY_SIZE;
        rep.add("dispute block is well formed (opener, bond, targets, jurors, beacon)", dd);
      }
    }
    rep.add("dispute block absent unless FINALIZED", (d !== null) === (terminal === "FINALIZED"));

    var orderOk = cert.deadline > cert.created_at && cert.finalized_at >= cert.created_at;
    if (cert.accepted_at > 0) orderOk = orderOk && cert.accepted_at >= cert.created_at;
    if (cert.verification_timestamp > 0) orderOk = orderOk && cert.verification_timestamp <= cert.finalized_at;
    rep.add("timestamps are ordered", orderOk && Number.isInteger(cert.created_at) && cert.created_at > 0 && Number.isInteger(cert.finalized_at) && cert.finalized_at > 0);
    rep.add("scope statement is the protocol's statement", cert.statement === STATEMENT);
    rep.add("result_note is a known value", has(RESULT_NOTES, cert.result_note));
    var aggregated = cert.verification_timestamp > 0;
    rep.add("verification_timestamp is set exactly when verification ran", aggregated === (cert.final_verdict !== "NOT_VERIFIED" || cert.result_note === "EVIDENCE_NOT_FROZEN"));
    rep.add("parties are well-formed distinct addresses", ADDR.test(cert.buyer) && ADDR.test(cert.worker) && cert.buyer !== cert.worker);

    if (bundle === null || bundle === undefined) {
      rep.skip("evidence contents and quotes", "no bundle supplied");
    } else {
      var evidence = Array.isArray(bundle) ? bundle : bundle.evidence;
      var byId = {};
      (evidence || []).forEach(function (e) { byId[e.item_id] = e; });
      var okb = Object.keys(byId).length === iids.length && allOk(iids, function (i) { return i in byId; });
      items.forEach(function (i) {
        var e = byId[i.item_id];
        okb = okb && e !== undefined && sha(e.content) === i.content_hash && i.content_hash === e.content_hash && Array.from(e.content).length === i.length;
        okb = okb && e !== undefined && ["kind", "source", "mutable", "length"].every(function (k) { return e[k] === i[k]; });
      });
      rep.add("evidence bundle matches every frozen content hash and length", okb);
      var gq = true;
      reqs.forEach(function (r) {
        quotesOf(r).forEach(function (q) { gq = gq && (q.evidence_id in byId) && grounded(q.quote, byId[q.evidence_id].content); });
      });
      rep.add("every quoted passage exists in the frozen evidence", gq);
      var chs = Array.isArray(bundle) ? null : bundle.challenges;
      if (chs === null || chs === undefined) rep.skip("challenge hashes and quotes", "bundle has no challenges");
      else {
        var cq = true;
        chs.forEach(function (c) {
          var b = {
            challenge_id: c.challenge_id, requirement_id: c.requirement_id, side: c.side, challenger: c.challenger, claim: c.claim,
            evidence_id: c.evidence_id, quote: c.quote, reasoning: c.reasoning, original_status: c.original_status, status: c.status,
            resolved_status: c.resolved_status, resolution: c.resolution
          };
          cq = cq && sha(canon(b)) === c.challenge_hash && (c.evidence_id in byId) && grounded(c.quote, byId[c.evidence_id].content);
          var res = c.resolution, upheld = c.status === "UPHELD";
          cq = cq && isObj(res) && res.ruling === c.status && res.new_verdict === (upheld ? c.resolved_status : "");
          var rq = isObj(res) && Array.isArray(res.quotes) ? res.quotes : null;
          cq = cq && rq !== null && allOk(rq, function (q) { return isObj(q) && (q.evidence_id in byId) && grounded(q.quote === undefined ? "" : q.quote, byId[q.evidence_id].content); });
          cq = cq && !(upheld && c.side === "WORKER" && !(rq && rq.length));
        });
        var a1 = chs.map(function (c) { return c.challenge_hash; }).sort().join(","), a2 = challenges.map(function (c) { return c.challenge_hash; }).sort().join(",");
        rep.add("challenge hashes recomputed, quotes grounded, auditor rulings consistent", cq && a1 === a2);
      }
    }

    if (onchainHash === null || onchainHash === undefined) rep.skip("on-chain anchor", "no on-chain hash supplied; the certificate is only self-consistent");
    else rep.add("certificate_hash equals the hash recorded by the contract", String(onchainHash).trim().toLowerCase() === cert.certificate_hash);
  }

  function verify(certText, bundle, onchainHash) {
    var rep = new Report();
    try { verifyInto(rep, certText, bundle, onchainHash); }
    catch (e) { rep.add("certificate is structurally well formed", false, (e && e.name || "Error") + ": " + (e && e.message || e)); }
    return rep;
  }

  var api = { verify: verify, canon: canon, sha: sha, normWs: normWs, grounded: grounded, STATEMENT: STATEMENT };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AgentTrustVerify = api;

  if (typeof require !== "undefined" && typeof module !== "undefined" && require.main === module) {
    var fs = require("fs"), argv = process.argv.slice(2);
    if (!argv.length) { console.log("usage: node verify.js cert.json [--bundle bundle.json] [--onchain-hash HASH]"); process.exit(2); }
    var bundle = argv.indexOf("--bundle") !== -1 ? JSON.parse(fs.readFileSync(argv[argv.indexOf("--bundle") + 1], "utf8")) : null;
    var onchain = argv.indexOf("--onchain-hash") !== -1 ? argv[argv.indexOf("--onchain-hash") + 1] : null;
    var rep = verify(fs.readFileSync(argv[0], "utf8"), bundle, onchain);
    console.log(rep.text());
    process.exit(rep.valid() ? 0 : 1);
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);
