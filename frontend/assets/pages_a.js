/* Pages: landing, browse, my agreements, create, public verification. */
(function (AT) {
  "use strict";
  var el = AT.el, ui = AT.ui;
  var P = (AT.pages = AT.pages || {});

  var STATUS_FILTERS = ["ALL", "OPEN", "VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE", "DISPUTED", "SETTLED", "FINALIZED", "REFUNDED"];
  var OPEN_STATES = ["CREATED", "FUNDED", "ACCEPTED", "IN_PROGRESS", "DELIVERED", "VERIFICATION_PENDING", "TIMEOUT"];
  var DISPUTE_STATES = ["DISPUTED", "CHALLENGE", "FINAL_REVIEW"];

  AT.snapshot = async function (aid) {
    var key = AT.state.mode + ":" + AT.state.address + ":" + aid;
    if (AT.cache[key]) return AT.cache[key];
    var s = await AT.source().get(aid);
    AT.cache[key] = s;
    return s;
  };

  /* ------------------------------------------------------------ landing */
  P.home = async function () {
    var demo = AT.state.mode === "demo";
    var protocol = null;
    try { protocol = await AT.source().protocol(); } catch (e) { /* live mode without an address yet */ }
    var steps = [
      ["Agree", "Buyer and worker write down measurable requirements. Terms and policies are hashed."],
      ["Escrow", "The buyer locks the exact amount. Wrong amounts are never lost: they are credited back."],
      ["Freeze terms", "The worker accepts. From that moment the agreement can no longer change."],
      ["Freeze evidence", "The worker submits evidence pinned to a commit. Its bytes are fetched once and hashed."],
      ["Verify per requirement", "Validators judge each requirement and must quote the evidence. The contract checks every quote."],
      ["Challenge", "An adversarial pass and an auditor can overturn weak passes. Each side gets one challenge per requirement."],
      ["Settle or dispute", "A pass settles to the worker. A fail can go to a bonded, staked jury with commit-reveal voting."],
      ["Certificate", "A canonical JSON certificate is sealed. Anyone can re-verify it offline."]
    ];
    var nots = [
      "It does not prove the deliverable is correct, secure or fit for any purpose beyond the written requirements.",
      "It does not stop two colluding parties or a majority of colluding validators or jurors.",
      "It cannot see anything that is not in the frozen evidence, and it cannot read private repositories.",
      "Language models can be wrong. The design makes them quote evidence and gives each verdict a way to be challenged, but does not make them infallible.",
      "The contract has been tested offline against a stub of GenLayer, not audited, and not yet run on a live network by this project."
    ];
    return el("div", { class: "page home" },
      el("section", { class: "hero" },
        el("h1", {}, "Agreements between AI agents that can be checked, not just trusted."),
        el("p", { class: "lead" }, "AgentTrust turns a piece of agent work into a machine-verifiable agreement: measurable requirements, frozen evidence, per-requirement consensus verification, an adversarial challenge, escrow, a dispute jury and a certificate anyone can re-verify."),
        el("div", { class: "row wrap" },
          ui.link("#/browse", demo ? "Explore the recorded demo" : "Browse agreements", "btn primary"),
          ui.link("#/verify", "Verify a certificate", "btn"),
          ui.link("#/new", "Create an agreement", "btn")),
        demo ? ui.notice("info", "You are looking at a recorded, offline simulation: the real contract code run against a stub of GenLayer with scripted model answers. No network, no funds. Switch to Live mode in Settings to use a deployed contract.") : null),
      ui.panel(el("h2", {}, "How one agreement moves"), el("ol", { class: "how" }, steps.map(function (s) { return el("li", {}, el("strong", {}, s[0]), el("span", {}, s[1])); }))),
      ui.panel(el("h2", {}, "Every state, and where you can go from it"), el("p", { class: "muted" }, "Hover or tap a state for its meaning. Colors follow the draft → committed → frozen → verified → dispute → final progression."), ui.stateMachine("VERIFIED_FAIL")),
      ui.panel(el("h2", {}, "What is mutable, committed and frozen"),
        el("div", { class: "cols3" },
          el("div", {}, el("h3", {}, "Draft"), el("p", {}, "Created but unfunded. The terms are already hashed, but nobody is bound. The buyer can cancel.")),
          el("div", {}, el("h3", {}, "Committed"), el("p", {}, "Funded. Escrow is locked; the worker has not agreed yet. The buyer can still cancel for a refund.")),
          el("div", {}, el("h3", {}, "Frozen"), el("p", {}, "Accepted by the worker. Terms, requirements, policies and parties are sealed by frozen_hash.")))),
      ui.panel(el("h2", {}, "Evidence: submitted, frozen, and mutable sources"),
        el("p", {}, "Evidence is only judged after it is frozen: the contract fetches each item once, stores the exact text and its sha256, and computes an evidence root. Items pinned to a commit cannot change. A plain URL is allowed only under the PERMISSIVE policy, and is always flagged as a mutable source: the stored bytes are frozen, but the page itself may change later.")),
      ui.panel(el("h2", {}, "What AgentTrust does not guarantee"), el("ul", {}, nots.map(function (n) { return el("li", {}, n); }))),
      protocol ? ui.panel(el("h2", {}, "Protocol parameters"), ui.kv([
        ["Version", protocol.protocol + " " + protocol.protocol_version], ["Minimum amount", AT.fmtGen(protocol.min_amount)], ["Juror stake", AT.fmtGen(protocol.juror_stake)],
        ["Dispute bond", "max(" + AT.fmtGen(protocol.dispute_bond_min) + ", amount / " + protocol.dispute_bond_divisor + ")"], ["Jury", protocol.jury_size + " jurors, quorum " + protocol.jury_quorum],
        ["Challenge window", AT.fmtDuration(protocol.windows.challenge_standard) + " (adversarial: " + AT.fmtDuration(protocol.windows.challenge_adversarial) + ")"],
        ["Dispute window", AT.fmtDuration(protocol.windows.dispute)], ["Commit / reveal", AT.fmtDuration(protocol.windows.commit) + " / " + AT.fmtDuration(protocol.windows.reveal)]])) : null);
  };

  /* ------------------------------------------------------------ browse */
  function card(snap) {
    var a = snap.agreement, reqs = snap.requirements || [];
    var counts = { PASS: 0, FAIL: 0, INSUFFICIENT_EVIDENCE: 0, UNVERIFIED: 0 };
    reqs.forEach(function (r) { counts[r.verdict] = (counts[r.verdict] || 0) + 1; });
    var phase = AT.PHASES[AT.phaseOf(a.status)];
    return el("a", { class: "card", href: "#/a/" + a.agreement_id },
      el("div", { class: "row wrap" }, el("strong", {}, a.title), ui.statusBadge(a.status)),
      el("div", { class: "muted small" }, a.agreement_id + " · " + AT.fmtGen(a.amount) + " · " + a.verification_policy.toLowerCase() + " verification · " + a.evidence_policy.toLowerCase() + " evidence"),
      el("div", { class: "row wrap small" }, ui.badge(phase.label, phase.css), reqs.length ? [
        ui.badge(counts.PASS + " pass", "ok"), counts.FAIL ? ui.badge(counts.FAIL + " fail", "bad") : null,
        counts.INSUFFICIENT_EVIDENCE ? ui.badge(counts.INSUFFICIENT_EVIDENCE + " insufficient", "warn") : null,
        counts.UNVERIFIED ? ui.badge(counts.UNVERIFIED + " unverified", "muted") : null] : null));
  }
  async function loadCards(ids) {
    var snaps = await Promise.all(ids.map(function (id) { return AT.snapshot(id).catch(function () { return null; }); }));
    return snaps.filter(Boolean);
  }
  P.browse = async function () {
    var ids = await AT.source().list();
    var snaps = await loadCards(ids);
    var filter = "ALL", q = "";
    var listBox = el("div", { class: "cards" });
    function draw() {
      AT.clear(listBox);
      var shown = snaps.filter(function (s) {
        var st = s.agreement.status;
        var okF = filter === "ALL" || (filter === "OPEN" ? OPEN_STATES.indexOf(st) !== -1 : filter === "DISPUTED" ? DISPUTE_STATES.indexOf(st) !== -1 : st === filter);
        var text = (s.agreement.title + " " + s.agreement.agreement_id + " " + s.agreement.buyer + " " + s.agreement.worker).toLowerCase();
        return okF && (!q || text.indexOf(q) !== -1);
      });
      if (!shown.length) listBox.appendChild(el("p", { class: "muted" }, ids.length ? "No agreement matches this filter." : "No agreements yet. Create the first one."));
      shown.forEach(function (s) { listBox.appendChild(card(s)); });
    }
    var chips = el("div", { class: "chips", role: "group", "aria-label": "Filter by status" }, STATUS_FILTERS.map(function (f) {
      return el("button", { class: "chip" + (f === "ALL" ? " on" : ""), type: "button", onclick: function (e) {
        filter = f; Array.prototype.forEach.call(e.currentTarget.parentNode.children, function (c) { c.classList.remove("on"); }); e.currentTarget.classList.add("on"); draw();
      } }, f === "ALL" ? "All" : f.replace(/_/g, " ").toLowerCase());
    }));
    var search = el("input", { type: "search", placeholder: "Search title, id or address", "aria-label": "Search agreements", oninput: function (e) { q = e.target.value.trim().toLowerCase(); draw(); } });
    draw();
    return el("div", { class: "page" }, el("h1", {}, "Agreements"),
      el("p", { class: "muted" }, AT.state.mode === "demo" ? "Recorded offline demo. Every card links to its frozen terms, evidence and certificate." : "Newest first from the deployed contract."),
      search, chips, listBox);
  };

  /* ------------------------------------------------------------ my agreements */
  P.mine = async function () {
    var wrap = el("div", { class: "page" }, el("h1", {}, "My agreements"));
    var data = AT.demoData();
    var demo = AT.state.mode === "demo";
    if (demo && data) {
      var sel = el("select", { "aria-label": "View the demo as", onchange: function (e) { AT.state.account = e.target.value; AT.refreshHeader(); AT.route(); } },
        el("option", { value: "" }, "— choose who you are —"),
        Object.keys(data.actors).map(function (a) { return el("option", { value: a, selected: AT.state.account === a }, data.actors[a] + " (" + AT.short(a) + ")"); }));
      wrap.appendChild(ui.panel(el("p", {}, "In the recorded demo there is no wallet. Choose a role to see the agreements that role would see, and which actions it could take."), ui.field("View the demo as", sel)));
    } else if (!AT.state.account) {
      wrap.appendChild(ui.panel(el("p", {}, "Connect a wallet to list the agreements you are a party to."),
        el("button", { class: "btn primary", type: "button", onclick: async function (e) {
          try { await AT.connectWallet(); AT.refreshHeader(); AT.route(); } catch (err) { e.currentTarget.nextSibling.textContent = err.message || String(err); }
        } }, "Connect wallet"), el("span", { class: "bad small" })));
      return wrap;
    }
    if (!AT.state.account) return wrap;
    var me = AT.state.account, ids;
    if (demo) ids = await AT.source().list();
    else ids = await AT.source().byParty(me);
    var juror = {};
    try { juror = (await AT.source().juror(me)) || {}; } catch (e) { juror = {}; }
    var seats = juror.seats || [];
    if (!demo) ids = ids.concat(seats.filter(function (x) { return ids.indexOf(x) === -1; }));
    var snaps = await loadCards(ids);
    var mine = snaps.filter(function (s) {
      var a = s.agreement, d = s.dispute || {};
      return a.buyer === me || a.worker === me || seats.indexOf(a.agreement_id) !== -1 || (d.jurors || []).some(function (j) { return j.address === me; });
    });
    var bal = "0";
    try { bal = await AT.source().balance(me); } catch (e) { /* ignore */ }
    wrap.appendChild(ui.panel(ui.kv([["Account", el("code", {}, me)], ["Withdrawable balance", AT.fmtGen(bal)],
      ["Juror pool", juror.address ? AT.fmtGen(juror.stake) + " staked · " + (juror.open_seats || 0) + " open seat(s)" + (juror.exit_at ? " · exiting" : "") : el("span", {}, "not registered · ", ui.link("#/jury", "join the pool"))]]),
      bal !== "0" ? ui.txButton("Withdraw balance", function () { return { method: "withdraw", args: [] }; }, function () { AT.route(); }) : null));
    var groups = [["As buyer", function (s) { return s.agreement.buyer === me; }], ["As worker", function (s) { return s.agreement.worker === me; }],
      ["As juror", function (s) { var d = s.dispute || {}; return seats.indexOf(s.agreement.agreement_id) !== -1 || (d.jurors || []).some(function (j) { return j.address === me; }); }]];
    groups.forEach(function (g) {
      var list = mine.filter(g[1]);
      wrap.appendChild(el("h2", {}, g[0] + " (" + list.length + ")"));
      wrap.appendChild(list.length ? el("div", { class: "cards" }, list.map(card)) : el("p", { class: "muted" }, "None."));
    });
    return wrap;
  };

  /* ------------------------------------------------------------ create */
  var EXAMPLE = {
    title: "REST API for the acme user service",
    description: "A REST API with token authentication, user creation and lookup, rate limiting and a documented user schema.",
    specification: "Deliver a Flask service exposing POST /users and GET /users/{id} behind token authentication, with rate limiting and the published user JSON schema.",
    reqs: [["Authentication is required on every endpoint.", "CODE_INSPECTION", "Source showing an authentication check applied to the endpoints."],
      ["POST /users creates a user and returns 201.", "CODE_INSPECTION", "Source of the POST /users handler."],
      ["GET /users/{id} returns the user or 404.", "CODE_INSPECTION", "Source of the GET /users/{id} handler."]]
  };
  function reqRow(values, onRemove) {
    var d = el("textarea", { rows: 2, maxlength: AT.LIMITS.reqText[1], placeholder: "A single, checkable statement (5–400 characters)", "aria-label": "Requirement description" }, values ? values[0] : "");
    var m = el("select", { "aria-label": "Verification method" }, AT.METHODS.map(function (x) { return el("option", { value: x, selected: values && values[1] === x }, x.replace(/_/g, " ").toLowerCase()); }));
    var e = el("textarea", { rows: 2, maxlength: AT.LIMITS.reqEvidence[1], placeholder: "What evidence would show it (5–300 characters)", "aria-label": "Evidence needed" }, values ? values[2] : "");
    var row = el("div", { class: "reqrow" }, el("div", { class: "reqid" }), d, m, e, el("button", { class: "btn tiny", type: "button", onclick: function () { onRemove(row); } }, "Remove"));
    row.get = function () { return { description: d.value.trim(), method: m.value, evidence_requirements: e.value.trim() }; };
    return row;
  }
  P.create = async function () {
    var f = {
      title: el("input", { maxlength: 120, placeholder: "Short title", "aria-required": "true" }),
      description: el("textarea", { rows: 3, maxlength: 2000, placeholder: "What is being delivered" }),
      specification: el("textarea", { rows: 4, maxlength: 4000, placeholder: "The precise specification the requirements are drawn from" }),
      worker: el("input", { placeholder: "0x… worker address", spellcheck: "false", autocomplete: "off" }),
      amount: el("input", { inputmode: "decimal", placeholder: "e.g. 10" }),
      days: el("input", { type: "number", min: 1, max: 364, step: 1, value: 14 }),
      evidence: el("select", {}, el("option", { value: "STRICT" }, "STRICT: only commit-pinned or self-contained evidence"), el("option", { value: "PERMISSIVE" }, "PERMISSIVE: also allow plain URLs (flagged mutable)")),
      verification: el("select", {}, el("option", { value: "STANDARD" }, "STANDARD: verifier consensus"), el("option", { value: "ADVERSARIAL" }, "ADVERSARIAL: also a red-team pass (longer challenge window)")),
      dispute: el("select", {}, el("option", { value: "JURY" }, "JURY: bonded dispute decided by a staked jury"), el("option", { value: "NONE" }, "NONE: the protocol result is final"))
    };
    var rows = el("div", { class: "reqrows" });
    var counter = function () { Array.prototype.forEach.call(rows.children, function (r, i) { r.firstChild.textContent = "REQ-" + String(i + 1).padStart(3, "0"); }); };
    var addRow = function (v) { if (rows.children.length >= AT.LIMITS.requirements) return; rows.appendChild(reqRow(v, function (r) { if (rows.children.length > 1) { rows.removeChild(r); counter(); } })); counter(); };
    EXAMPLE.reqs.forEach(addRow);
    var fill = el("button", { class: "btn", type: "button", onclick: function () {
      f.title.value = EXAMPLE.title; f.description.value = EXAMPLE.description; f.specification.value = EXAMPLE.specification; f.amount.value = "10";
      AT.clear(rows); EXAMPLE.reqs.forEach(addRow);
    } }, "Fill with the demo example");
    function build() {
      var L = AT.LIMITS, title = f.title.value.trim(), description = f.description.value.trim(), spec = f.specification.value.trim(), worker = f.worker.value.trim().toLowerCase();
      if (title.length < L.title[0] || title.length > L.title[1]) throw new Error("Title must be " + L.title[0] + "–" + L.title[1] + " characters.");
      if (description.length < L.description[0]) throw new Error("Description must be at least " + L.description[0] + " characters.");
      if (spec.length < L.specification[0]) throw new Error("Specification must be at least " + L.specification[0] + " characters.");
      if (!/^0x[0-9a-f]{40}$/.test(worker)) throw new Error("Worker must be a 0x-prefixed 20-byte address.");
      if (AT.state.account && worker === AT.state.account) throw new Error("The worker must be a different account from the buyer.");
      var amount = AT.toWei(f.amount.value);
      if (amount < 10n ** 15n) throw new Error("The minimum amount is 0.001 GEN.");
      var days = Number(f.days.value);
      if (!(Number.isInteger(days) && days >= 1 && days <= 364)) throw new Error("Deadline must be a whole number of days between 1 and 364.");
      var reqs = Array.prototype.map.call(rows.children, function (r, i) {
        var v = r.get();
        if (v.description.length < L.reqText[0] || v.evidence_requirements.length < L.reqEvidence[0]) throw new Error("REQ-" + String(i + 1).padStart(3, "0") + ": description and evidence text must be at least 5 characters.");
        return { id: "REQ-" + String(i + 1).padStart(3, "0"), description: v.description, method: v.method, evidence_requirements: v.evidence_requirements };
      });
      var deadline = Math.floor(Date.now() / 1000) + days * 86400;
      return { method: "create_agreement", args: [title, description, spec, worker, "GEN", amount, deadline, JSON.stringify(reqs), f.evidence.value, f.verification.value, f.dispute.value] };
    }
    return el("div", { class: "page" }, el("h1", {}, "Create an agreement"),
      ui.notice("info", "Everything you enter here becomes a permanent part of the agreement. Requirements are hashed now and frozen for good when the worker accepts."),
      ui.panel(el("h2", {}, "Terms"), fill, ui.field("Title", f.title), ui.field("Description", f.description), ui.field("Specification", f.specification), ui.field("Worker", f.worker, "The only account that can accept and deliver."),
        el("div", { class: "grid2" }, ui.field("Amount (GEN)", f.amount, "Escrow must be funded with exactly this amount."), ui.field("Deadline (days from now)", f.days, "Chain time decides; between 1 hour and 1 year."))),
      ui.panel(el("h2", {}, "Requirements"), el("p", { class: "muted" }, "Write each as one statement a reader could check against evidence. Up to 12."), rows,
        el("button", { class: "btn", type: "button", onclick: function () { addRow(); } }, "Add requirement")),
      ui.panel(el("h2", {}, "Policies"), ui.field("Evidence policy", f.evidence), ui.field("Verification policy", f.verification), ui.field("Dispute policy", f.dispute)),
      ui.panel(el("h2", {}, "Create"), el("p", {}, "Creating is free of escrow: nothing is locked until you fund it."),
        ui.txButton("Create agreement", build, function () { setTimeout(function () { location.hash = "#/browse"; }, 800); })));
  };

  /* ------------------------------------------------------------ juror pool */
  P.jury = async function () {
    var me = AT.state.account, info = null, acc = {};
    try { info = await AT.source().protocol(); } catch (e) { info = null; }
    if (me) { try { acc = (await AT.source().juror(me)) || {}; } catch (e) { acc = {}; } }
    var stake = info ? BigInt(info.juror_stake) : 10n ** 17n;
    var refresh = function () { AT.cache = {}; AT.route(); };
    var actions;
    if (!me) actions = el("p", { class: "muted" }, AT.state.mode === "demo" ? "The recorded demo is read-only. In Live mode, connect a wallet here to register." : "Connect a wallet in Settings to register as a juror.");
    else if (!acc.address) actions = ui.txButton("Stake " + AT.fmtGen(stake.toString()) + " and join the pool", function () { return { method: "register_juror", args: [], value: stake }; }, refresh);
    else actions = el("div", {}, ui.kv([["Stake", AT.fmtGen(acc.stake)], ["Registered", AT.fmtTime(acc.registered_at)], ["Open seats", String(acc.open_seats)],
        ["Exit requested", AT.fmtTime(acc.exit_at)], ["Removed for not revealing", AT.fmtTime(acc.removed_at)],
        ["Cases", (acc.seats || []).length ? el("span", {}, (acc.seats || []).map(function (x, i) { return [i ? ", " : "", ui.link("#/a/" + x + "/dispute", x)]; })) : "none"]]),
      !acc.exit_at && !acc.removed_at ? ui.txButton("Leave the pool", function () { return { method: "request_juror_exit", args: [] }; }, refresh, { kind: "" }) : null,
      Number(acc.stake) > 0 && (acc.exit_at || acc.removed_at) ? ui.txButton("Withdraw my stake", function () { return { method: "withdraw_juror_stake", args: [] }; }, refresh, { kind: "" }) : null);
    return el("div", { class: "page" }, el("h1", {}, "Juror pool"),
      el("p", { class: "lead" }, "Disputes are decided by three jurors drawn from a pool of people who staked before the dispute existed. Nobody can join a pool for a case already in progress, and nobody can choose who is drawn."),
      ui.panel(el("h2", {}, "Your membership"), actions),
      ui.panel(el("h2", {}, "How selection works"), el("ol", {}, [
        "Anyone except the two parties of a case can serve. Registering locks a stake of " + AT.fmtGen(stake.toString()) + ".",
        "When a dispute opens, the contract records the pool size. Only jurors registered before that moment, and not leaving or removed by then, can be drawn for it.",
        "When the challenge phase starts, the contract fixes a future drand randomness round (the League of Entropy public beacon). Nobody knows its value in advance and no party can change it.",
        "After the phase, anyone seats the jury: every validator fetches that round and the same three jurors are drawn by hashing it with the case id.",
        "Jurors commit a hashed vote, then reveal it. Majority jurors share the jury fee (half the bond) whichever side wins; a juror who does not reveal loses the stake and is removed from the pool.",
        "Leaving takes " + (info ? AT.fmtDuration(info.windows.juror_exit_delay) : "four days") + ", only 30 days after registering, and only with no open seats."].map(function (t) { return el("li", {}, t); }))),
      info ? ui.panel(el("h2", {}, "Pool"), ui.kv([["Registered jurors", String(info.juror_pool_size)], ["Beacon", el("code", {}, info.beacon ? info.beacon.url : "drand")]])) : null,
      ui.notice("info", "Limits: a party that controls a large share of the pool can still be drawn more often; the stake makes each identity cost something but does not make capture impossible. See docs/DISPUTE_MODEL.md."));
  };

  /* ------------------------------------------------------------ public verification */
  function reportView(rep) {
    var c = rep.counts();
    var banner = el("div", { class: "verdictbanner " + (rep.valid() ? "ok" : "bad"), role: "status" },
      el("strong", {}, rep.valid() ? "CERTIFICATE VALID" : "CERTIFICATE INVALID"), el("span", {}, c.PASS + " passed · " + c.FAIL + " failed · " + c.SKIP + " skipped"));
    var rows = rep.rows.map(function (r) { return el("tr", { class: "r-" + r.status.toLowerCase() }, el("td", {}, ui.badge(r.status, r.status === "PASS" ? "ok" : r.status === "FAIL" ? "bad" : "muted")), el("td", {}, r.name, r.detail ? el("div", { class: "small muted" }, r.detail) : null)); });
    return el("div", {}, banner, el("div", { class: "tablewrap" }, el("table", { class: "report" }, el("tbody", {}, rows))));
  }
  AT.reportView = reportView;
  P.verify = async function (aid) {
    var V = window.AgentTrustVerify;
    var certBox = el("textarea", { rows: 8, class: "mono", placeholder: "Paste the certificate JSON returned by get_certificate", spellcheck: "false", "aria-label": "Certificate JSON" });
    var bundleBox = el("textarea", { rows: 4, class: "mono", placeholder: 'Optional: {"evidence": [...], "challenges": [...]} from get_evidence_bundle and get_challenges', spellcheck: "false", "aria-label": "Evidence bundle JSON" });
    var hashBox = el("input", { class: "mono", placeholder: "Optional: certificate hash from get_certificate_hash", spellcheck: "false", "aria-label": "On-chain certificate hash" });
    var out = el("div", { "aria-live": "polite" });
    function run() {
      AT.clear(out);
      var bundle = null, text = bundleBox.value.trim();
      if (text) { try { bundle = JSON.parse(text); } catch (e) { out.appendChild(ui.notice("bad", "The bundle is not valid JSON: " + e.message)); return; } }
      var rep = V.verify(certBox.value, bundle, hashBox.value.trim() || null);
      out.appendChild(reportView(rep));
      out.appendChild(el("p", { class: "muted small" }, hashBox.value.trim() ? "The on-chain hash check ties this document to what the contract recorded." : "Without the on-chain hash this only proves the document is internally consistent; anyone could have produced a consistent forgery. Fetch the hash from the contract to anchor it."));
    }
    function load(id) {
      return AT.snapshot(id).then(function (s) {
        if (!s.certificate) { AT.clear(out); out.appendChild(ui.notice("warn", id + " has no certificate yet: it is sealed only in a final state.")); return; }
        certBox.value = s.certificate; bundleBox.value = JSON.stringify({ evidence: s.evidence_bundle, challenges: s.challenges }); hashBox.value = s.certificate_hash; run();
      }).catch(function (e) { AT.clear(out); out.appendChild(ui.notice("bad", e.message || String(e))); });
    }
    var demo = AT.state.mode === "demo" && AT.demoData();
    var tamper = el("button", { class: "btn", type: "button", onclick: function () {
      try { var c = JSON.parse(certBox.value); c.settlement.to_worker = String(BigInt(c.settlement.to_worker) + 1n); certBox.value = JSON.stringify(c); run(); }
      catch (e) { AT.clear(out); out.appendChild(ui.notice("warn", "Load a valid certificate first.")); }
    } }, "Tamper with it (change the payout by 1 wei)");
    var examples = demo ? el("div", { class: "row wrap" },
      el("button", { class: "btn", type: "button", onclick: function () { load("AT-1"); } }, "Load example: settled to worker"),
      el("button", { class: "btn", type: "button", onclick: function () { load("AT-2"); } }, "Load example: refunded after jury")) : null;
    var idBox = el("input", { placeholder: "AT-1", "aria-label": "Agreement id", style: "max-width:9rem" });
    if (aid) setTimeout(function () { load(aid); }, 0);
    return el("div", { class: "page" }, el("h1", {}, "Verify a certificate"),
      el("p", { class: "lead" }, "This check runs entirely in your browser. It recomputes every hash, re-derives every verdict from the recorded evidence, and checks that each quoted passage really exists in the frozen evidence. It never trusts the page or the contract to have done so."),
      ui.panel(el("h2", {}, "Certificate"), examples, el("div", { class: "row wrap" }, idBox, el("button", { class: "btn", type: "button", onclick: function () { if (idBox.value.trim()) load(idBox.value.trim()); } }, "Load from the current source")),
        certBox, el("h3", {}, "Evidence bundle (optional)"), bundleBox, el("h3", {}, "On-chain hash (optional)"), hashBox,
        el("div", { class: "row wrap" }, el("button", { class: "btn primary", type: "button", onclick: run }, "Verify"), tamper)),
      out,
      ui.panel(el("h2", {}, "What VALID means"), el("ul", {}, [
        "Every hash in the certificate matches its contents, and every derived field follows from the recorded records by the published rules.",
        "With the bundle: every stored evidence text matches its recorded sha256, and every quoted passage is found in it.",
        "With the on-chain hash: this exact document is the one the contract sealed.",
        "It does not mean the work is good. It means the protocol was followed and the record is intact."].map(function (t) { return el("li", {}, t); }))));
  };
})(window.AT);
