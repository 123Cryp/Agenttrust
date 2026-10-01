/* Router, header and settings. Hash routing: every page has a shareable URL and works with the back button. */
(function (AT) {
  "use strict";
  var el = AT.el, ui = AT.ui, P = AT.pages;

  var ROUTES = [
    [/^\/?$/, function () { return P.home(); }, "home"],
    [/^\/browse$/, function () { return P.browse(); }, "browse"],
    [/^\/new$/, function () { return P.create(); }, "new"],
    [/^\/mine$/, function () { return P.mine(); }, "mine"],
    [/^\/jury$/, function () { return P.jury(); }, "jury"],
    [/^\/verify(?:\/(AT-\d+))?$/, function (m) { return P.verify(m[1]); }, "verify"],
    [/^\/a\/(AT-\d+)$/, function (m) { return P.details(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/fund$/, function (m) { return P.fund(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/accept$/, function (m) { return P.accept(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/submit$/, function (m) { return P.submit(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/verification$/, function (m) { return P.verification(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/requirement\/(REQ-\d{3})$/, function (m) { return P.requirement(m[1], m[2]); }, "browse"],
    [/^\/a\/(AT-\d+)\/dispute$/, function (m) { return P.dispute(m[1]); }, "browse"],
    [/^\/a\/(AT-\d+)\/certificate$/, function (m) { return P.certificate(m[1]); }, "browse"]
  ];
  var NAV = [["home", "#/", "Home"], ["browse", "#/browse", "Agreements"], ["new", "#/new", "Create"], ["mine", "#/mine", "Mine"], ["jury", "#/jury", "Jury"], ["verify", "#/verify", "Verify"]];
  var seq = 0;

  AT.route = async function () {
    var view = document.getElementById("view");
    var path = (location.hash || "#/").replace(/^#/, "").split("?")[0];
    if (path && path.charAt(0) !== "/") return;
    var mine = ++seq, hit = null, m = null;
    for (var i = 0; i < ROUTES.length; i++) { m = ROUTES[i][0].exec(path); if (m) { hit = ROUTES[i]; break; } }
    AT.clear(view);
    view.appendChild(ui.loading());
    drawNav(hit ? hit[2] : "");
    var node;
    try {
      node = hit ? await hit[1](m) : el("div", { class: "page" }, el("h1", {}, "Page not found"), el("p", {}, "There is no page at " + path + "."), ui.link("#/", "Go to the home page", "btn"));
    } catch (e) {
      node = el("div", { class: "page" }, ui.notice("bad", "Could not load this page: " + (e && e.message ? e.message : String(e))),
        AT.state.mode === "live" ? el("p", { class: "muted" }, "Check the contract address and network in Settings.") : null, ui.link("#/", "Home", "btn"));
    }
    if (mine !== seq) return;
    AT.clear(view); view.appendChild(node);
    window.scrollTo(0, 0);
    view.focus({ preventScroll: true });
    document.title = (hit && hit[2] !== "home" ? path.replace(/^\//, "") + " · " : "") + "AgentTrust";
  };

  function drawNav(active) {
    var nav = document.getElementById("nav");
    AT.clear(nav);
    NAV.forEach(function (n) { nav.appendChild(el("a", { href: n[1], class: n[0] === active ? "active" : "", "aria-current": n[0] === active ? "page" : null }, n[2])); });
  }

  AT.refreshHeader = function () {
    var chip = document.getElementById("modechip");
    AT.clear(chip);
    chip.appendChild(ui.badge(AT.state.mode === "demo" ? "Recorded demo (offline)" : "Live: " + (AT.CFG.chain || "studionet"), AT.state.mode === "demo" ? "warn" : "ok"));
    if (AT.state.account) chip.appendChild(el("span", { class: "small muted", title: AT.state.account }, " " + AT.short(AT.state.account)));
  };

  function settings() {
    var box = document.getElementById("settings");
    AT.clear(box);
    var mode = el("select", { "aria-label": "Mode", onchange: function (e) { AT.setMode(e.target.value); AT.refreshHeader(); AT.route(); AT.restoreWallet().then(function (acc) { if (acc) { AT.refreshHeader(); AT.route(); } }); } },
      el("option", { value: "demo", selected: AT.state.mode === "demo" }, "Recorded demo (offline, read-only)"), el("option", { value: "live", selected: AT.state.mode === "live" }, "Live (deployed contract)"));
    var addr = el("input", { class: "mono", placeholder: "0x… deployed AgentTrust contract", value: AT.state.address, spellcheck: "false", "aria-label": "Contract address" });
    var msg = el("span", { class: "small", role: "status" });
    box.appendChild(el("div", { class: "settings" }, el("h2", {}, "Settings"),
      ui.field("Mode", mode),
      ui.field("Contract address", addr, "Used in Live mode. Set a default in assets/config.js."),
      el("div", { class: "row wrap" },
        el("button", { class: "btn", type: "button", onclick: function () {
          var v = addr.value.trim();
          if (v && !/^0x[0-9a-fA-F]{40}$/.test(v)) { msg.textContent = "That is not a valid address."; msg.className = "bad small"; return; }
          AT.setAddress(v); msg.textContent = "Saved."; msg.className = "ok small"; AT.route();
        } }, "Save address"),
        el("button", { class: "btn", type: "button", onclick: async function () {
          try { var a = await AT.connectWallet(); msg.textContent = "Connected " + a; msg.className = "ok small"; AT.refreshHeader(); AT.route(); }
          catch (e) { msg.textContent = e.message || String(e); msg.className = "bad small"; }
        } }, "Connect wallet"), msg),
      el("p", { class: "muted small" }, "Live mode uses genlayer-js createClient({ chain, account }) and an injected wallet. The recorded demo needs no wallet and no network.")));
  }

  function boot() {
    var skip = document.querySelector(".skip");
    if (skip) skip.addEventListener("click", function (e) { e.preventDefault(); document.getElementById("view").focus(); });
    document.getElementById("settingsbtn").addEventListener("click", function (e) {
      var box = document.getElementById("settings"), open = box.hidden;
      box.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open));
      if (open) settings();
    });
    if (!window.AgentTrustVerify) { document.getElementById("view").textContent = "The verifier failed to load."; return; }
    AT.refreshHeader();
    window.addEventListener("hashchange", AT.route);
    AT.route();
    AT.restoreWallet().then(function (acc) { if (acc) { AT.refreshHeader(); AT.route(); } });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})(window.AT);
