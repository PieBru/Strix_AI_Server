#!/usr/bin/env python3
"""Self-test for scripts/strix-watchdog.py — the ladder is pure, so the whole policy is
testable without a box: `uv run --no-project python tests/watchdog_check.py`.

Sabotage: make `decide` return "ok" whenever the probe fails (the classic watchdog bug —
it reports and never acts) and check_a_failed_arm_escalates must fail.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile

loader = importlib.machinery.SourceFileLoader(
    "wd", str(pathlib.Path(__file__).resolve().parent.parent / "scripts" / "strix-watchdog.py"))
spec = importlib.util.spec_from_loader("wd", loader)
wd = importlib.util.module_from_spec(spec)
loader.exec_module(wd)


def D(**kw):
    """decide() with everything benign unless the test says otherwise."""
    base = dict(disabled=False, stamp="lab-video", probe_ok=False, failures=wd.N_TRIP,
                cooldown_left=0, slow_but_busy=False, tier=0, tier_hits=0)
    base.update(kw)
    return wd.decide(**base)


def check_a_healthy_arm_and_a_parked_box_do_nothing():
    assert D(probe_ok=True) == ("ok", None)
    assert D(stamp=None) == ("ignore", "no stamp — the box is parked by hand, that is not our contract")
    assert D(disabled=True)[0] == "ignore"
    assert D(failures=1)[0] == "watch", "one miss is not an outage"


def check_a_failed_arm_escalates_in_order():
    assert D()[0] == "restart", "tier 1 is the cheapest thing that might work"
    assert D(tier=1)[0] == "emergency"
    assert D(tier=2)[0] == "panic"
    assert D(tier=3)[0] == "shout"
    assert D(tier=9)[0] == "shout", "a state file from the future must not index out of range"


def check_slow_is_not_dead_and_cooldown_is_respected():
    a, r = D(slow_but_busy=True)
    assert a == "wait" and "slow is not dead" in r, (a, r)
    a, r = D(cooldown_left=600)
    assert a == "wait" and "600" in r, (a, r)
    # busy alone is not enough: no listener means the arm is gone, not slow
    assert D(slow_but_busy=False)[0] == "restart"


def check_reaching_a_tier_too_often_stops_acting():
    a, r = D(tier_hits=wd.MAX_TIER_PER_DAY)
    assert a == "shout" and "structural" in r, (a, r)


def check_a_measured_fail_is_never_forced():
    class Sp:
        def __init__(self, v): self.v = v
        def _gate_verdict(self, b, p): return self.v

    assert wd.refused_by_evidence("emergency", Sp({"verdict": "FAIL"})) is True
    assert wd.refused_by_evidence("emergency", Sp({"verdict": "PASS"})) is False
    assert wd.refused_by_evidence("panic", Sp(None)) is False, "absence of evidence is forceable"
    assert wd.refused_by_evidence("panic", Sp({"verdict": "INCONCLUSIVE"})) is False


def check_state_round_trips_and_resets_on_the_day():
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "watchdog.json"
    st = wd.read_state(p)
    assert st["failures"] == 0 and st["tier"] == 0
    st["tier"], st["actions"] = 2, 5
    wd.write_state(st, p)
    back = json.loads(p.read_text())
    assert back["tier"] == 2 and back["actions"] == 5, back
    back["day"] = "19700101"
    wd.write_state(back, p)
    assert wd.read_state(p)["tier"] == 0, "yesterday's escalation must not be today's"
    p.write_text("{ not json")
    assert wd.read_state(p)["failures"] == 0, "a corrupt state file must not crash the tick"


def main():
    for fn in [check_a_healthy_arm_and_a_parked_box_do_nothing,
               check_a_failed_arm_escalates_in_order,
               check_slow_is_not_dead_and_cooldown_is_respected,
               check_reaching_a_tier_too_often_stops_acting,
               check_a_measured_fail_is_never_forced,
               check_state_round_trips_and_resets_on_the_day]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
