#!/usr/bin/env python3
"""
Writes build/agenttrust_short_window.py: the contract with every protocol window
(freeze, verify, challenge, dispute, response, commit, reveal) shortened so the
whole dispute path can be exercised on GenLayer Studio in minutes.

    python3 scripts/deploy/build_short_window.py [seconds_per_unit]   # default 60

The only change is the WINDOW_UNIT constant (3600 -> N). Test networks only: never
deploy the short-window build with real funds. The build refuses to write unless the
diff against contracts/agenttrust.py is exactly that one line.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "contracts", "agenttrust.py")
OUT = os.path.join(ROOT, "build", "agenttrust_short_window.py")


def main(argv):
    unit = int(argv[0]) if argv else 60
    if unit < 1 or unit >= 3600:
        raise SystemExit("seconds_per_unit must be between 1 and 3599")
    src = open(SRC, encoding="utf-8").read()
    old = "WINDOW_UNIT = 3600\n"
    if src.count(old) != 1:
        raise SystemExit("WINDOW_UNIT line not found exactly once")
    out = src.replace(old, "WINDOW_UNIT = %d\n" % unit)
    diff = [(a, b) for a, b in zip(src.split("\n"), out.split("\n")) if a != b]
    if len(diff) != 1:
        raise SystemExit("unexpected diff")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(out)
    print("wrote %s with WINDOW_UNIT = %d (1 protocol hour = %d seconds)" % (os.path.relpath(OUT, ROOT), unit, unit))


if __name__ == "__main__":
    main(sys.argv[1:])
