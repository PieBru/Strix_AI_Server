#!/usr/bin/env python3
"""The storm badge must name the process, not just the bytes.

Why this exists (261001): the 10:58 storm showed "peak 1074 MB/s · 30.2 GiB moved" and left
the operator to work out WHO did it (it was the LTX CPU render, killed by the OOM killer at
11:02). Attribution is VmSwap GROWTH since the trip, so a tenant already sitting on 6 GiB of
swap that never moves is not blamed for somebody else's storm.

    uv run --offline --no-project python tests/storm_culprit_check.py
"""
import os
import pathlib
import sys
import tempfile
import types

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = str(REPO / "doctor" / "Doctor.py")
# compile from source: a .pyc is validated by (mtime, size), so a same-second sabotage
# restore of the same length re-runs stale bytecode (measured 261001).
D = types.ModuleType("storm_culprit_under_test")
D.__file__ = SRC
exec(compile(open(SRC, encoding="utf-8").read(), SRC, "exec"), D.__dict__)

D.STORM_FILE = str(pathlib.Path(tempfile.mkdtemp()) / "storm.json")
P0 = (1_000_000, 2_000_000)
HI = D.STORM_MBPS * 10
GI = 1048576                      # kB in a GiB

TENANT = {"700": ("idle-tenant", 6 * GI)}          # 6 GiB already swapped, never grows
HOG = {"700": ("idle-tenant", 6 * GI), "900": ("ltx2-gen", 30 * GI)}


def reset():
    D.STORM.clear()
    D._SW["hits"] = 0


def trip(snap):
    for i in range(D.STORM_N):
        D.storm_tick(HI, (P0[0], P0[1] + 4096 * (i + 1)), snap)


def check_names_the_grower_not_the_resident():
    reset()
    trip(lambda: TENANT)
    assert D.STORM.get("t0"), "storm should be latched"
    D.storm_tick(HI, (P0[0], P0[1] + 4096 * 10), lambda: HOG)
    assert D.STORM.get("who") == "ltx2-gen", f"named {D.STORM.get('who')!r}, want the grower"
    assert abs(D.STORM["who_kb"] / GI - 30) < 0.01, f"grew {D.STORM['who_kb']/GI:.2f} GiB, want 30"


def check_blames_nobody_when_nothing_grows():
    reset()
    trip(lambda: TENANT)
    D.storm_tick(HI, (P0[0], P0[1] + 4096 * 10), lambda: TENANT)
    assert "who" not in D.STORM, f"blamed {D.STORM.get('who')!r} for a storm nobody grew"


def check_a_broken_snapshot_cannot_kill_the_latch():
    reset()
    def boom():
        raise OSError("proc walked into a wall")
    trip(boom)
    D.storm_tick(HI, (P0[0], P0[1] + 4096 * 10), boom)
    assert D.STORM.get("t0"), "latch must survive a failing /proc read"
    assert "who" not in D.STORM


if __name__ == "__main__":
    fails = 0
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("check_")]:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if fails else 0)
