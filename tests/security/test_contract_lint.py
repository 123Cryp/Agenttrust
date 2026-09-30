import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
spec = importlib.util.spec_from_file_location("check_contract", os.path.join(ROOT, "scripts", "deploy", "check_contract.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

HEADER = '# v0.2.16\n# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }\n'
GOOD = HEADER + '''from genlayer import *
from dataclasses import dataclass


class C(gl.Contract):
    items: TreeMap[str, u256]

    def __init__(self):
        self.n = u256(0)

    @gl.public.view
    def get(self, key: str) -> int:
        return 1
'''


def rules(src):
    return sorted({p.split()[0].rstrip(":") for p in cc.check(src)})


class ContractLintTests(unittest.TestCase):
    def test_the_real_contract_is_clean(self):
        with open(os.path.join(ROOT, "contracts", "agenttrust.py"), encoding="utf-8") as f:
            self.assertEqual(cc.check(f.read()), [])

    def test_the_two_line_header_is_the_first_thing_in_the_file(self):
        with open(os.path.join(ROOT, "contracts", "agenttrust.py"), encoding="utf-8") as f:
            lines = f.read().split("\n")
        self.assertRegex(lines[0], r"^# v0\.2\.16$")
        self.assertIn('"Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6"', lines[1])

    def test_the_lint_accepts_a_minimal_good_contract(self):
        self.assertEqual(cc.check(GOOD), [])

    def test_the_lint_catches_each_known_failure_mode(self):
        cases = {
            "H1": GOOD.replace("# v0.2.16\n", "# something\n"),
            "H2": GOOD + "X = '\u00e9'\n",
            "H3": GOOD + "# a long comment\n",
            "A1": GOOD.replace("return 1", "return gl.storage.inmem_allocate(1)"),
            "A2": GOOD.replace("return 1", "return gl.vm.run_nondet_unsafe(leader_fn=f, validator_fn=g)"),
            "A3": GOOD.replace("return 1", "return gl.get_contract_at(a).emit_transfer(value=1, on='accepted')"),
            "A4": GOOD + "\n\ndef helper():\n    return self.x\n",
            "A5": GOOD.replace("return 1", "return 1 / 2"),
            "A6": GOOD.replace("self.n = u256(0)", "self.items = {}"),
            "A7": GOOD.replace("return 1", "return int(gl.message.value)"),
            "A8": GOOD.replace("key: str", "key"),
            "A10": GOOD + "\n\n@allow_storage\n@dataclass\nclass R:\n    a: int\n",
            "A11": GOOD.replace("from genlayer import *", "import os\nfrom genlayer import *"),
        }
        for rule, src in cases.items():
            self.assertIn(rule, rules(src), rule)

    def test_docstrings_are_flagged(self):
        self.assertIn("H3", rules(GOOD.replace("        return 1", '        """doc"""\n        return 1')))

    def test_public_methods_may_not_call_each_other(self):
        src = GOOD + "\n    @gl.public.view\n    def other(self) -> int:\n        return self.get('a')\n"
        self.assertIn("A9", rules(src))

    def test_datetime_min_is_flagged(self):
        self.assertIn("A5", rules(GOOD.replace("return 1", "return datetime.datetime.min")))


class ShortWindowBuildTests(unittest.TestCase):
    def test_build_changes_exactly_the_window_unit(self):
        import subprocess
        import sys
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "deploy", "build_short_window.py"), "60"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(os.path.join(ROOT, "build", "agenttrust_short_window.py"), encoding="utf-8") as f:
            built = f.read()
        with open(os.path.join(ROOT, "contracts", "agenttrust.py"), encoding="utf-8") as f:
            real = f.read()
        diff = [(a, b) for a, b in zip(real.split("\n"), built.split("\n")) if a != b]
        self.assertEqual(diff, [("WINDOW_UNIT = 3600", "WINDOW_UNIT = 60")])
        self.assertEqual(cc.check(built), [])


if __name__ == "__main__":
    unittest.main()
