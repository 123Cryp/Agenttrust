#!/usr/bin/env python3
"""
Static pre-deployment checks for contracts/agenttrust.py (or another file).

    python3 scripts/deploy/check_contract.py [path]

Every rule below comes from a real GenLayer Studio or GenVM failure recorded in
the reference projects (SpecProof, VeriForge, JudgeChain, ModAppeal, ForesightVault):

  H1  line 1 is a version comment and line 2 is the pinned Depends runner line
  H2  ASCII only (Studio rejects some non-ASCII sources)
  H3  no comment other than those two lines and no docstring (comment volume made
      gen_getContractSchemaForCode fail with invalid_contract)
  A1  only gl.* attributes that have been used live are referenced
  A2  run_nondet_unsafe gets exactly two positional arguments
  A3  emit_transfer is called with value= only
  A4  module-level functions and their closures never touch `self` (a captured
      contract makes GenVM try to pickle storage)
  A5  no float literals, no true division, no datetime.min/max, no print
  A6  __init__ never assigns a TreeMap or DynArray field
  A7  a method that reads gl.message.value is decorated payable
  A8  every public method annotates every parameter and its return type
  A9  public methods never call other public methods
  A10 storage dataclass fields use only str, u256, Address, DynArray[str]
  A11 imports are limited to the ones proven live
"""
import ast
import io
import os
import re
import sys
import tokenize

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT = os.path.join(ROOT, "contracts", "agenttrust.py")
ALLOWED_GL = {
    ("Contract",), ("message", "sender_address"), ("message", "value"), ("public", "write"), ("public", "write", "payable"),
    ("public", "view"), ("nondet", "exec_prompt"), ("nondet", "web", "get"), ("nondet", "web", "render"),
    ("eq_principle", "strict_eq"), ("vm", "run_nondet_unsafe"), ("get_contract_at",),
}
ALLOWED_IMPORTS = {"hashlib", "json", "datetime", "re", "urllib.parse", "genlayer", "dataclasses"}
FIELD_TYPES = {"str", "u256", "Address", "DynArray[str]"}


def attr_chain(node):
    parts = []
    while isinstance(node, (ast.Attribute, ast.Call)):
        if isinstance(node, ast.Call):
            node = node.func
            continue
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def check(src):
    problems = []

    def bad(rule, msg, line=None):
        problems.append("%s%s %s" % (rule, (" line %d:" % line) if line else ":", msg))

    lines = src.split("\n")
    if not re.match(r"^# v\d+\.\d+\.\d+$", lines[0]):
        bad("H1", "line 1 must be a version comment such as '# v0.2.16'")
    if len(lines) < 2 or not (lines[1].startswith("# { \"Depends\": \"py-genlayer:") and lines[1].endswith("\" }")):
        bad("H1", "line 2 must be the pinned Depends runner line")
    if not src.isascii():
        bad("H2", "file contains non-ASCII characters")
    comments = [t for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.COMMENT]
    if {c.start[0] for c in comments} != {1, 2} or len(comments) != 2:
        bad("H3", "only the two header comment lines are allowed (found %d comments)" % len(comments))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                bad("H3", "docstring in %s" % getattr(node, "name", "module"), first.lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = attr_chain(node)
            if chain and chain[0] == "gl":
                sub = chain[1:]
                if not any(sub == a[:len(sub)] or sub[:len(a)] == a for a in ALLOWED_GL):
                    bad("A1", "unproven GenLayer attribute gl." + ".".join(sub), node.lineno)
        if isinstance(node, ast.Call):
            chain = attr_chain(node.func)
            if chain and chain[-1] == "run_nondet_unsafe":
                if len(node.args) != 2 or node.keywords:
                    bad("A2", "run_nondet_unsafe needs exactly two positional arguments", node.lineno)
            if chain and chain[-1] == "emit_transfer":
                if node.args or [k.arg for k in node.keywords] != ["value"]:
                    bad("A3", "emit_transfer must be called with value= only", node.lineno)
            if isinstance(node.func, ast.Name) and node.func.id in ("print", "float", "eval", "exec", "open", "input"):
                bad("A5", "forbidden call " + node.func.id, node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            bad("A5", "float literal", node.lineno)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            bad("A5", "true division; use //", node.lineno)
        if isinstance(node, ast.Attribute) and node.attr in ("min", "max") and attr_chain(node) and attr_chain(node)[0] == "datetime":
            bad("A5", "datetime.min/max sentinel", node.lineno)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == "self":
                    bad("A4", "module-level function %s references self" % node.name, sub.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for n in names:
                if n not in ALLOWED_IMPORTS:
                    bad("A11", "import of " + str(n), node.lineno)

    contracts = [n for n in tree.body if isinstance(n, ast.ClassDef) and any(attr_chain(b) == ("gl", "Contract") for b in n.bases)]
    if len(contracts) != 1:
        bad("A6", "exactly one gl.Contract subclass is expected")
    else:
        cls = contracts[0]
        storage = set()
        for n in cls.body:
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                ann = ast.unparse(n.annotation)
                if ann.startswith("TreeMap") or ann.startswith("DynArray"):
                    storage.add(n.target.id)
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

        def decorators(fn):
            return [".".join(attr_chain(d) or ()) for d in fn.decorator_list]

        public = {name for name, fn in methods.items() if any(d.startswith("gl.public") for d in decorators(fn))}
        init = methods.get("__init__")
        if init:
            for sub in ast.walk(init):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Attribute) and t.attr in storage:
                            bad("A6", "__init__ assigns storage field " + t.attr, sub.lineno)
        for name, fn in methods.items():
            reads_value = any(isinstance(s, ast.Attribute) and attr_chain(s) == ("gl", "message", "value") for s in ast.walk(fn))
            if reads_value and "gl.public.write.payable" not in decorators(fn):
                bad("A7", "%s reads gl.message.value but is not payable" % name, fn.lineno)
            if name in public:
                params = fn.args.args[1:]
                if any(p.annotation is None for p in params) or fn.returns is None:
                    bad("A8", "%s must annotate all parameters and the return type" % name, fn.lineno)
                for s in ast.walk(fn):
                    if isinstance(s, ast.Call) and attr_chain(s.func) and len(attr_chain(s.func)) == 2 and attr_chain(s.func)[0] == "self" and attr_chain(s.func)[1] in public:
                        bad("A9", "%s calls public method %s" % (name, attr_chain(s.func)[1]), s.lineno)

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(ast.unparse(d) in ("dataclass", "allow_storage") for d in node.decorator_list):
            for n in node.body:
                if isinstance(n, ast.AnnAssign) and ast.unparse(n.annotation) not in FIELD_TYPES:
                    bad("A10", "storage field %s.%s has type %s" % (node.name, ast.unparse(n.target), ast.unparse(n.annotation)), n.lineno)
    return problems


def main(argv):
    path = argv[0] if argv else DEFAULT
    problems = check(open(path, encoding="utf-8").read())
    for p in problems:
        print("FAIL", p)
    if problems:
        return 1
    print("ok: %s passes all %d rule groups (%d bytes)" % (os.path.relpath(path, ROOT), 14, os.path.getsize(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
