/* AgentTrust frontend core: helpers, protocol tables, data sources. No framework, no build step. */
(function (AT) {
  "use strict";

  var CFG = window.AGENTTRUST_CONFIG || {};
  AT.CFG = CFG;

  /* ---------------------------------------------------------------- DOM helpers (data is only ever set as text) */
  AT.el = function (tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") n.className = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (k === "value") n.value = v;
      else if (k === "checked" || k === "disabled" || k === "selected" || k === "open") n[k] = !!v;
      else n.setAttribute(k, v === true ? "" : String(v));
    });
    for (var i = 2; i < arguments.length; i++) AT.append(n, arguments[i]);
    return n;
  };
  AT.append = function (n, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { AT.append(n, x); }); return; }
    n.appendChild(c && c.nodeType ? c : document.createTextNode(String(c)));
  };
  AT.clear = function (n) { while (n.firstChild) n.removeChild(n.firstChild); return n; };
  var el = AT.el;

  /* ---------------------------------------------------------------- formatting */
  AT.short = function (a) { a = String(a || ""); return a.length > 14 ? a.slice(0, 8) + "…" + a.slice(-4) : a; };
  AT.fmtGen = function (wei) {
    try {
      var v = BigInt(String(wei)), base = 10n ** 18n, whole = v / base, frac = (v % base).toString().padStart(18, "0").replace(/0+$/, "");
      return whole.toString() + (frac ? "." + frac.slice(0, 6) : "") + " GEN";
    } catch (e) { return String(wei) + " wei"; }
  };
  AT.toWei = function (text) {
    var t = String(text).trim();
    if (!/^[0-9]+(\.[0-9]{1,18})?$/.test(t)) throw new Error("amount must be a positive decimal number of GEN");
    var parts = t.split("."), frac = (parts[1] || "").padEnd(18, "0");
    var v = BigInt(parts[0]) * 10n ** 18n + BigInt(frac || "0");
    if (v <= 0n) throw new Error("amount must be greater than zero");
    return v;
  };
  AT.fmtTime = function (ts) {
    ts = Number(ts);
    if (!ts) return "—";
    return new Date(ts * 1000).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
  };
  AT.fmtDuration = function (s) {
    s = Number(s);
    if (s % 86400 === 0) return (s / 86400) + " d";
    if (s % 3600 === 0) return (s / 3600) + " h";
    return s + " s";
  };
  AT.pretty = function (x) { return typeof x === "string" ? x : JSON.stringify(x, null, 2); };
  AT.toPlain = function (x) {
    if (x instanceof Map) { var o = {}; x.forEach(function (v, k) { o[k] = AT.toPlain(v); }); return o; }
    if (Array.isArray(x)) return x.map(AT.toPlain);
    if (typeof x === "bigint") return x <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(x) : x.toString();
    if (x && typeof x === "object") { var r = {}; Object.keys(x).forEach(function (k) { r[k] = AT.toPlain(x[k]); }); return r; }
    return x;
  };

  /* ---------------------------------------------------------------- protocol tables (mirror contracts/agenttrust.py) */
  AT.EDGES = {
    CREATED: ["FUNDED", "CANCELLED"], FUNDED: ["ACCEPTED", "REFUNDED", "TIMEOUT"], ACCEPTED: ["IN_PROGRESS", "TIMEOUT"],
    IN_PROGRESS: ["DELIVERED", "TIMEOUT"], DELIVERED: ["VERIFICATION_PENDING", "INSUFFICIENT_EVIDENCE"],
    VERIFICATION_PENDING: ["VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"],
    VERIFIED_PASS: ["SETTLED", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE", "DISPUTED"],
    VERIFIED_FAIL: ["DISPUTED", "REFUNDED"], INSUFFICIENT_EVIDENCE: ["DISPUTED", "REFUNDED"], DISPUTED: ["CHALLENGE"],
    CHALLENGE: ["FINAL_REVIEW", "FINALIZED"], FINAL_REVIEW: ["FINALIZED"], TIMEOUT: ["REFUNDED"],
    SETTLED: [], FINALIZED: [], REFUNDED: [], CANCELLED: []
  };
  AT.TERMINAL = ["SETTLED", "FINALIZED", "REFUNDED", "CANCELLED"];
  AT.PHASES = {
    draft: { label: "Draft", css: "draft", text: "Not funded. Only the buyer has committed to anything, and only by writing the terms; they can still cancel." },
    committed: { label: "Committed", css: "committed", text: "The buyer's escrow is locked and the terms are fixed by hash. The worker has not accepted yet." },
    frozen: { label: "Frozen", css: "frozen", text: "The worker accepted. Terms, requirements and policies are bound by frozen_hash and can never change." },
    evidence: { label: "Evidence", css: "frozen", text: "Deliverable evidence is submitted, then frozen: its bytes are fetched once and hashed." },
    verify: { label: "Verification", css: "verify", text: "Validators judge each requirement against the frozen evidence; the contract checks every quote." },
    dispute: { label: "Dispute", css: "dispute", text: "A bonded dispute is decided by a staked jury (commit, then reveal)." },
    terminal: { label: "Final", css: "terminal", text: "Money has moved exactly once and a canonical certificate exists." }
  };
  AT.STATE_INFO = {
    CREATED: { phase: "draft", who: "Buyer", text: "Waiting for the buyer to fund the escrow." },
    FUNDED: { phase: "committed", who: "Worker", text: "Escrow locked. Waiting for the worker to accept the frozen terms." },
    ACCEPTED: { phase: "frozen", who: "Worker", text: "Terms are frozen. The worker must start work." },
    IN_PROGRESS: { phase: "frozen", who: "Worker", text: "Work in progress. The worker submits evidence before the deadline." },
    DELIVERED: { phase: "evidence", who: "Buyer or worker", text: "Evidence submitted but not frozen yet. Either party can freeze it." },
    VERIFICATION_PENDING: { phase: "verify", who: "Anyone", text: "Evidence is frozen. Anyone can trigger verification of each requirement." },
    VERIFIED_PASS: { phase: "verify", who: "Anyone / buyer", text: "Every requirement passed. The buyer can challenge or dispute during the window; afterwards anyone can settle." },
    VERIFIED_FAIL: { phase: "verify", who: "Worker / buyer", text: "At least one requirement failed. The worker can dispute; otherwise the buyer is refunded after the window." },
    INSUFFICIENT_EVIDENCE: { phase: "verify", who: "Worker / buyer", text: "Evidence was not enough to decide. The worker can dispute; otherwise the buyer is refunded after the window." },
    DISPUTED: { phase: "dispute", who: "Jurors / other party", text: "A bonded dispute is open. The other side can respond; jurors will be drawn from the pool registered before the dispute." },
    CHALLENGE: { phase: "dispute", who: "Parties / anyone", text: "Challenge phase: parties may challenge requirements; then the jury is seated." },
    FINAL_REVIEW: { phase: "dispute", who: "Jurors", text: "Seated jurors commit hashed votes, then reveal them." },
    FINALIZED: { phase: "terminal", who: "—", text: "Finalized by jury decision. Funds are withdrawable; the certificate is sealed." },
    SETTLED: { phase: "terminal", who: "—", text: "Settled to the worker. The certificate is sealed." },
    REFUNDED: { phase: "terminal", who: "—", text: "Refunded to the buyer. The certificate is sealed." },
    TIMEOUT: { phase: "committed", who: "Buyer", text: "A deadline passed. The buyer can claim the refund." },
    CANCELLED: { phase: "terminal", who: "—", text: "Cancelled before funding. Nothing was ever locked." }
  };
  AT.LAYOUT = {
    CREATED: [0, 0], FUNDED: [1, 0], ACCEPTED: [2, 0], IN_PROGRESS: [3, 0], DELIVERED: [4, 0], VERIFICATION_PENDING: [5, 0], VERIFIED_PASS: [6, 0], SETTLED: [7, 0],
    CANCELLED: [0, 1], TIMEOUT: [1, 1], VERIFIED_FAIL: [5, 1], INSUFFICIENT_EVIDENCE: [6, 1], DISPUTED: [7, 1],
    REFUNDED: [3, 2], FINALIZED: [5, 2], FINAL_REVIEW: [6, 2], CHALLENGE: [7, 2]
  };
  AT.METHODS = ["CODE_INSPECTION", "DOCUMENT_INSPECTION", "SCHEMA_CHECK", "EXISTENCE_CHECK"];
  AT.LIMITS = { title: [3, 120], description: [10, 2000], specification: [10, 4000], reqText: [5, 400], reqEvidence: [5, 300], requirements: 12, evidenceItems: 10,
    claim: [20, 600], reasoning: [40, 1000], quote: [6, 400], statement: [10, 2000] };

  /* ---------------------------------------------------------------- persisted settings (never required to work) */
  var mem = {};
  AT.store = {
    get: function (k, d) { try { var v = window.localStorage.getItem("agenttrust." + k); return v === null ? (k in mem ? mem[k] : d) : v; } catch (e) { return k in mem ? mem[k] : d; } },
    set: function (k, v) { mem[k] = v; try { window.localStorage.setItem("agenttrust." + k, v); } catch (e) { /* storage unavailable */ } }
  };
  AT.state = {
    mode: AT.store.get("mode", CFG.defaultMode || "demo"),
    address: AT.store.get("address", CFG.contractAddress || ""),
    account: "", busy: false
  };
  if (AT.state.mode !== "demo" && AT.state.mode !== "live") AT.state.mode = "demo";
  AT.setMode = function (m) { AT.state.mode = m; AT.store.set("mode", m); AT.state.account = ""; live.write = null; AT.cache = {}; };
  AT.setAddress = function (a) { AT.state.address = String(a || "").trim(); AT.store.set("address", AT.state.address); AT.cache = {}; };
  AT.cache = {};

  /* ---------------------------------------------------------------- data sources */
  AT.demoData = function () { return window.AGENTTRUST_DEMO || null; };
  var live = { client: null, write: null, mod: null, chains: null, listening: false };
  var demoSource = {
    id: "demo", canWrite: false,
    protocol: async function () { return AT.demoData().protocol; },
    list: async function () { return AT.demoData().order.slice().reverse(); },
    get: async function (aid) {
      var s = AT.demoData().agreements[aid];
      if (!s) throw new Error("unknown agreement " + aid + " in the recorded demo");
      var copy = JSON.parse(JSON.stringify(s));
      if (copy.dispute && !Object.keys(copy.dispute).length) copy.dispute = null;
      return copy;
    },
    balance: async function (addr) { return "0"; },
    accounting: async function () { return AT.demoData().accounting; },
    juror: async function (addr) { return (AT.demoData().jurors || {})[String(addr).toLowerCase()] || {}; }
  };
  async function liveModules() {
    if (live.mod) return live;
    live.mod = await import(CFG.genlayerJs);
    live.chains = await import(CFG.genlayerJsChains);
    return live;
  }
  async function liveClient() {
    if (live.client) return live.client;
    await liveModules();
    live.client = live.mod.createClient({ chain: live.chains[CFG.chain || "studionet"] });
    return live.client;
  }
  var readQueue = { active: 0, waiting: [] };
  function acquireRead() {
    if (readQueue.active < 2) { readQueue.active++; return Promise.resolve(); }
    return new Promise(function (resolve) { readQueue.waiting.push(resolve); });
  }
  function releaseRead() {
    var next = readQueue.waiting.shift();
    if (next) next(); else readQueue.active--;
  }
  async function read(method, args) {
    if (!/^0x[0-9a-fA-F]{40}$/.test(AT.state.address)) throw new Error("Set the deployed AgentTrust contract address in Settings first.");
    var c = await liveClient(), lastError;
    await acquireRead();
    try {
      for (var attempt = 0; attempt < 5; attempt++) {
        try {
          return AT.toPlain(await c.readContract({ address: AT.state.address, functionName: method, args: args || [] }));
        } catch (e) {
          lastError = e;
          await new Promise(function (r) { setTimeout(r, 500 * (attempt + 1)); });
        }
      }
      throw lastError;
    } finally { releaseRead(); }
  }
  var liveSource = {
    id: "live", canWrite: true,
    protocol: function () { return read("get_protocol_info"); },
    list: async function () {
      var n = Number(await read("agreement_count"));
      return n === 0 ? [] : read("list_agreements", [0, Math.min(CFG.listPageSize || 30, 100)]);
    },
    get: async function (aid) {
      var r = await Promise.all([read("get_agreement", [aid]), read("get_requirements", [aid]), read("get_evidence_bundle", [aid]),
        read("get_challenges", [aid]), read("get_dispute", [aid]), read("get_certificate", [aid]), read("get_certificate_hash", [aid])]);
      var d = r[4];
      return { agreement: r[0], requirements: r[1], evidence_bundle: r[2], challenges: r[3], dispute: d && Object.keys(d).length ? d : null, certificate: r[5], certificate_hash: r[6] };
    },
    balance: function (addr) { return read("get_balance", [String(addr).toLowerCase()]); },
    accounting: function () { return read("get_accounting"); },
    byParty: function (addr) { return read("list_by_party", [String(addr).toLowerCase(), 0, 100]); },
    juror: function (addr) { return read("get_juror", [String(addr).toLowerCase()]); }
  };
  AT.source = function () { return AT.state.mode === "live" ? liveSource : demoSource; };
  AT.readRaw = read;

  async function ensureNetwork(chain) {
    if (!chain || !chain.id) return;
    var hex = "0x" + Number(chain.id).toString(16);
    try {
      var current = await window.ethereum.request({ method: "eth_chainId" });
      if (String(current).toLowerCase() === hex) return;
      await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hex }] });
    } catch (e) {
      if (e && e.code === 4001) throw new Error("The wallet refused to switch to " + (chain.name || "the GenLayer network") + ".");
      var rpc = chain.rpcUrls && chain.rpcUrls.default && chain.rpcUrls.default.http;
      if (!rpc || !rpc.length) throw new Error("Switch your wallet to " + (chain.name || "the GenLayer network") + " and try again.");
      await window.ethereum.request({ method: "wallet_addEthereumChain", params: [{ chainId: hex, chainName: chain.name || "GenLayer",
        nativeCurrency: chain.nativeCurrency || { name: "GEN", symbol: "GEN", decimals: 18 }, rpcUrls: rpc }] });
    }
  }
  function bindAccount(addr) {
    AT.state.account = String(addr || "").toLowerCase();
    live.write = AT.state.account ? live.mod.createClient({ chain: live.chains[CFG.chain || "studionet"], account: addr }) : null;
  }
  AT.connectWallet = async function () {
    if (!window.ethereum) throw new Error("No injected wallet was found in this browser.");
    if (AT.state.mode !== "live") throw new Error("Switch to Live mode in Settings before connecting a wallet.");
    var accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    await liveModules();
    await ensureNetwork(live.chains[CFG.chain || "studionet"]);
    bindAccount(accounts[0]);
    if (!live.listening && window.ethereum.on) {
      live.listening = true;
      window.ethereum.on("accountsChanged", function (list) {
        if (AT.state.mode !== "live") return;
        bindAccount((list || [])[0]);
        AT.cache = {};
        if (AT.refreshHeader) AT.refreshHeader();
        AT.route();
      });
    }
    return AT.state.account;
  };

  function findRejection(x, depth) {
    if (depth > 6 || x === null || x === undefined) return null;
    if (typeof x === "string") { var m = /REJECTED: [^"\\]*/.exec(x); return m ? m[0] : null; }
    if (typeof x === "object") {
      var keys = Object.keys(x);
      for (var i = 0; i < keys.length; i++) { var r = findRejection(x[keys[i]], depth + 1); if (r) return r; }
    }
    return null;
  }
  AT.findRejection = function (x) { return findRejection(x, 0); };

  /* Sends a transaction through the connected wallet and waits for consensus. Returns the plain receipt. */
  AT.tx = async function (method, args, opts, log) {
    opts = opts || {};
    log = log || function () {};
    if (AT.state.mode !== "live") throw new Error("The recorded demo is read-only. Switch to Live mode in Settings to send transactions.");
    if (!live.write) throw new Error("Connect a wallet first.");
    if (!/^0x[0-9a-fA-F]{40}$/.test(AT.state.address)) throw new Error("Set the contract address in Settings first.");
    if (AT.state.busy) throw new Error("Another transaction is still in progress.");
    AT.state.busy = true;
    try {
      log("→ " + method + "(" + JSON.stringify(args, function (k, v) { return typeof v === "bigint" ? v.toString() : v; }) + ")" + (opts.value ? " value " + AT.fmtGen(opts.value) : ""));
      var req = { address: AT.state.address, functionName: method, args: args };
      if (opts.value) req.value = BigInt(opts.value);
      var hash = await live.write.writeContract(req);
      log("  transaction " + hash + " sent; waiting for validator consensus (model steps can take minutes)…");
      var receipt = AT.toPlain(await live.write.waitForTransactionReceipt({ hash: hash, status: "ACCEPTED", interval: 5000, retries: 120 }));
      var st = String((receipt && (receipt.status_name || receipt.statusName || receipt.status)) || "");
      if (st && !/ACCEPTED|FINALIZED/i.test(st)) throw new Error(method + " did not reach consensus (status " + st + "). Nothing changed; you can retry.");
      var leader = receipt && receipt.consensus_data && receipt.consensus_data.leader_receipt && receipt.consensus_data.leader_receipt[0];
      var res = leader && leader.execution_result;
      if (typeof res === "string" && /error|revert|rollback/i.test(res)) throw new Error("The contract rejected " + method + " (" + res + ")");
      var rejected = leader ? findRejection(leader.result !== undefined ? leader.result : leader, 0) : null;
      if (rejected) {
        AT.cache = {};
        throw new Error(rejected + ". Any value you attached was credited to your withdrawable balance (Mine → Withdraw).");
      }
      log("  accepted. " + (CFG.explorerUrl ? CFG.explorerUrl + "/tx/" + hash : ""));
      AT.cache = {};
      return receipt;
    } finally { AT.state.busy = false; }
  };

  /* ---------------------------------------------------------------- derived helpers */
  AT.role = function (agreement) {
    var me = AT.state.account;
    if (!me) return "visitor";
    if (me === agreement.buyer) return "buyer";
    if (me === agreement.worker) return "worker";
    return "other";
  };
  AT.phaseOf = function (status) { return (AT.STATE_INFO[status] || { phase: "draft" }).phase; };
  AT.commitmentLevel = function (a) {
    if (a.status === "CANCELLED") return { key: "draft", label: "Cancelled draft", text: "The draft was cancelled before any funds were locked." };
    if (a.accepted_at > 0) return { key: "frozen", label: "Frozen", text: "Bound by frozen_hash " + AT.short(a.frozen_hash) + ". Nothing in the agreement can change." };
    if (a.funded) return { key: "committed", label: "Committed", text: "Escrow locked and terms fixed by agreement_hash " + AT.short(a.agreement_hash) + ". The worker has not accepted yet." };
    return { key: "draft", label: "Draft", text: "Unfunded. Terms are already fixed by agreement_hash " + AT.short(a.agreement_hash) + ", but nobody is bound to them yet." };
  };
  AT.grounded = function (quote, content) { return window.AgentTrustVerify ? window.AgentTrustVerify.grounded(quote, content) : false; };
  AT.pyWsNorm = function (t) { return window.AgentTrustVerify.normWs(t); };
})(window.AT = window.AT || {});
