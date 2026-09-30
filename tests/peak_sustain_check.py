#!/usr/bin/env python3
"""Card peaks must be sustained, not touched.

Why (260930): the high-water mark was a plain max over samples, so one 2 s reading of a
transient put a chip on a card for the rest of the day. The rule now mirrors the
swap-storm latch — N consecutive samples are a state, one sample is a spike — and the
recorded level is min(window), i.e. the level that actually held across the window.

    uv run --no-project python tests/peak_sustain_check.py
"""
import importlib.machinery
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
loader = importlib.machinery.SourceFileLoader("d", os.path.join(ROOT, "doctor", "Doctor.py"))
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("d", loader))
sys.modules["d"] = mod
loader.exec_module(mod)

N = mod.PEAK_N
assert N >= 2, "PEAK_N must require more than one sample"

# 1. a spike never becomes the peak, and does not even pause the sustained level
for v in (10, 10, 90, 10, 10):
    mod.track("spike", v)
assert mod.PEAKS["spike"]["v"] == 10, mod.PEAKS["spike"]

# 2. a real plateau converges on its true level, one window late
for v in (20, 20, 20):
    mod.track("plateau", v)
assert mod.PEAKS["plateau"]["v"] == 20, mod.PEAKS["plateau"]
mod.track("plateau", 50)
mod.track("plateau", 50)
assert mod.PEAKS["plateau"]["v"] == 20, "rose before the window was full"
mod.track("plateau", 50)
assert mod.PEAKS["plateau"]["v"] == 50, mod.PEAKS["plateau"]

# 3. a ramp records the floor it held, not the top it touched
mod.track("ramp", 30); mod.track("ramp", 40); mod.track("ramp", 50)
assert mod.PEAKS["ramp"]["v"] == 30, mod.PEAKS["ramp"]

# 4. reset clears the window too, so the ↺ is not immediately re-armed by a held level
mod.PEAKS.pop("plateau"); mod._HIST.pop("plateau")
mod.track("plateau", 70)
assert "plateau" not in mod.PEAKS, "reset did not clear the window"

# 5. non-numeric input is ignored, not stored as a peak
mod.track("junk", None); mod.track("junk", "—")
assert "junk" not in mod.PEAKS, mod.PEAKS.get("junk")

print(f"peak_sustain_check: PASS — spike suppressed, plateau held at PEAK_N={N}")
