/* Shared UI components. Everything derived from chain data is inserted as text, never as HTML. */
(function (AT) {
  "use strict";
  var el = AT.el;
  var ui = (AT.ui = {});
  var SVGNS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    for (var i = 2; i < arguments.length; i++) { var c = arguments[i]; if (c) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); }
    return n;
  }

  function labelText(state) {
    var words = state.split("_"), lines;
    if (state.length > 13 && words.length > 1) {
      var best = 1, bestDiff = 1e9;
      for (var i = 1; i < words.length; i++) {
        var d = Math.abs(words.slice(0, i).join(" ").length - words.slice(i).join(" ").length);
        if (d < bestDiff) { bestDiff = d; best = i; }
      }
      lines = [words.slice(0, best).join(" "), words.slice(best).join(" ")];
    } else lines = [words.join(" ")];
    var t = svg("text", { x: 59, "text-anchor": "middle" });
    lines.forEach(function (l, i) { t.appendChild(svg("tspan", { x: 59, y: lines.length === 1 ? 24 : 17 + i * 13 }, l)); });
    return t;
  }

  ui.panel = function () { var p = el("section", { class: "panel" }); for (var i = 0; i < arguments.length; i++) AT.append(p, arguments[i]); return p; };
  ui.badge = function (text, cls) { return el("span", { class: "badge " + (cls || "") }, text); };
  ui.statusBadge = function (s) {
    var map = { PASS: "ok", VERIFIED_PASS: "ok", SETTLED: "ok", FAIL: "bad", VERIFIED_FAIL: "bad", INSUFFICIENT_EVIDENCE: "warn", CONFLICTING_EVIDENCE: "warn",
      UNVERIFIED: "muted", NOT_VERIFIED: "muted", DISPUTED: "dispute", CHALLENGE: "dispute", FINAL_REVIEW: "dispute", FINALIZED: "info", REFUNDED: "info",
      CANCELLED: "muted", TIMEOUT: "warn", CREATED: "draft", FUNDED: "committed", ACCEPTED: "frozen", IN_PROGRESS: "frozen", DELIVERED: "frozen", VERIFICATION_PENDING: "verify" };
    return ui.badge(String(s || "").replace(/_/g, " "), map[s] || "muted");
  };
  ui.notice = function (kind, text) { return el("div", { class: "notice " + kind, role: kind === "bad" ? "alert" : "note" }, text); };
  ui.loading = function (text) { return el("div", { class: "loading", "aria-busy": "true" }, text || "Loading…"); };
  ui.kv = function (rows) {
    var dl = el("dl", { class: "kv" });
    rows.forEach(function (r) { if (r) { dl.appendChild(el("dt", {}, r[0])); dl.appendChild(el("dd", {}, r[1])); } });
    return dl;
  };
  ui.copy = function (text) {
    return el("button", { class: "btn tiny", type: "button", "aria-label": "Copy to clipboard", onclick: function (e) {
      var b = e.currentTarget;
      var done = function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1200); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { b.textContent = "Select and copy manually"; });
      else b.textContent = "Select and copy manually";
    } }, "Copy");
  };
  ui.hash = function (label, value) {
    return el("div", { class: "hashrow" }, el("span", { class: "hashlabel" }, label), el("code", { class: "hash", title: value || "" }, value || "—"), value ? ui.copy(value) : null);
  };
  ui.field = function (label, input, hint) {
    return el("label", { class: "field" }, el("span", { class: "flabel" }, label), input, hint ? el("span", { class: "hint" }, hint) : null);
  };
  ui.link = function (href, text, cls) { return el("a", { href: href, class: cls || "" }, text); };

  /* ---------------------------------------------------------- state machine */
  ui.stateMachine = function (current) {
    var W = 118, H = 40, DX = 128, DY = 126, X0 = 8, Y0 = 16;
    var pos = function (s) { var l = AT.LAYOUT[s]; return { x: X0 + l[0] * DX, y: Y0 + l[1] * DY, col: l[0], row: l[1] }; };
    var nextSet = {};
    (AT.EDGES[current] || []).forEach(function (s) { nextSet[s] = true; });
    var root = svg("svg", { viewBox: "0 0 1040 372", class: "sm", role: "img", "aria-label": "Agreement state machine. Current state: " + current, width: 1040, height: 372 });
    root.appendChild(svg("defs", {},
      svg("marker", { id: "arr", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: "arrowhead" })),
      svg("marker", { id: "arrHot", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: "arrowhead hot" }))));
    function edge(a, b) {
      var A = pos(a), B = pos(b), hot = a === current;
      var ax = A.x + W / 2, ay = A.y + H / 2, bx = B.x + W / 2, by = B.y + H / 2, d;
      if (A.row === B.row && Math.abs(A.col - B.col) > 1) {
        var y = A.y + H, mx = (ax + bx) / 2;
        d = "M" + ax + "," + y + " Q" + mx + "," + (y + 48) + " " + bx + "," + (B.y + H + 2);
      } else {
        var dx = bx - ax, dy = by - ay;
        var clip = function (sx, sy) { var t = Math.min(sx === 0 ? Infinity : (W / 2 + 3) / Math.abs(sx), sy === 0 ? Infinity : (H / 2 + 3) / Math.abs(sy)); return t; };
        var t1 = clip(dx, dy);
        d = "M" + (ax + dx * t1) + "," + (ay + dy * t1) + " L" + (bx - dx * t1) + "," + (by - dy * t1);
      }
      return svg("path", { d: d, class: "edge" + (hot ? " hot" : ""), "marker-end": hot ? "url(#arrHot)" : "url(#arr)" });
    }
    Object.keys(AT.EDGES).forEach(function (a) { if (a !== current) AT.EDGES[a].forEach(function (b) { root.appendChild(edge(a, b)); }); });
    (AT.EDGES[current] || []).forEach(function (b) { root.appendChild(edge(current, b)); });
    Object.keys(AT.LAYOUT).forEach(function (s) {
      var p = pos(s), info = AT.STATE_INFO[s], terminal = AT.TERMINAL.indexOf(s) !== -1;
      var cls = "node phase-" + AT.PHASES[info.phase].css + (s === current ? " current" : "") + (nextSet[s] ? " next" : "") + (terminal ? " terminal" : "");
      var g = svg("g", { class: cls, transform: "translate(" + p.x + "," + p.y + ")" },
        svg("title", {}, s + ": " + info.text),
        svg("rect", { width: W, height: H, rx: 8 }),
        labelText(s));
      root.appendChild(g);
    });
    return el("div", { class: "smwrap" }, root,
      el("div", { class: "legend" },
        el("span", { class: "lg current" }, "current state"), el("span", { class: "lg next" }, "possible next state"), el("span", { class: "lg terminal" }, "final (never changes again)"),
        el("span", { class: "lg hotedge" }, "transitions from here")));
  };

  /* ---------------------------------------------------------- draft / committed / frozen */
  ui.commitStrip = function (a) {
    var lvl = AT.commitmentLevel(a), order = ["draft", "committed", "frozen"], idx = order.indexOf(lvl.key);
    var steps = [
      ["Draft", "mutable-looking, unfunded", "Terms exist and are hashed, but nobody is bound. The buyer can cancel."],
      ["Committed", "buyer bound", "Escrow is locked. The worker has not agreed; the buyer can still cancel for a refund."],
      ["Frozen", "both bound", "Worker accepted: terms + worker + time are sealed in frozen_hash. Nothing can be edited."]
    ];
    return el("div", { class: "strip" },
      el("ol", { class: "steps" }, steps.map(function (s, i) {
        return el("li", { class: (i < idx ? "done " : "") + (i === idx ? "now " : "") + "lvl-" + order[i] },
          el("strong", {}, s[0]), el("span", { class: "sub" }, s[1]), el("span", { class: "desc" }, s[2]));
      })),
      el("p", { class: "strip-now" }, el("strong", {}, "This agreement is " + lvl.label.toLowerCase() + ". "), lvl.text));
  };

  ui.evidenceFlag = function (item) {
    if (item.mutable === 1) return ui.badge("content frozen · source is mutable", "warn");
    if (item.kind === "text" || item.kind === "artifact_hash" || item.kind === "tx_reference") return ui.badge("content frozen · self-contained", "ok");
    return ui.badge("content frozen · pinned by commit", "ok");
  };

  /* ---------------------------------------------------------- navigation inside one agreement */
  ui.subnav = function (aid, current) {
    var pages = [["", "Overview"], ["fund", "Fund"], ["accept", "Accept"], ["submit", "Submit"], ["verification", "Verification"], ["dispute", "Challenge & dispute"], ["certificate", "Certificate"]];
    return el("nav", { class: "subnav", "aria-label": "Agreement pages" }, pages.map(function (p) {
      return el("a", { href: "#/a/" + aid + (p[0] ? "/" + p[0] : ""), class: p[0] === (current || "") ? "active" : "", "aria-current": p[0] === (current || "") ? "page" : null }, p[1]);
    }));
  };
  ui.agreementHeader = function (snap, page) {
    var a = snap.agreement;
    return el("header", { class: "ahead" },
      el("div", { class: "row wrap" }, el("h1", {}, a.title), ui.statusBadge(a.status)),
      el("p", { class: "muted" }, a.agreement_id + " · " + AT.fmtGen(a.amount) + " · buyer " + AT.short(a.buyer) + " · worker " + AT.short(a.worker)),
      ui.subnav(a.agreement_id, page));
  };

  /* ---------------------------------------------------------- transactions */
  ui.txLog = function () {
    var box = el("pre", { class: "txlog", "aria-live": "polite" }, "");
    var log = function (s) { box.textContent += s + "\n"; box.scrollTop = box.scrollHeight; box.hidden = false; };
    box.hidden = true;
    return { box: box, log: log };
  };
  /* A button that sends one transaction. build() returns {method,args,value}; it may throw a validation error. */
  ui.txButton = function (label, build, done, opts) {
    opts = opts || {};
    var out = ui.txLog(), status = el("span", { class: "muted small", role: "status" });
    var demo = AT.state.mode !== "live";
    var btn = el("button", { class: "btn " + (opts.kind || "primary"), type: "button", disabled: demo, title: demo ? "The recorded demo is read-only" : "", onclick: async function () {
      status.textContent = "";
      var spec;
      try { spec = build(); } catch (e) { status.textContent = e.message || String(e); status.className = "bad small"; return; }
      btn.disabled = true; status.className = "muted small"; status.textContent = "sending…";
      try {
        await AT.tx(spec.method, spec.args, { value: spec.value }, out.log);
        status.textContent = "done"; status.className = "ok small";
        if (done) done();
      } catch (e) { status.textContent = e.message || String(e); status.className = "bad small"; out.log("  failed: " + (e.message || e)); btn.disabled = false; }
    } }, label);
    var wrap = el("div", { class: "txwrap" }, el("div", { class: "row wrap" }, btn, status, demo ? el("span", { class: "muted small" }, "Read-only demo: switch to Live mode in Settings to send this.") : null), out.box);
    return wrap;
  };

  ui.jsonBlock = function (text) { return el("pre", { class: "code" }, typeof text === "string" ? text : JSON.stringify(text, null, 2)); };
  ui.quoteBlock = function (q, bundle) {
    var item = (bundle || []).filter(function (e) { return e.item_id === q.evidence_id; })[0];
    var ok = item ? AT.grounded(q.quote, item.content) : null;
    return el("blockquote", { class: "quote" }, el("div", {}, "“" + q.quote + "”"),
      el("div", { class: "quotemeta" }, el("span", {}, "from " + q.evidence_id + (item ? " · " + item.source : "")),
        ok === null ? ui.badge("evidence not loaded", "muted") : ok ? ui.badge("found verbatim in frozen evidence", "ok") : ui.badge("NOT found in frozen evidence", "bad")));
  };
})(window.AT);
