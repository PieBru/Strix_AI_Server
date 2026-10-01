#!/usr/bin/env python3
"""The GPU power card must not call ordinary inference an alarm.

Why this exists (261001): the card used the generic watts-as-percent heat(), which clamps at
100 and returns hue 0, so a perfectly normal 105 W inference pass rendered the bar AND the
peak chip red - "a permanently red card is not an alarm, it is the loss of one" (the repo's
own words about gpu_busy_percent). The operator's line: red only above the 110-120 W band.
Peak chips are shown from hue <= 60 up, so yellow is the first thing that ever appears.

    uv run --offline --no-project python tests/power_zones_check.py
"""
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "doctor", "Doctor.py")
# Compiled from source, NOT SourceFileLoader: a .pyc is validated by (source mtime, size),
# and a sabotage edit that swaps digits keeps the size identical. Restore the file inside the
# same second as the break and the loader happily re-runs the stale bytecode (measured
# 261001: the sabotage "passed" the restore check). No cache, no lie.
mod = types.ModuleType("d")
mod.__file__ = SRC
exec(compile(open(SRC, encoding="utf-8").read(), SRC, "exec"), mod.__dict__)


def hue(w):
    m = re.match(r"hsl\(([\d.]+)", mod.heat_power(w))
    assert m, f"heat_power({w}) returned a non-hsl colour: {mod.heat_power(w)!r}"
    return float(m.group(1))


def shown(w):
    """Would pchip() paint this peak at all? (it hides anything greener than hue 60)."""
    return hue(w) <= 60


bad = []
for w, want in [(42.8, 120), (99, 120), (105, 120), (109, 120), (110, 45), (118, 45), (119, 0), (124, 0)]:
    got = hue(w)
    if got != want:
        bad.append(f"{w} W -> hue {got}, want {want}")

# 105 W is the number the operator quoted as normal: it must be invisible, not red.
if shown(105):
    bad.append("a 105 W peak is still shown as an alarm")
if not shown(119):
    bad.append("a 119 W peak is not flagged")
# The bar ceiling is the 140 W chassis rating: 70 W is half the bar, not a full one.
if not (0.45 < (70 / 140) < 0.55):
    bad.append("bar ceiling is not the 140 W chassis rating")

print("FAIL " + "; ".join(bad) if bad else "power zones: green<110, yellow to 118, red beyond")
sys.exit(1 if bad else 0)
