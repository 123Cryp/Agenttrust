import json
import unittest

from scenario import *

SHA_A = "a" * 40
SHA_B = "b" * 40


def gh(path, commit=COMMIT_V1):
    return {"kind": "github_file", "repository": REPO, "commit": commit, "path": path}


class EvidenceParsingTests(unittest.TestCase):
    def parse(self, items, policy="STRICT"):
        return at._parse_evidence(json.dumps(items), policy)

    def bad(self, items, fragment, policy="STRICT"):
        expect_raises(lambda: self.parse(items, policy), fragment)

    def test_branch_names_are_rejected_with_an_explanation(self):
        for ref in ("main", "master", "v1.0.0", "HEAD", "refs/heads/main", "abc1234", "1" * 39, "1" * 41, "g" * 40):
            self.bad([gh("a.py", ref)], "40-character")

    def test_uppercase_sha_is_normalised(self):
        items = self.parse([gh("a.py", "A" * 40)])
        self.assertEqual(items[0]["params"]["commit"], "a" * 40)

    def test_repository_must_be_plain_github(self):
        for repo in ("http://github.com/o/r", "https://gitlab.com/o/r", "https://github.com/o", "https://github.com/o/r/tree/main",
                     "https://github.com/o/r?x=1", "https://github.com/o/r#frag", "https://github.com:443@evil.example/o/r",
                     "https://user@github.com/o/r", "https://github.com/../r"):
            item = dict(gh("a.py"), repository=repo)
            self.bad([item], "repository")

    def test_path_traversal_and_odd_paths(self):
        for path in ("../secret", "/etc/passwd", "a//b", "a/../b", "./a", "", "a b", "a?x=1", "a#b", "x" * 201):
            self.bad([gh(path)], "path")

    def test_duplicate_reference_rejected(self):
        self.bad([gh("a.py"), gh("a.py")], "duplicate evidence reference")

    def test_same_file_at_different_commits_is_not_a_duplicate(self):
        self.assertEqual(len(self.parse([gh("a.py", SHA_A), gh("a.py", SHA_B)])), 2)

    def test_malformed_containers(self):
        expect_raises(lambda: at._parse_evidence("not json", "STRICT"), "JSON list")
        expect_raises(lambda: at._parse_evidence("{}", "STRICT"), "list of 1 to")
        expect_raises(lambda: at._parse_evidence("[]", "STRICT"), "list of 1 to")
        expect_raises(lambda: at._parse_evidence("[1]", "STRICT"), "must be an object")
        self.bad([{"kind": "telepathy"}], "unknown evidence kind")
        self.bad([dict(gh("a.py"), extra=1)], "exactly")

    def test_too_many_items(self):
        self.bad([gh("f%d.py" % i) for i in range(at.MAX_EVIDENCE_ITEMS + 1)], "list of 1 to")

    def test_url_policy(self):
        item = {"kind": "url", "url": "https://example.org/report.json"}
        self.bad([item], "STRICT", "STRICT")
        parsed = self.parse([item], "PERMISSIVE")
        self.assertEqual(parsed[0]["mutable"], 1)

    def test_url_hardening(self):
        for url in ("http://example.org/x", "https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.1/x",
                    "https://intranet/x", "https://a.local/x", "https://user:pw@example.org/x", "https://example.org/x#frag",
                    "https://example.org/" + "x" * 500, "ftp://example.org/x", "javascript:alert(1)"):
            self.bad([{"kind": "url", "url": url}], "url", "PERMISSIVE")

    def test_text_artifact_and_tx_kinds(self):
        good = [{"kind": "text", "text": "Load test summary: 1200 requests, p95 latency 80 ms."},
                {"kind": "artifact_hash", "algorithm": "sha256", "hash": "ab" * 32, "description": "release tarball"},
                {"kind": "tx_reference", "chain": "genlayer-studio", "tx": "0x" + "12" * 32}]
        parsed = self.parse(good)
        self.assertEqual([p["mutable"] for p in parsed], [0, 0, 0])
        self.bad([{"kind": "text", "text": "short"}], "text evidence")
        self.bad([{"kind": "artifact_hash", "algorithm": "md5", "hash": "ab" * 32, "description": "release tarball"}], "sha256")
        self.bad([{"kind": "artifact_hash", "algorithm": "sha256", "hash": "zz" * 32, "description": "release tarball"}], "64 hex")
        self.bad([{"kind": "tx_reference", "chain": "x", "tx": "0x" + "12" * 32}], "chain")
        self.bad([{"kind": "tx_reference", "chain": "genlayer-studio", "tx": "0x12"}], "transaction hash")

    def test_pr_number_validation(self):
        for pr in (0, -1, "7", 1.5, True, 10 ** 10):
            self.bad([{"kind": "github_pr", "repository": REPO, "pr": pr, "head": COMMIT_V2}], "pr must be")
        self.bad([{"kind": "github_pr", "repository": REPO, "pr": 7}], "needs exactly kind, repository, pr, head")
        self.bad([{"kind": "github_pr", "repository": REPO, "pr": 7, "head": "main"}], "40-character")


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.chain, self.llm = new_chain()
        self.aid = create(self.chain)
        to_delivered(self.chain, self.aid)
        self.web = gl.nondet.web

    def freeze(self, who=WORKER):
        return freeze_all(self.chain, self.aid, who)

    def test_freeze_stores_content_and_hashes(self):
        root = self.freeze()
        a = self.chain.agreement(self.aid)
        self.assertEqual(a["status"], "VERIFICATION_PENDING")
        self.assertEqual(a["evidence_root"], root)
        bundle = self.chain.view("get_evidence_bundle", self.aid)
        self.assertEqual([b["item_id"] for b in bundle], ["E1", "E2"])
        self.assertEqual(bundle[0]["content"], APP_V1)
        self.assertEqual(bundle[0]["content_hash"], at._sha(APP_V1))
        self.assertEqual(bundle[0]["mutable"], 0)

    def test_buyer_may_freeze_stranger_may_not(self):
        expect_raises(lambda: self.freeze(STRANGER), "only a party")
        self.freeze(BUYER)
        self.assertEqual(self.chain.status(self.aid), "VERIFICATION_PENDING")

    def test_missing_page_blocks_only_its_own_item(self):
        del self.web.pages[RAW + COMMIT_V1 + "/src/auth.py"]
        self.assertEqual(self.chain.tx(WORKER, "freeze_evidence", self.aid), "FROZEN 1/2")
        expect_raises(self.freeze)
        self.assertEqual(self.chain.status(self.aid), "DELIVERED")
        self.assertEqual(self.chain.agreement(self.aid)["evidence_root"], "")
        self.assertEqual([b["item_id"] for b in self.chain.view("get_evidence_bundle", self.aid)], ["E1"])
        self.web.pages[RAW + COMMIT_V1 + "/src/auth.py"] = AUTH
        self.freeze()
        self.assertEqual(self.chain.status(self.aid), "VERIFICATION_PENDING")

    def test_http_error_is_a_failure(self):
        self.web.statuses[RAW + COMMIT_V1 + "/src/app.py"] = 404
        expect_raises(self.freeze, "HTTP 404")
        self.assertEqual(self.chain.status(self.aid), "DELIVERED")

    def test_a_retry_after_a_transient_failure_succeeds(self):
        self.web.statuses[RAW + COMMIT_V1 + "/src/app.py"] = 503
        expect_raises(self.freeze)
        del self.web.statuses[RAW + COMMIT_V1 + "/src/app.py"]
        self.freeze()
        self.assertEqual(self.chain.status(self.aid), "VERIFICATION_PENDING")

    def test_a_moving_source_breaks_consensus(self):
        self.web.pages[RAW + COMMIT_V1 + "/src/app.py"] = Sequence(APP_V1, APP_V1 + "# changed\n", APP_V1 + "# again\n")
        expect_raises(self.freeze, "consensus not reached")
        self.assertEqual(self.chain.status(self.aid), "DELIVERED")

    def test_duplicate_content_under_different_references_is_rejected(self):
        chain, _ = new_chain()
        aid = create(chain)
        gl.nondet.web.pages[RAW + COMMIT_V1 + "/src/copy.py"] = APP_V1
        to_delivered(chain, aid, evidence_json(COMMIT_V1, ["src/app.py", "src/copy.py"]))
        expect_raises(lambda: freeze_all(chain, aid), "duplicate evidence content")

    def test_empty_and_oversized_content_rejected(self):
        self.web.pages[RAW + COMMIT_V1 + "/src/auth.py"] = "   \n"
        expect_raises(self.freeze, "empty evidence")
        self.web.pages[RAW + COMMIT_V1 + "/src/auth.py"] = "x" * (at.MAX_ITEM_CHARS + 1)
        expect_raises(self.freeze, "larger than")
        self.assertEqual(self.chain.status(self.aid), "DELIVERED")

    def test_total_size_limit(self):
        chain, _ = new_chain()
        for name, ch in (("app", "a"), ("auth", "b"), ("c", "c"), ("d", "d")):
            gl.nondet.web.pages[RAW + COMMIT_V1 + "/src/" + name + ".py"] = ch * at.MAX_ITEM_CHARS
        aid = create(chain)
        to_delivered(chain, aid, evidence_json(COMMIT_V1, ["src/app.py", "src/auth.py", "src/c.py", "src/d.py"]))
        expect_raises(lambda: freeze_all(chain, aid), "total evidence")

    def test_freeze_window(self):
        self.chain.advance(at.FREEZE_WINDOW + 1)
        expect_raises(self.freeze, "deadline has passed")

    def test_freezing_twice_is_impossible(self):
        self.freeze()
        expect_raises(lambda: self.chain.tx(WORKER, "freeze_evidence", self.aid), "invalid state")

    def test_deliverable_cannot_be_resubmitted_or_replaced(self):
        expect_raises(lambda: self.chain.tx(WORKER, "submit_deliverable", self.aid, "A second statement long enough.", default_evidence(COMMIT_V2)), "invalid state")
        self.freeze()
        expect_raises(lambda: self.chain.tx(WORKER, "submit_deliverable", self.aid, "A third statement long enough.", default_evidence(COMMIT_V2)), "invalid state")
        self.assertEqual(self.chain.view("get_evidence_bundle", self.aid)[0]["content"], APP_V1)

    def test_diff_and_pr_evidence(self):
        chain, _ = new_chain()
        aid = create(chain)
        diff = "diff --git a/x.py b/x.py\n+++ b/x.py\n+print('hi')\n"
        web = gl.nondet.web
        web.pages["https://github.com/acme-agent/user-api/commit/" + COMMIT_V1 + ".diff"] = diff
        web.pages["https://api.github.com/repos/acme-agent/user-api/pulls/7"] = json.dumps(
            {"base": {"sha": SHA_A}, "head": {"sha": COMMIT_V2}})
        web.pages["https://github.com/acme-agent/user-api/compare/" + SHA_A + "..." + COMMIT_V2 + ".diff"] = diff + "+more\n"
        to_delivered(chain, aid, json.dumps([{"kind": "github_diff", "repository": REPO, "commit": COMMIT_V1},
                                            {"kind": "github_pr", "repository": REPO, "pr": 7, "head": COMMIT_V2}]))
        freeze_all(chain, aid)
        bundle = chain.view("get_evidence_bundle", aid)
        self.assertTrue(bundle[0]["source"].endswith("#diff"))
        self.assertIn("@" + COMMIT_V2 + "#pr7", bundle[1]["source"])

    def test_a_non_diff_page_is_rejected_as_a_diff(self):
        chain, _ = new_chain()
        aid = create(chain)
        gl.nondet.web.pages["https://github.com/acme-agent/user-api/commit/" + COMMIT_V1 + ".diff"] = "<html>not a diff</html>"
        to_delivered(chain, aid, json.dumps([{"kind": "github_diff", "repository": REPO, "commit": COMMIT_V1}]))
        expect_raises(lambda: freeze_all(chain, aid), "not a unified diff")

    def test_text_and_hash_evidence_freeze_without_network(self):
        chain, _ = new_chain()
        aid = create(chain)
        to_delivered(chain, aid, json.dumps([{"kind": "text", "text": "Benchmark output: 1200 rps sustained for 60 seconds."},
                                            {"kind": "artifact_hash", "algorithm": "sha256", "hash": "cd" * 32, "description": "release tarball"}]))
        freeze_all(chain, aid)
        self.assertEqual(len(chain.view("get_evidence_bundle", aid)), 2)

    def test_a_moved_pull_request_head_is_refused(self):
        chain, _ = new_chain()
        aid = create(chain)
        web = gl.nondet.web
        web.pages["https://api.github.com/repos/acme-agent/user-api/pulls/7"] = json.dumps(
            {"base": {"sha": SHA_A}, "head": {"sha": COMMIT_V1}})
        to_delivered(chain, aid, json.dumps([{"kind": "github_pr", "repository": REPO, "pr": 7, "head": COMMIT_V2}]))
        expect_raises(lambda: freeze_all(chain, aid), "head moved")

    def test_url_evidence_is_rendered_text_truncated_to_the_item_limit(self):
        chain, _ = new_chain()
        aid = create(chain, evidence="PERMISSIVE")
        gl.nondet.web.pages["https://example.org/big"] = "  " + "x" * (at.MAX_ITEM_CHARS + 500)
        to_delivered(chain, aid, json.dumps([{"kind": "url", "url": "https://example.org/big"}]))
        freeze_all(chain, aid)
        item = chain.view("get_evidence_bundle", aid)[0]
        self.assertEqual(item["length"], at.MAX_ITEM_CHARS)
        self.assertIn(("render", "https://example.org/big"), gl.nondet.web.calls)

    def test_permissive_url_evidence_is_flagged_mutable(self):
        chain, _ = new_chain()
        aid = create(chain, evidence="PERMISSIVE")
        gl.nondet.web.pages["https://example.org/report.json"] = '{"uptime": "99.9"}'
        to_delivered(chain, aid, json.dumps([{"kind": "url", "url": "https://example.org/report.json"}]))
        freeze_all(chain, aid)
        self.assertEqual(chain.view("get_evidence_bundle", aid)[0]["mutable"], 1)


if __name__ == "__main__":
    unittest.main()
