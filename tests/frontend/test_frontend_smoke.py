"""
Headless-browser smoke test of the static frontend in demo mode (skipped when Playwright or Chromium is missing).
Every route must render without console errors, without page-level horizontal scroll on a phone, with no untrusted
HTML injected, and the in-browser verifier must agree with the demo data.
    python3 -m unittest tests.frontend.test_frontend_smoke
    SHOTS=/tmp/shots python3 -m unittest tests.frontend.test_frontend_smoke   # also save screenshots
"""
import http.server
import os
import socketserver
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None

ROUTES = ["#/", "#/browse", "#/new", "#/mine", "#/jury", "#/verify", "#/verify/AT-1", "#/verify/AT-2",
          "#/a/AT-1", "#/a/AT-1/certificate", "#/a/AT-1/verification", "#/a/AT-1/requirement/REQ-002", "#/a/AT-1/dispute",
          "#/a/AT-2", "#/a/AT-2/certificate", "#/a/AT-2/verification", "#/a/AT-2/requirement/REQ-004", "#/a/AT-2/requirement/REQ-005", "#/a/AT-2/dispute",
          "#/a/AT-3", "#/a/AT-3/accept", "#/a/AT-3/fund", "#/a/AT-3/submit", "#/a/AT-4", "#/a/AT-4/fund", "#/a/AT-4/certificate"]


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@unittest.skipUnless(sync_playwright, "playwright is not installed")
class FrontendSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.join(ROOT, "frontend"))
        cls.httpd = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop()
            cls.httpd.shutdown()
            raise unittest.SkipTest("chromium unavailable: %s" % e)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def open(self, width, height):
        ctx = self.browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:%d/index.html" % self.port)
        page.wait_for_selector("#view .page, #view .notice")
        return ctx, page, errors

    def visit(self, page, route):
        page.evaluate("location.hash = %r" % route)
        page.wait_for_function("() => !document.querySelector('#view .loading')", timeout=8000)
        page.wait_for_timeout(50)

    def test_every_route_on_a_phone_and_a_desktop(self):
        shots = os.environ.get("SHOTS")
        if shots:
            os.makedirs(shots, exist_ok=True)
        for width, height, label in ((390, 844, "phone"), (1200, 900, "desktop")):
            ctx, page, errors = self.open(width, height)
            for route in ROUTES:
                self.visit(page, route)
                text = page.inner_text("#view")
                self.assertNotIn("Could not load", text, route)
                self.assertNotIn("Page not found", text, route)
                overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                self.assertLessEqual(overflow, 1, "%s: page scrolls horizontally by %spx at %s" % (route, overflow, label))
                if shots:
                    page.screenshot(path=os.path.join(shots, "%s-%s.png" % (label, route.replace("#/", "").replace("/", "_") or "home")), full_page=True)
            self.assertEqual(errors, [], label)
            ctx.close()

    def test_certificates_verify_in_the_browser(self):
        ctx, page, errors = self.open(1000, 800)
        for aid in ("AT-1", "AT-2"):
            self.visit(page, "#/a/%s/certificate" % aid)
            self.assertIn("CERTIFICATE VALID", page.inner_text("#view"))
        self.visit(page, "#/verify/AT-2")
        page.wait_for_selector(".verdictbanner")
        self.assertIn("CERTIFICATE VALID", page.inner_text(".verdictbanner"))
        page.click("text=Tamper with it")
        page.wait_for_selector(".verdictbanner.bad")
        self.assertIn("CERTIFICATE INVALID", page.inner_text(".verdictbanner"))
        self.assertEqual(errors, [])
        ctx.close()

    def test_state_machine_marks_the_current_state_and_reads_as_text(self):
        ctx, page, errors = self.open(1000, 800)
        self.visit(page, "#/a/AT-2")
        self.assertEqual(page.text_content(".sm .node.current text").strip(), "FINALIZED")
        self.assertEqual(page.locator(".sm .node").count(), 17)
        self.visit(page, "#/a/AT-3")
        self.assertEqual(page.text_content(".sm .node.current text").strip(), "FUNDED")
        self.assertIn("committed", page.inner_text(".strip-now").lower())
        self.visit(page, "#/a/AT-4")
        self.assertIn("draft", page.inner_text(".strip-now").lower())
        self.visit(page, "#/a/AT-1")
        self.assertIn("frozen", page.inner_text(".strip-now").lower())
        ctx.close()

    def test_browse_lists_all_agreements_and_filters(self):
        ctx, page, errors = self.open(1000, 800)
        self.visit(page, "#/browse")
        self.assertEqual(page.locator(".card").count(), 4)
        page.click(".chip:has-text('settled')")
        self.assertEqual(page.locator(".card").count(), 1)
        page.fill("input[type=search]", "second")
        self.assertEqual(page.locator(".card").count(), 0)
        ctx.close()

    def test_data_is_never_interpreted_as_html(self):
        ctx, page, errors = self.open(1000, 800)
        page.evaluate("""() => { window.AGENTTRUST_DEMO.agreements['AT-4'].agreement.title = '<img src=x onerror=window.__xss=1>'; AT.cache = {}; }""")
        self.visit(page, "#/browse")
        self.assertIn("<img src=x", page.inner_text("#view"))
        self.assertIsNone(page.evaluate("window.__xss"))
        ctx.close()

    def test_live_mode_without_an_address_explains_what_to_do(self):
        ctx, page, errors = self.open(390, 800)
        page.evaluate("AT.setMode('live'); AT.setAddress(''); AT.refreshHeader();")
        for route in ("#/browse", "#/a/AT-1", "#/mine"):
            self.visit(page, route)
            text = page.inner_text("#view")
            self.assertTrue("Settings" in text or "wallet" in text.lower(), route + ": " + text[:200])
        self.assertIn("live", page.inner_text("#modechip").lower())
        page.evaluate("AT.setMode('demo')")
        ctx.close()

    def test_write_buttons_are_disabled_in_the_read_only_demo(self):
        ctx, page, errors = self.open(1000, 800)
        self.visit(page, "#/a/AT-3/accept")
        self.assertTrue(page.locator("button:has-text('Accept and freeze')").is_disabled())
        self.visit(page, "#/new")
        self.assertTrue(page.locator("button:has-text('Create agreement')").is_disabled())
        ctx.close()


    def test_skip_link_focuses_content_without_breaking_the_route(self):
        ctx, page, errors = self.open(390, 800)
        self.visit(page, "#/browse")
        page.focus(".skip")
        page.keyboard.press("Enter")
        page.wait_for_timeout(100)
        self.assertNotIn("Page not found", page.inner_text("#view"))
        self.assertEqual(page.evaluate("location.hash"), "#/browse")
        self.assertEqual(errors, [])
        ctx.close()

    def test_every_nav_item_is_visible_on_a_phone(self):
        ctx, page, errors = self.open(360, 740)
        right = page.evaluate("Math.max(...Array.from(document.querySelectorAll('#nav a')).map(a => a.getBoundingClientRect().right))")
        self.assertLessEqual(right, 360)
        self.assertIn("Jury", page.inner_text("#nav"))
        ctx.close()

    def test_a_juror_reveals_the_vote_they_committed(self):
        ctx, page, errors = self.open(1000, 800)
        page.evaluate("""() => {
          const snap = JSON.parse(JSON.stringify(window.AGENTTRUST_DEMO.agreements['AT-2']));
          snap.agreement.status = 'FINAL_REVIEW';
          window.__sent = [];
          AT.snapshot = async () => JSON.parse(JSON.stringify(snap));
          AT.setMode('live');
          AT.state.account = snap.dispute.jurors[0].address;
          AT.tx = async (method, args) => { window.__sent.push([method, args]); return {}; };
          AT.store.set('vote.AT-2.' + AT.state.account, 'BUYER');
          AT.store.set('salt.AT-2.' + AT.state.account, 'secret-salt-1');
          AT.store.set('commit.AT-2.' + AT.state.account, AgentTrustVerify.sha('AT-2:' + AT.state.account + ':BUYER:secret-salt-1'));
        }""")
        self.visit(page, "#/a/AT-2/dispute")
        self.assertEqual(page.eval_on_selector("select[aria-label=Vote]", "s => s.value"), "BUYER")
        page.click("button:has-text('Reveal vote')")
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate("window.__sent"), [["reveal_vote", ["AT-2", "BUYER", "secret-salt-1"]]])
        page.select_option("select[aria-label=Vote]", "WORKER")
        page.click("button:has-text('Reveal vote')")
        page.wait_for_timeout(200)
        self.assertEqual(len(page.evaluate("window.__sent")), 1)
        self.assertIn("do not match what you committed", page.inner_text("#view"))
        ctx.close()

    def test_artifact_hash_evidence_rows_include_the_algorithm(self):
        ctx, page, errors = self.open(1000, 800)
        page.evaluate("""() => {
          const snap = JSON.parse(JSON.stringify(window.AGENTTRUST_DEMO.agreements['AT-3']));
          snap.agreement.status = 'IN_PROGRESS';
          window.__sent = [];
          AT.snapshot = async () => JSON.parse(JSON.stringify(snap));
          AT.setMode('live');
          AT.state.account = snap.agreement.worker;
          AT.tx = async (method, args) => { window.__sent.push([method, args]); return {}; };
        }""")
        self.visit(page, "#/a/AT-3/submit")
        page.fill("textarea[maxlength='2000']", "The release tarball is identified by its hash.")
        page.select_option("select[aria-label='Evidence kind']", "artifact_hash")
        page.fill("input[aria-label=hash]", "ab" * 32)
        page.fill("input[aria-label=description]", "release tarball v1")
        page.click("button:has-text('Submit deliverable')")
        page.wait_for_timeout(200)
        sent = page.evaluate("window.__sent")
        self.assertEqual(sent[0][0], "submit_deliverable")
        import json as _json
        item = _json.loads(sent[0][1][2])[0]
        self.assertEqual(sorted(item), ["algorithm", "description", "hash", "kind"])
        ctx.close()


if __name__ == "__main__":
    unittest.main()
