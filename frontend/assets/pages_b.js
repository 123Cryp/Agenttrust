/* Pages: one agreement (overview, fund, accept, submit, verification, requirement, dispute, certificate). */
(function (AT) {
  "use strict";
  var el = AT.el, ui = AT.ui;
  var P = (AT.pages = AT.pages || {});
  var reload = function () { AT.cache = {}; AT.route(); };

  async function shell(aid, page, build) {
    var snap = await AT.snapshot(aid);
    var body = await build(snap, snap.agreement);
    return el("div", { class: "page" }, ui.agreementHeader(snap, page), body);
  }
  function requirementList(reqs, aid, withStatus) {
    return el("ul", { class: "reqlist" }, reqs.map(function (r) {
      return el("li", {}, el("div", { class: "row wrap" }, el("strong", {}, r.requirement_id), ui.badge(r.method.replace(/_/g, " ").toLowerCase(), "muted"),
        withStatus ? ui.statusBadge(r.verdict) : null, withStatus && r.detail ? ui.badge(r.detail.replace(/_/g, " ").toLowerCase(), "warn") : null),
        el("p", {}, r.description), el("p", { class: "muted small" }, "Evidence needed: " + r.evidence_requirements),
        aid && withStatus ? ui.link("#/a/" + aid + "/requirement/" + r.requirement_id, "Open requirement result") : null);
    }));
  }
  function deadlineNote(a) {
    if (!a.stage_deadline) return null;
    return ["Current stage deadline", AT.fmtTime(a.stage_deadline)];
  }
  function hashes(a) {
    return el("div", {}, ui.hash("agreement_hash", a.agreement_hash), ui.hash("frozen_hash", a.frozen_hash), ui.hash("spec_hash", a.spec_hash),
      ui.hash("requirements_hash", a.requirements_hash), ui.hash("policies_hash", a.policies_hash), ui.hash("evidence_root", a.evidence_root), ui.hash("certificate_hash", a.certificate_hash));
  }

  /* ------------------------------------------------------------ overview */
  function evidencePanel(snap) {
    var a = snap.agreement, items = snap.evidence_bundle || [];
    if (items.length && a.status === "DELIVERED") {
      var total = 0;
      try { total = JSON.parse(a.pending_evidence).length; } catch (e) { total = items.length; }
      return ui.panel(el("h2", {}, "Freezing evidence"), ui.badge(items.length + " of " + total + " items frozen", "warn"),
        el("p", { class: "muted" }, "Items are frozen one per transaction, so a source that cannot be fetched only blocks itself. The evidence root is sealed when the last item is frozen."),
        items.map(function (it) { return el("div", {}, el("strong", {}, it.item_id), " ", el("code", {}, it.source), " ", ui.evidenceFlag(it)); }));
    }
    if (items.length) {
      return ui.panel(el("h2", {}, "Frozen evidence"), ui.badge("immutable", "ok"),
        el("p", { class: "muted" }, "These exact bytes were fetched once by validators and hashed. Nothing that changes at the source afterwards can affect the verdict."),
        items.map(function (it) {
          return el("details", { class: "evitem" }, el("summary", {}, el("strong", {}, it.item_id), " ", el("code", {}, it.source), " ", ui.evidenceFlag(it)),
            ui.kv([["kind", it.kind], ["length", it.length + " characters"], ["sha256", el("code", { class: "hash" }, it.content_hash)]]), el("pre", { class: "code" }, it.content));
        }), ui.hash("evidence_root", a.evidence_root), el("p", { class: "small muted" }, "Frozen at " + AT.fmtTime(a.frozen_at)));
    }
    var pending = null;
    try { pending = a.pending_evidence ? JSON.parse(a.pending_evidence) : null; } catch (e) { pending = null; }
    if (pending) {
      return ui.panel(el("h2", {}, "Submitted evidence"), ui.badge("submitted, not frozen yet", "warn"),
        el("p", { class: "muted" }, "These are only references so far. Until freeze_evidence runs, nothing has been fetched or hashed, so nothing here is final."),
        el("pre", { class: "code" }, JSON.stringify(pending, null, 2)));
    }
    return ui.panel(el("h2", {}, "Evidence"), el("p", { class: "muted" }, "No evidence has been submitted yet."));
  }
  function escrowPanel(a) {
    var st = a.escrow_paid ? "Paid out exactly once" : a.funded ? "Locked in the contract" : "Not funded";
    return ui.panel(el("h2", {}, "Escrow"), ui.kv([["Amount", AT.fmtGen(a.amount)], ["State", st], a.escrow_paid ? ["To worker", AT.fmtGen(a.settle_worker)] : null, a.escrow_paid ? ["To buyer", AT.fmtGen(a.settle_buyer)] : null]),
      el("p", { class: "small muted" }, "Payouts are credited to a withdrawable balance (pull payments), so a failed transfer can never trap funds."));
  }
  function quickActions(a) {
    var s = a.status, out = [];
    var add = function (label, method, note) { out.push(el("div", { class: "qa" }, el("p", { class: "small muted" }, note), ui.txButton(label, function () { return { method: method, args: [a.agreement_id] }; }, reload, { kind: "" }))); };
    if (s === "CREATED" || s === "FUNDED") add("Cancel agreement", "cancel", "Buyer only. Cancels the draft or refunds a funded agreement the worker has not accepted.");
    if (s === "ACCEPTED") add("Start work", "start_work", "Worker only.");
    var now = Date.now() / 1000, late = a.stage_deadline && now > a.stage_deadline;
    if (s === "DELIVERED" && !late) add("Freeze next evidence item", "freeze_evidence", "Buyer or worker. Fetches the next evidence item once and stores its exact bytes; the last one seals the evidence root.");
    if (s === "DELIVERED" && late) add("Close the freeze window", "expire_if_timed_out", "Anyone. The freeze window has passed: the agreement becomes INSUFFICIENT EVIDENCE and the worker may still dispute.");
    if (s === "VERIFICATION_PENDING" && late) add("Close verification", "aggregate", "Anyone. The verify window has passed: unjudged requirements count as insufficient evidence.");
    if (s === "VERIFIED_PASS") add("Settle to worker", "settle", "Anyone, once the challenge window has closed with no dispute.");
    if (s === "VERIFIED_FAIL" || s === "INSUFFICIENT_EVIDENCE" || s === "TIMEOUT") add("Claim refund", "claim_refund", "Buyer only, once any dispute window has closed.");
    if (["FUNDED", "ACCEPTED", "IN_PROGRESS"].indexOf(s) !== -1) add("Check timeout", "expire_if_timed_out", "Anyone. Moves the agreement to TIMEOUT if its deadline has passed.");
    return out;
  }
  function nextSteps(a) {
    var s = a.status, role = AT.role(a), aid = a.agreement_id, L = function (h, t) { return el("li", {}, ui.link("#/a/" + aid + "/" + h, t)); };
    var items = [];
    if (s === "CREATED") items.push(L("fund", "Fund the escrow (buyer)"));
    if (s === "FUNDED") items.push(L("accept", "Review and accept the terms (worker)"));
    if (s === "ACCEPTED" || s === "IN_PROGRESS") items.push(L("submit", "Submit the deliverable evidence (worker)"));
    if (s === "VERIFICATION_PENDING") items.push(L("verification", "Run verification for each requirement (anyone)"));
    if (["VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"].indexOf(s) !== -1) { items.push(L("verification", "Inspect the requirement results")); items.push(L("dispute", "Challenge a requirement or open a dispute")); }
    if (["DISPUTED", "CHALLENGE", "FINAL_REVIEW"].indexOf(s) !== -1) items.push(L("dispute", "Follow or take part in the dispute"));
    if (AT.TERMINAL.indexOf(s) !== -1 && s !== "CANCELLED") items.push(L("certificate", "Read and verify the certificate"));
    return el("div", {}, el("p", { class: "small muted" }, role === "visitor" ? "Connect a wallet to see which of these are yours." : "You are viewing as the " + role + "."), el("ul", { class: "next" }, items));
  }
  P.details = function (aid) {
    return shell(aid, "", function (snap, a) {
      var info = AT.STATE_INFO[a.status], reqs = snap.requirements;
      return el("div", {},
        ui.panel(el("h2", {}, "Where this stands"), el("p", {}, info.who === "—" ? null : el("strong", {}, info.who + ": "), info.text), ui.commitStrip(a), nextSteps(a), quickActions(a)),
        ui.panel(el("h2", {}, "State machine"), ui.stateMachine(a.status)),
        el("div", { class: "grid2" }, escrowPanel(a),
          ui.panel(el("h2", {}, "Timing"), ui.kv([["Created", AT.fmtTime(a.created_at)], ["Deadline", AT.fmtTime(a.deadline)], ["Accepted", AT.fmtTime(a.accepted_at)],
            ["Delivered", AT.fmtTime(a.delivered_at)], ["Evidence frozen", AT.fmtTime(a.frozen_at)], ["Verified", AT.fmtTime(a.aggregated_at)], ["Finalized", AT.fmtTime(a.finalized_at)], deadlineNote(a)]))),
        ui.panel(el("h2", {}, "Terms"), a.accepted_at > 0 ? ui.badge("frozen", "frozen") : a.funded ? ui.badge("committed", "committed") : ui.badge("draft", "draft"),
          el("p", {}, a.description), el("h3", {}, "Specification"), el("p", { class: "pre" }, a.specification), el("h3", {}, "Requirements"), requirementList(reqs, aid, a.aggregated_at > 0 || reqs.some(function (r) { return r.verdict !== "UNVERIFIED"; })),
          ui.kv([["Evidence policy", a.evidence_policy + (a.evidence_policy === "STRICT" ? ": no mutable sources" : ": plain URLs allowed and flagged")],
            ["Verification policy", a.verification_policy + (a.verification_policy === "ADVERSARIAL" ? ": red-team pass and a longer challenge window" : "")],
            ["Dispute policy", a.dispute_policy + (a.dispute_policy === "JURY" ? ": bonded dispute, staked jury" : ": result is final")]])),
        evidencePanel(snap),
        ui.panel(el("h2", {}, "Hashes"), el("p", { class: "muted small" }, "These bind the agreement. agreement_hash covers the terms; frozen_hash additionally covers the worker and acceptance time."), hashes(a)));
    });
  };

  /* ------------------------------------------------------------ fund */
  P.fund = function (aid) {
    return shell(aid, "fund", function (snap, a) {
      var role = AT.role(a), can = a.status === "CREATED" && (role === "buyer" || role === "visitor");
      return el("div", {}, ui.panel(el("h2", {}, "Fund the escrow"),
        ui.kv([["Amount to send", el("strong", {}, AT.fmtGen(a.amount))], ["Wei", el("code", {}, a.amount)], ["Buyer (only this account can fund)", el("code", {}, a.buyer)]]),
        ui.notice("info", "Send exactly this amount. If you send a different amount, fund from a different account, or the agreement is no longer fundable, the transaction does not revert: the value is credited to your withdrawable balance and you can withdraw it."),
        can ? ui.txButton("Fund " + AT.fmtGen(a.amount), function () { return { method: "fund", args: [aid], value: BigInt(a.amount) }; }, reload)
          : ui.notice("warn", a.funded ? "This agreement is already funded." : a.status === "CREATED" ? "Only the buyer's account can fund this agreement. You are connected as the " + role + "." : "This agreement is " + a.status.replace(/_/g, " ").toLowerCase() + " and cannot be funded.")),
        ui.panel(el("h2", {}, "What funding means"), el("ul", {}, [
          "The amount is locked in the contract and cannot be moved by anyone until the agreement reaches a final state.",
          "The terms are already fixed by agreement_hash; funding commits you to them. The worker has not agreed yet, so you can still cancel for a full refund.",
          "The escrow is paid out exactly once: to the worker on a settled pass, to you on a refund, or as the jury decides."].map(function (t) { return el("li", {}, t); }))));
    });
  };

  /* ------------------------------------------------------------ accept */
  P.accept = function (aid) {
    return shell(aid, "accept", function (snap, a) {
      var can = a.status === "FUNDED";
      var ack = el("input", { type: "checkbox", id: "ack" });
      var wrap = el("div", {}, ui.panel(el("h2", {}, "Terms you are about to freeze"),
        ui.notice("warn", "Accepting is final. After this, no field below, no requirement and no policy can change, and the agreement is bound to you as the worker."),
        el("p", {}, a.description), el("p", { class: "pre" }, a.specification), requirementList(snap.requirements, null, false),
        ui.kv([["Amount", AT.fmtGen(a.amount)], ["Deadline", AT.fmtTime(a.deadline)], ["Evidence policy", a.evidence_policy], ["Verification policy", a.verification_policy], ["Dispute policy", a.dispute_policy]]),
        ui.hash("agreement_hash", a.agreement_hash)));
      if (can) {
        var btnBox = ui.txButton("Accept and freeze the terms", function () { if (!ack.checked) throw new Error("Tick the box to confirm you have read the terms."); return { method: "accept", args: [aid] }; }, reload);
        wrap.appendChild(ui.panel(el("h2", {}, "Accept"), el("label", { class: "check" }, ack, " I have read every requirement and I accept these terms as they are."), btnBox));
      } else wrap.appendChild(ui.panel(ui.notice("info", a.accepted_at > 0 ? "The worker accepted at " + AT.fmtTime(a.accepted_at) + ". frozen_hash: " + a.frozen_hash : "This agreement is not waiting for acceptance (status " + a.status + ").")));
      if (a.status === "ACCEPTED") wrap.appendChild(ui.panel(el("h2", {}, "Start work"), ui.txButton("Start work", function () { return { method: "start_work", args: [aid] }; }, reload)));
      return wrap;
    });
  };

  /* ------------------------------------------------------------ submit */
  var KINDS = {
    github_file: [["repository", "https://github.com/owner/repo"], ["commit", "40-character commit sha"], ["path", "src/app.py"]],
    github_diff: [["repository", "https://github.com/owner/repo"], ["commit", "40-character commit sha"]],
    github_pr: [["repository", "https://github.com/owner/repo"], ["pr", "pull request number"], ["head", "40-character head commit sha the PR must still point to"]],
    url: [["url", "https://… (PERMISSIVE agreements only)"]],
    text: [["text", "the evidence text itself (10–4000 characters)"]],
    artifact_hash: [["hash", "64 hex characters (sha256)"], ["description", "what this hash identifies"]],
    tx_reference: [["chain", "chain name, e.g. ethereum"], ["tx", "0x + 64 hex characters"]]
  };
  function evidenceRow(policy, onRemove) {
    var kind = el("select", { "aria-label": "Evidence kind" }, Object.keys(KINDS).filter(function (k) { return k !== "url" || policy === "PERMISSIVE"; }).map(function (k) { return el("option", { value: k }, k); }));
    var fields = el("div", { class: "efields" }), inputs = {};
    var draw = function () {
      AT.clear(fields); inputs = {};
      KINDS[kind.value].forEach(function (f) { var i = f[0] === "text" ? el("textarea", { rows: 3, placeholder: f[1], "aria-label": f[0] }) : el("input", { placeholder: f[1], "aria-label": f[0], spellcheck: "false" }); inputs[f[0]] = i; fields.appendChild(i); });
      if (kind.value === "url") fields.appendChild(el("p", { class: "small warn-text" }, "A plain URL is a mutable source: the bytes are frozen at freeze time but the page may change afterwards."));
    };
    kind.addEventListener("change", draw); draw();
    var row = el("div", { class: "evrow" }, kind, fields, el("button", { class: "btn tiny", type: "button", onclick: function () { onRemove(row); } }, "Remove"));
    row.get = function () {
      var o = { kind: kind.value };
      Object.keys(inputs).forEach(function (k) { var v = inputs[k].value.trim(); o[k] = k === "pr" ? Number(v) : v; });
      if (o.pr !== undefined && !(Number.isInteger(o.pr) && o.pr > 0)) throw new Error("Pull request number must be a positive integer.");
      if (o.kind === "artifact_hash") o.algorithm = "sha256";
      ["commit", "head"].forEach(function (k) { if (o[k] !== undefined && !/^[0-9a-fA-F]{40}$/.test(o[k])) throw new Error(k + " must be a full 40-character commit sha."); });
      return o;
    };
    return row;
  }
  P.submit = function (aid) {
    return shell(aid, "submit", function (snap, a) {
      var can = a.status === "IN_PROGRESS";
      var wrap = el("div", {});
      if (!can) {
        wrap.appendChild(ui.panel(ui.notice("info", a.status === "ACCEPTED" ? "Start work first (Accept page)." : "Deliverable submission is only open while the agreement is IN PROGRESS. Current status: " + a.status + "."),
          a.deliverable_statement ? el("div", {}, el("h3", {}, "Submitted statement"), el("p", { class: "pre" }, a.deliverable_statement)) : null));
        wrap.appendChild(evidencePanel(snap));
        if (a.status === "DELIVERED") {
          var n = (snap.evidence_bundle || []).length, total = 0;
          try { total = JSON.parse(a.pending_evidence).length; } catch (e) { total = 0; }
          wrap.appendChild(ui.panel(el("h2", {}, "Freeze the evidence"), el("p", {}, "Either party can freeze. Each call fetches the next item once and stores its exact text; the last call seals the evidence root. " + n + " of " + total + " frozen."),
            ui.txButton("Freeze item " + (n + 1) + " of " + total, function () { return { method: "freeze_evidence", args: [aid] }; }, reload)));
        }
        return wrap;
      }
      var statement = el("textarea", { rows: 4, maxlength: 2000, placeholder: "Describe what you delivered and where each requirement is satisfied." });
      var rows = el("div", { class: "evrows" });
      var add = function () { if (rows.children.length >= AT.LIMITS.evidenceItems) return; rows.appendChild(evidenceRow(a.evidence_policy, function (r) { if (rows.children.length > 1) rows.removeChild(r); })); };
      add();
      wrap.appendChild(ui.panel(el("h2", {}, "Submit deliverable evidence"),
        ui.notice("info", "Prefer references pinned to a full commit sha. Nothing is fetched at submission time: the evidence is fetched and sealed only when someone runs freeze_evidence. Until then it is only a list of references."),
        a.evidence_policy === "STRICT" ? ui.notice("warn", "This agreement is STRICT: plain URLs are not accepted.") : null,
        ui.field("Statement", statement), rows, el("button", { class: "btn", type: "button", onclick: add }, "Add evidence item"),
        ui.txButton("Submit deliverable", function () {
          var st = statement.value.trim();
          if (st.length < AT.LIMITS.statement[0]) throw new Error("Statement must be at least 10 characters.");
          var items = Array.prototype.map.call(rows.children, function (r) { return r.get(); });
          return { method: "submit_deliverable", args: [aid, st, JSON.stringify(items)] };
        }, reload)));
      return wrap;
    });
  };

  /* ------------------------------------------------------------ verification dashboard */
  P.verification = function (aid) {
    return shell(aid, "verification", function (snap, a) {
      var reqs = snap.requirements, adv = a.verification_policy === "ADVERSARIAL";
      var judged = reqs.filter(function (r) { return r.verdict !== "UNVERIFIED"; }).length;
      var redone = reqs.filter(function (r) { return r.red_done; }).length;
      var passing = reqs.filter(function (r) { return r.verdict === "PASS"; }).length;
      var pending = a.status === "VERIFICATION_PENDING";
      var pct = reqs.length ? Math.round(100 * judged / reqs.length) : 0;
      var rows = reqs.map(function (r) {
        var actions = [];
        if (pending && r.verdict === "UNVERIFIED") actions.push(ui.txButton("Verify", function () { return { method: "verify_requirement", args: [aid, r.requirement_id] }; }, reload, { kind: "" }));
        if (pending && adv && r.verdict === "PASS" && !r.red_done) actions.push(ui.txButton("Red-team", function () { return { method: "red_team_requirement", args: [aid, r.requirement_id] }; }, reload, { kind: "" }));
        return el("tr", {}, el("td", {}, ui.link("#/a/" + aid + "/requirement/" + r.requirement_id, r.requirement_id)),
          el("td", { class: "desc" }, r.description),
          el("td", {}, ui.statusBadge(r.status), r.detail ? el("div", { class: "small muted" }, r.detail.replace(/_/g, " ").toLowerCase()) : null),
          el("td", {}, adv ? (r.redteam ? ui.badge(r.redteam.outcome.replace(/_/g, " ").toLowerCase(), r.redteam.outcome === "COUNTEREXAMPLE" ? "bad" : "ok") : r.red_done ? ui.badge("done", "muted") : ui.badge("pending", "muted")) : el("span", { class: "muted" }, "n/a")),
          el("td", {}, String(r.challenge_count)), el("td", {}, actions));
      });
      var late = pending && a.stage_deadline && Date.now() / 1000 > a.stage_deadline;
      var ready = pending && (late || (judged === reqs.length && (!adv || redone >= passing)));
      return el("div", {},
        ui.panel(el("h2", {}, "Verification progress"), el("div", { class: "bar", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 }, el("div", { class: "barfill", style: "width:" + pct + "%" })),
          el("p", {}, judged + " of " + reqs.length + " requirements judged" + (adv ? " · " + redone + " of " + passing + " passes red-teamed" : "")),
          ui.kv([["Protocol result", a.protocol_result ? ui.statusBadge(a.protocol_result) : "not yet aggregated"], ["Result note", a.result_note || "—"], ["Verified at", AT.fmtTime(a.aggregated_at)]]),
          el("p", { class: "muted small" }, "Anyone can trigger these steps; the contract, not the caller, decides the outcome. Each verdict needs validator consensus on the categorical result and every quote is checked as a verbatim substring of the frozen evidence."),
          pending ? (ready ? ui.txButton("Aggregate the result", function () { return { method: "aggregate", args: [aid] }; }, reload) : el("p", { class: "muted" }, "Aggregation unlocks when every requirement is judged" + (adv ? " and every pass is red-teamed." : ".") + " Requirements that are never judged before the verify window closes are filled as insufficient evidence.")) : null),
        ui.panel(el("h2", {}, "Requirements"), el("div", { class: "tablewrap" }, el("table", { class: "grid" },
          el("thead", {}, el("tr", {}, ["Requirement", "Statement", "Result", "Red team", "Challenges", ""].map(function (h) { return el("th", {}, h); }))), el("tbody", {}, rows)))),
        ui.panel(el("h2", {}, "How the overall result is derived"), el("ol", {}, [
          "Any requirement that FAILS makes the overall result FAIL.",
          "Otherwise, any requirement with conflicting evidence makes it CONFLICTING EVIDENCE.",
          "Otherwise, any requirement that is not a clean PASS makes it INSUFFICIENT EVIDENCE.",
          "Only if every requirement is a grounded PASS is the overall result PASS. A model saying PASS without a quote from the frozen evidence is downgraded automatically."].map(function (t) { return el("li", {}, t); }))));
    });
  };

  /* ------------------------------------------------------------ one requirement */
  P.requirement = function (aid, rid) {
    return shell(aid, "verification", function (snap, a) {
      var r = snap.requirements.filter(function (x) { return x.requirement_id === rid; })[0];
      if (!r) return ui.notice("bad", "Unknown requirement " + rid);
      var bundle = snap.evidence_bundle, chs = snap.challenges.filter(function (c) { return c.requirement_id === rid; });
      var chain = el("ol", { class: "chain" },
        el("li", {}, el("strong", {}, "Verifier consensus: "), r.verification ? [ui.statusBadge(r.verification.verdict), " ", r.verification.detail ? ui.badge(r.verification.detail.replace(/_/g, " ").toLowerCase(), "warn") : null] : ui.badge("not judged", "muted")),
        a.verification_policy === "ADVERSARIAL" ? el("li", {}, el("strong", {}, "Red team: "), r.redteam ? ui.badge(r.redteam.outcome.replace(/_/g, " ").toLowerCase(), r.redteam.outcome === "COUNTEREXAMPLE" ? "bad" : "ok") : ui.badge(r.red_done ? "done" : "pending", "muted")) : null,
        el("li", {}, el("strong", {}, "Challenges: "), chs.length ? chs.map(function (c) { return ui.badge(c.side.toLowerCase() + " " + c.status.toLowerCase(), c.status === "UPHELD" ? "bad" : "muted"); }) : "none"),
        el("li", {}, el("strong", {}, "Standing result: "), ui.statusBadge(r.status), r.detail ? " " : null, r.detail ? ui.badge(r.detail.replace(/_/g, " ").toLowerCase(), "warn") : null));
      return el("div", {},
        ui.panel(el("h2", {}, r.requirement_id), el("p", {}, r.description), ui.kv([["Method", r.method.replace(/_/g, " ").toLowerCase()], ["Evidence needed", r.evidence_requirements]]), ui.hash("requirement_hash", r.requirement_hash)),
        ui.panel(el("h2", {}, "How this result came about"), chain),
        r.verification ? ui.panel(el("h2", {}, "Verifier record"), el("p", {}, r.verification.reason || "No reason recorded."),
          r.verification.quotes.length ? r.verification.quotes.map(function (q) { return ui.quoteBlock(q, bundle); }) : el("p", { class: "muted" }, "No quotes. A PASS without a quote from the frozen evidence is never accepted.")) : null,
        r.redteam ? ui.panel(el("h2", {}, "Red-team record"), el("p", {}, r.redteam.claim || "No claim."), r.redteam.quotes.map(function (q) { return ui.quoteBlock(q, bundle); })) : null,
        chs.length ? ui.panel(el("h2", {}, "Challenges"), chs.map(function (c) {
          return el("div", { class: "challenge" }, el("div", { class: "row wrap" }, el("strong", {}, c.challenge_id), ui.badge(c.side.toLowerCase(), "muted"), ui.badge(c.status.toLowerCase(), c.status === "UPHELD" ? "bad" : "ok"),
            el("span", { class: "muted small" }, c.original_status + " → " + c.resolved_status)), el("p", {}, c.claim), el("p", { class: "muted" }, c.reasoning),
            ui.quoteBlock({ evidence_id: c.evidence_id, quote: c.quote }, bundle), c.resolution && c.resolution.reason ? el("p", { class: "small" }, "Auditor: " + c.resolution.reason) : null);
        })) : null,
        ui.link("#/a/" + aid + "/verification", "← Back to the verification dashboard"));
    });
  };

  /* ------------------------------------------------------------ challenge and dispute */
  function saltKey(aid, who) { return "salt." + aid + "." + who; }
  function randomSalt() { var b = new Uint8Array(16); (window.crypto || {}).getRandomValues ? window.crypto.getRandomValues(b) : b.forEach(function (_, i) { b[i] = Math.floor(Math.random() * 256); }); return Array.prototype.map.call(b, function (x) { return ("0" + x.toString(16)).slice(-2); }).join(""); }
  function countdown(ts, label) { return ts ? [label, AT.fmtTime(ts)] : null; }
  P.dispute = function (aid) {
    return shell(aid, "dispute", function (snap, a) {
      var d = snap.dispute, reqs = snap.requirements, s = a.status, wrap = el("div", {});
      // challenge
      var canChallenge = s === "VERIFIED_PASS" || s === "CHALLENGE";
      var rsel = el("select", { "aria-label": "Requirement" }, reqs.map(function (r) { return el("option", { value: r.requirement_id }, r.requirement_id + " · " + r.verdict + " · " + r.description.slice(0, 50)); }));
      var claim = el("textarea", { rows: 2, maxlength: 600, placeholder: "The specific claim you dispute (20–600 characters)" });
      var esel = el("select", { "aria-label": "Evidence item" }, (snap.evidence_bundle || []).map(function (e) { return el("option", { value: e.item_id }, e.item_id + " · " + e.source); }));
      var quote = el("textarea", { rows: 2, maxlength: 400, placeholder: "A passage copied verbatim from that evidence item (6–400 characters)" });
      var reasoning = el("textarea", { rows: 3, maxlength: 1000, placeholder: "Why the passage shows the current result is wrong (40–1000 characters)" });
      wrap.appendChild(ui.panel(el("h2", {}, "Challenge a requirement"),
        el("p", { class: "muted" }, "A challenge asks the auditor to re-read the same frozen evidence. It must quote the evidence verbatim; the contract checks the quote itself. The buyer can challenge a passing requirement, the worker a failing one (in the challenge phase of a dispute). Each side gets one challenge per requirement."),
        canChallenge ? [ui.field("Requirement", rsel), ui.field("Claim", claim), ui.field("Evidence item", esel), ui.field("Quote", quote), ui.field("Reasoning", reasoning),
          ui.txButton("Submit challenge", function () {
            var L = AT.LIMITS;
            if (claim.value.trim().length < L.claim[0]) throw new Error("Claim must be at least 20 characters.");
            if (!esel.value) throw new Error("There is no frozen evidence to cite.");
            if (quote.value.trim().length < L.quote[0]) throw new Error("Quote must be at least 6 characters.");
            if (reasoning.value.trim().length < L.reasoning[0]) throw new Error("Reasoning must be at least 40 characters.");
            var ev = (snap.evidence_bundle || []).filter(function (e) { return e.item_id === esel.value; })[0];
            if (ev && !AT.grounded(quote.value, ev.content)) throw new Error("That quote is not found verbatim in " + esel.value + ". The contract would reject it.");
            return { method: "challenge_requirement", args: [aid, rsel.value, claim.value.trim(), esel.value, quote.value.trim(), reasoning.value.trim()] };
          }, reload)] : el("p", { class: "muted" }, "Challenges are open while the agreement is VERIFIED PASS (buyer) or in the CHALLENGE phase of a dispute. Current status: " + s + ".")));

      // open a dispute
      var canOpen = a.dispute_policy === "JURY" && ["VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"].indexOf(s) !== -1;
      if (a.dispute_policy !== "JURY") wrap.appendChild(ui.panel(el("h2", {}, "Dispute"), ui.notice("info", "This agreement's dispute policy is NONE: the protocol result is final.")));
      else if (!d) {
        var bond = BigInt(a.amount) / 20n; if (bond < 10n ** 17n) bond = 10n ** 17n;
        var against = reqs.filter(function (r) { return s === "VERIFIED_PASS" ? r.verdict === "PASS" : (r.verdict === "FAIL" || r.verdict === "INSUFFICIENT_EVIDENCE"); });
        var checks = against.map(function (r) { return el("label", { class: "check" }, el("input", { type: "checkbox", value: r.requirement_id }), " " + r.requirement_id + " · " + r.verdict + " · " + r.description); });
        var disputer = s === "VERIFIED_PASS" ? "buyer" : "worker", role = AT.role(a);
        if (canOpen && role !== "visitor" && role !== disputer) canOpen = false;
        var stmt = el("textarea", { rows: 3, maxlength: 2000, placeholder: "Why the protocol result is wrong (20–2000 characters)" });
        wrap.appendChild(ui.panel(el("h2", {}, "Open a dispute"), el("p", { class: "muted" }, "Only the losing party can open a dispute (the buyer against a pass, the worker against a fail). It requires a bond of " + AT.fmtGen(bond.toString()) + " (the larger of 0.1 GEN and 5% of the amount). Three jurors are then drawn from the pre-registered juror pool with public drand randomness and vote with commit and reveal. Half the bond is the jury fee and pays the jurors whichever side wins; the other half is returned if you win and goes to the other party if you lose. If no jury can be seated, or the jury deadlocks, the automated result stands and the bond is returned (minus the fee only when jurors actually voted)."),
          canOpen ? [el("div", { class: "checks" }, checks), ui.field("Statement", stmt), ui.txButton("Open dispute with " + AT.fmtGen(bond.toString()) + " bond", function () {
            var ids = checks.map(function (c) { return c.firstChild; }).filter(function (i) { return i.checked; }).map(function (i) { return i.value; });
            if (!ids.length) throw new Error("Choose at least one requirement to dispute.");
            if (stmt.value.trim().length < 20) throw new Error("Write a statement of at least 20 characters.");
            return { method: "open_dispute", args: [aid, ids.join(","), stmt.value.trim()], value: bond };
          }, reload)] : el("p", { class: "muted" }, AT.role(a) !== "visitor" && ["VERIFIED_PASS", "VERIFIED_FAIL", "INSUFFICIENT_EVIDENCE"].indexOf(s) !== -1
            ? "Only the " + (s === "VERIFIED_PASS" ? "buyer" : "worker") + " can dispute this result."
            : "Disputes can be opened while the agreement is VERIFIED PASS, VERIFIED FAIL or INSUFFICIENT EVIDENCE, before the window closes. Current status: " + s + ".")));
      } else {
        wrap.appendChild(disputePanel(snap, a, d));
      }
      return wrap;
    });
  };
  function disputePanel(snap, a, d) {
    var aid = a.agreement_id, s = a.status, me = AT.state.account, box = el("div", {});
    box.appendChild(ui.panel(el("h2", {}, "Dispute"), ui.kv([["Opened by", el("code", {}, AT.short(d.opened_by) + " (" + d.side.toLowerCase() + ")")], ["Requirements", d.requirement_ids], ["Bond", AT.fmtGen(d.bond)],
      countdown(d.phase_deadline, "Response deadline"), countdown(d.commit_deadline, "Commit deadline"), countdown(d.reveal_deadline, "Reveal deadline"),
      ["Juror pool snapshot", d.pool_size + " registered jurors (only these can be drawn)"],
      d.beacon_round ? ["Randomness", el("span", {}, "drand round " + d.beacon_round + (d.beacon ? " · " : ""), d.beacon ? el("code", { class: "hash" }, d.beacon) : null)] : null,
      d.result ? ["Result", ui.statusBadge(d.result)] : null]),
      el("h3", {}, "Statement"), el("p", { class: "pre" }, d.statement), el("h3", {}, "Response"), el("p", { class: "pre" }, d.response || "No response yet.")));
    // stage actions
    var act = [];
    if (s === "DISPUTED") {
      var resp = el("textarea", { rows: 3, maxlength: 2000, placeholder: "The other party's response (20–2000 characters)" });
      act.push(el("div", {}, el("h3", {}, "Respond"), resp, ui.txButton("Respond to dispute", function () { if (resp.value.trim().length < 20) throw new Error("Response must be at least 20 characters."); return { method: "respond_dispute", args: [aid, resp.value.trim()] }; }, reload)));
      act.push(el("div", {}, el("h3", {}, "Move to the challenge phase"), el("p", { class: "muted small" }, "Anyone, after the response window."), ui.txButton("Start challenge phase", function () { return { method: "start_challenge_phase", args: [aid] }; }, reload, { kind: "" })));
    }
    if (s === "CHALLENGE") act.push(el("div", {}, el("h3", {}, "Seat the jury"), el("p", { class: "muted small" }, "Anyone, about a minute after the challenge phase ends (the drand round must be published). Three jurors are drawn from the pool snapshot. With fewer than three eligible jurors, or if nobody seats the jury within the grace period, the automated result stands."), ui.txButton("Seat jury", function () { return { method: "seat_jury", args: [aid] }; }, reload)));
    if (s === "FINAL_REVIEW") {
      var stored = me ? AT.store.get("vote." + aid + "." + me, "") : "";
      var vote = el("select", { "aria-label": "Vote" }, el("option", { value: "WORKER", selected: stored === "WORKER" }, "WORKER: the work satisfies the requirements"), el("option", { value: "BUYER", selected: stored === "BUYER" }, "BUYER: it does not"));
      var salt = el("input", { class: "mono", "aria-label": "Salt", spellcheck: "false", value: AT.store.get(saltKey(aid, me || "x"), "") || randomSalt() });
      act.push(el("div", {}, el("h3", {}, "Your vote (seated jurors only)"), el("p", { class: "muted small" }, "Commit a hash of your vote and a secret salt first; after the commit window, reveal both. Keep the salt: it is stored in this browser if storage is available, and you must copy it if not. Losing it means you cannot reveal."),
        ui.field("Vote", vote), ui.field("Salt", salt),
        ui.txButton("Commit vote", function () {
          if (!me) throw new Error("Connect a wallet first.");
          if (salt.value.trim().length < 8) throw new Error("Salt must be at least 8 characters.");
          var h = window.AgentTrustVerify.sha(aid + ":" + me + ":" + vote.value + ":" + salt.value.trim());
          AT.store.set(saltKey(aid, me), salt.value.trim());
          AT.store.set("vote." + aid + "." + me, vote.value);
          AT.store.set("commit." + aid + "." + me, h);
          return { method: "commit_vote", args: [aid, h] };
        }, reload),
        ui.txButton("Reveal vote", function () {
          if (!me) throw new Error("Connect a wallet first.");
          var v = vote.value, sl = salt.value.trim(), committed = AT.store.get("commit." + aid + "." + me, "");
          if (committed && window.AgentTrustVerify.sha(aid + ":" + me + ":" + v + ":" + sl) !== committed)
            throw new Error("This vote and salt do not match what you committed from this browser. Choose the vote you committed and use the same salt.");
          return { method: "reveal_vote", args: [aid, v, sl] };
        }, reload, { kind: "" })));
      act.push(el("div", {}, el("h3", {}, "Finalize"), el("p", { class: "muted small" }, "Anyone, once everyone revealed or the reveal window closed."), ui.txButton("Finalize dispute", function () { return { method: "finalize_dispute", args: [aid] }; }, reload)));
    }
    if (act.length) box.appendChild(ui.panel(el("h2", {}, "Actions for this stage"), act));
    box.appendChild(ui.panel(el("h2", {}, "Jury"), el("p", { class: "small muted" }, "Pool snapshot: " + d.pool_size + " · Seated: " + d.jurors.length + " · Revealed: " + d.revealed + " (worker " + d.votes_worker + ", buyer " + d.votes_buyer + ")"),
      d.jurors.length ? el("div", { class: "tablewrap" }, el("table", { class: "grid" }, el("thead", {}, el("tr", {}, ["Juror", "Committed", "Revealed", "Vote"].map(function (h) { return el("th", {}, h); }))),
        el("tbody", {}, d.jurors.map(function (j) { return el("tr", {}, el("td", {}, el("code", {}, AT.short(j.address))), el("td", {}, j.committed ? "yes" : "no"), el("td", {}, j.revealed ? "yes" : "no"), el("td", {}, j.vote || "hidden")); })))) : el("p", { class: "muted" }, "No jury seated yet."),
      ui.link("#/jury", "Join the juror pool for future disputes"),
      el("p", { class: "small muted" }, "Voting rule: a strict majority of revealed votes with at least two reveals decides. A tie or too few reveals leaves the automated result in place.")));
    return box;
  }

  /* ------------------------------------------------------------ certificate */
  function download(name, text) {
    var url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    var a = el("a", { href: url, download: name }); document.body.appendChild(a); a.click(); document.body.removeChild(a); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  P.certificate = function (aid) {
    return shell(aid, "certificate", function (snap, a) {
      if (!snap.certificate) return ui.panel(el("h2", {}, "No certificate yet"), el("p", {}, "A certificate is sealed in the same transaction that moves the money, when the agreement reaches SETTLED, FINALIZED or REFUNDED. Current status: " + a.status + "."), ui.stateMachine(a.status));
      var cert = JSON.parse(snap.certificate), bundle = { evidence: snap.evidence_bundle, challenges: snap.challenges };
      var rep = window.AgentTrustVerify.verify(snap.certificate, bundle, snap.certificate_hash);
      var s = cert.settlement;
      return el("div", {},
        ui.panel(el("h2", {}, "Certificate"), el("div", { class: "row wrap" }, ui.statusBadge(cert.final_verdict), ui.statusBadge(cert.terminal_state)),
          ui.kv([["Terminal state", cert.terminal_state], ["Final verdict", cert.final_verdict], ["Result note", cert.result_note || "—"], ["To worker", AT.fmtGen(s.to_worker)], ["To buyer", AT.fmtGen(s.to_buyer)], ["Finalized", AT.fmtTime(cert.finalized_at)],
            cert.dispute ? ["Jury result", cert.dispute.result + " (" + cert.dispute.votes_worker + " worker, " + cert.dispute.votes_buyer + " buyer)"] : null]),
          ui.hash("certificate_hash (on-chain)", snap.certificate_hash), el("p", { class: "muted small" }, cert.statement),
          el("div", { class: "row wrap" }, el("button", { class: "btn", type: "button", onclick: function () { download(aid + "-certificate.json", snap.certificate); } }, "Download certificate"),
            el("button", { class: "btn", type: "button", onclick: function () { download(aid + "-bundle.json", JSON.stringify(bundle)); } }, "Download evidence bundle"), ui.link("#/verify/" + aid, "Open in the public verifier", "btn"))),
        ui.panel(el("h2", {}, "Verified in your browser just now"), AT.reportView(rep), el("p", { class: "muted small" }, "Run offline with the two downloaded files:"),
          el("pre", { class: "code" }, "python3 scripts/verification/verify_certificate.py " + aid + "-certificate.json --bundle " + aid + "-bundle.json --onchain-hash " + snap.certificate_hash)),
        ui.panel(el("h2", {}, "Raw certificate (canonical JSON)"), el("details", {}, el("summary", {}, "Show"), el("pre", { class: "code" }, JSON.stringify(cert, null, 2)))));
    });
  };
})(window.AT);
