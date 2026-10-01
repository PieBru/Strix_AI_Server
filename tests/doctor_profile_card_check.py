"""Runnable check for the profile UI in doctor/Doctor.py.

    uv run --no-project python tests/doctor_profile_card_check.py

The three pieces are pure functions on purpose: the dropdown markup, the ARM-card line, and the
POST handler's validation. Only the wiring touches the socket, and the handler is tested with an
injected `spawn` so a test can never start a unit.
"""
import importlib.machinery
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


D = _load("doctor_under_test", REPO / "doctor" / "Doctor.py")

GATE = {"verdict": "PASS", "age_h": 6.0, "peak_gtt_pct": 84.2, "started": "260930T11:02:11+02:00"}


def check_profile_line_shows_claim_truth_and_gate():
    h = D.profile_line_html("lab-video", missing=["comfyui-h3"], extra=[], gate=GATE)
    assert "lab-video" in h and "PASS" in h and "DRIFT" in h and "comfyui-h3" in h, h
    assert "84.2" in h and "260930" in h, h


def check_profile_line_is_clean_when_there_is_nothing_to_say():
    h = D.profile_line_html("coding", missing=[], extra=[], gate=GATE)
    assert "DRIFT" not in h and "coding" in h and "PASS" in h, h


def check_a_gate_that_is_gone_or_old_is_said_out_loud():
    # no gate evidence at all is the common case, and "we never proved this" must not read as ok
    h = D.profile_line_html("coding", missing=[], extra=[], gate=None)
    assert "coding" in h and "never gated" in h, h
    h = D.profile_line_html("coding", missing=[], extra=[],
                            gate={"verdict": "FAIL", "age_h": 1.0, "peak_gtt_pct": 95.0,
                                  "started": "260930T11:02:11+02:00",
                                  "reasons": ["swap written 45.4 MiB"]})
    assert "FAIL" in h and "bad" in h, h


def check_names_are_escaped_not_executed():
    # no auth on this LAN: the profile name comes from a file someone else could edit
    h = D.profile_line_html('<script>alert(1)</script>', missing=["<b>x</b>"], extra=[],
                            gate=GATE)
    assert "<script" not in h and "&lt;script&gt;" in h, h
    assert "<b>x</b>" not in h, h


def check_no_stamp_says_so_exactly_once():
    h = D.profile_line_html(None, missing=[], extra=[], gate=GATE)
    assert h.count("no profile") == 1, h


def check_select_marks_current_and_always_offers_the_way_out():
    h = D.profile_select_html(["coding", "lab-video"], "lab-video")
    assert 'id="prof"' in h and 'value="coding"' in h, h
    assert h.count("selected") == 1 and 'value="lab-video" selected' in h, h
    # panic must survive a wiped profiles dir: it is the escape hatch, not a preference
    h = D.profile_select_html([], "coding")
    assert 'value="panic"' in h and 'value="emergency"' in h, h


def check_a_stamp_that_is_not_in_the_list_shows_placeholder():
    # The row must never claim a profile nobody applied by falling back to option #1.
    h = D.profile_select_html(["coding"], "lab-video")
    assert h.count("selected") == 1 and "selected disabled>---" in h, h
    assert 'value="coding" selected' not in h, h


def check_the_first_paint_of_the_chip_cannot_lie():
    # Chrome restores a <select>'s previous selection over `selected` on reload, so `/`
    # must paint something with nothing to restore (operator 261001: "panic" on refresh).
    assert "---" in D.PROF_PLACEHOLDER and "value=" not in D.PROF_PLACEHOLDER, D.PROF_PLACEHOLDER
    assert 'id="prof"' in D.PROF_PLACEHOLDER, "the placeholder must be the same chip shape"


def check_apply_validates_before_anything_is_spawned():
    calls = []
    known = {"coding", "lab-video", "panic", "emergency"}
    for bad in ["/profile?name=../../etc/passwd", "/profile?name=;rm -rf /", "/profile?name=",
                "/profile", "/profile?name=CODING", "/profile?name=coding%0asec"]:
        code, body = D.profile_apply(bad, known, calls.append)
        assert code == 404, (bad, code, body)
    assert calls == [], calls


def check_apply_spawns_the_exact_name_once():
    calls = []
    code, body = D.profile_apply("/profile?name=lab-video", {"lab-video"}, calls.append)
    assert code == 200 and calls == ["lab-video"], (code, body, calls)
    assert "lab-video" in body


def check_a_refused_apply_is_said_instead_of_a_lie():
    # The old handler answered "starting profile 'panic'…" and spawned a detached apply that
    # the gate then refused. The card kept saying the old profile; the operator got nothing.
    calls = []
    code, body = D.profile_apply("/profile?name=panic", {"panic"}, calls.append,
                                 lambda n: (1, "REFUSED: never gated on this box"))
    assert code == 409 and calls == [], (code, body, calls)
    assert "never gated" in body, body
    code, body = D.profile_apply("/profile?name=panic", {"panic"}, calls.append,
                                 lambda n: (0, "would stop comfyui-h3"))
    assert code == 200 and calls == ["panic"], (code, body, calls)


def check_the_watchdog_says_off_and_silent_instead_of_nothing():
    now = 1_000_000.0
    off = D.watchdog_html(None, False, now)
    assert "off" in off and "enable --now strix-watchdog.timer" in off, off
    never = D.watchdog_html(None, True, now)
    assert "no tick has ever been recorded" in never and 'class="bad"' in never, never
    ok = D.watchdog_html({"last_tick_ts": now - 30}, True, now)
    assert 'class="on">ok' in ok and "30 s" in ok, ok
    dead = D.watchdog_html({"last_tick_ts": now - 900}, True, now)
    assert "SILENT" in dead and 'class="bad"' in dead, dead
    acted = D.watchdog_html({"last_tick_ts": now - 30, "actions": 2,
                             "tier_hits": {"0": 1, "1": 1}}, True, now)
    assert "2 action(s) today" in acted and "restart×1" in acted and "emergency×1" in acted, acted
    # a state file from a future ladder must not index out of range into a traceback
    assert "shout" not in D.watchdog_html({"last_tick_ts": now, "actions": 1,
                                           "tier_hits": {"9": 3}}, True, now)


def main():
    for fn in [check_profile_line_shows_claim_truth_and_gate,
               check_profile_line_is_clean_when_there_is_nothing_to_say,
               check_a_gate_that_is_gone_or_old_is_said_out_loud,
               check_names_are_escaped_not_executed,
               check_no_stamp_says_so_exactly_once,
               check_select_marks_current_and_always_offers_the_way_out,
               check_a_stamp_that_is_not_in_the_list_shows_placeholder,
               check_the_first_paint_of_the_chip_cannot_lie,
               check_apply_validates_before_anything_is_spawned,
               check_apply_spawns_the_exact_name_once,
               check_a_refused_apply_is_said_instead_of_a_lie,
               check_the_watchdog_says_off_and_silent_instead_of_nothing]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")


if __name__ == "__main__":
    main()
