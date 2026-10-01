"""Runnable check for the morning-report card in doctor/Doctor.py.

    uv run --offline --no-project python tests/checkup_card_check.py

The card is the only place the operator learns whether the night produced a report at all.
Before 261001 it printed panel.json's mtime under a hardcoded "LAST NIGHT'S CHECKUP", so a
night the idle gate refused (OBSERVED: busy 03:15→06:51, no report) looked identical to a
fresh pass. checkup_html(skill=...) takes the skill dir so a fixture can drive every state.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


D = _load("doctor_checkup_under_test", REPO / "doctor" / "Doctor.py")

PANEL = {"generated": "x", "summary": ["line one", "line two"],
         "new": {"P1": 0, "P2": 3, "P3": 5}, "backlog": {"count": 9, "oldest_days": 11}}


def fixture(report_today=False, last_pass=None, panel=PANEL):
    """A throwaway skill dir: panel.json always, a report dated today on request."""
    d = tempfile.mkdtemp(prefix="checkup-")
    (pathlib.Path(d) / "state").mkdir()
    if panel is not None:
        (pathlib.Path(d) / "state" / "panel.json").write_text(json.dumps(panel))
    if report_today:
        (pathlib.Path(d) / f"DOCTOR_REPORT_{time.strftime('%y%m%d')}-033000.md").write_text("# ok")
    if last_pass is not None:
        (pathlib.Path(d) / "state" / "LAST-PASS.json").write_text(json.dumps(last_pass))
    return d


def check_a_report_dated_today_is_titled_as_today():
    h = D.checkup_html(fixture(report_today=True))
    assert "NO REPORT" not in h, h
    assert "CHECKUP —" in h, h
    assert "P2×3" in h and "oldest 11d" in h, h
    assert "line one" in h and "full report" in h, h


def check_a_skipped_night_says_so_with_the_gate_reason():
    d = fixture(report_today=False, last_pass={
        "date": "260930", "outcome": "skipped-by-gate",
        "reason": "give-up hour reached (06:51)"})
    h = D.checkup_html(d)
    assert "NO REPORT today" in h, h
    assert "give-up hour reached (06:51)" in h, h
    # The title must not claim today for a report from another day.
    assert time.strftime("%b %d") in h, h


def check_a_missing_stamp_admits_it_cannot_say_why():
    h = D.checkup_html(fixture(report_today=False))
    assert "NO REPORT today" in h and "cannot say why" in h, h


def check_a_covered_today_is_not_shown_as_a_failure():
    # The gate refusing because today is already reported is the normal 13:4x case.
    d = fixture(report_today=True, last_pass={"outcome": "skipped-by-gate",
                                              "reason": "a report is already dated 261001"})
    assert "NO REPORT" not in D.checkup_html(d), "today's report must silence the warning"


def check_the_reason_is_escaped_not_executed():
    d = fixture(report_today=False, last_pass={"outcome": "no-report",
                                               "reason": "<script>alert(1)</script>"})
    h = D.checkup_html(d)
    assert "<script>" not in h and "&lt;script&gt;" in h, h


def check_no_panel_means_no_card():
    assert D.checkup_html(fixture(panel=None)) == ""


def main():
    for fn in [check_a_report_dated_today_is_titled_as_today,
               check_a_skipped_night_says_so_with_the_gate_reason,
               check_a_missing_stamp_admits_it_cannot_say_why,
               check_a_covered_today_is_not_shown_as_a_failure,
               check_the_reason_is_escaped_not_executed,
               check_no_panel_means_no_card]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")


if __name__ == "__main__":
    main()
