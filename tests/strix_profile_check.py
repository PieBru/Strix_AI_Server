"""Runnable check for scripts/strix-profile's loader, drift and stamp logic.

    uv run --no-project python tests/strix_profile_check.py

Exit 0 = the profile loader parses the INI contract, drift detection separates
claim from live truth, an unknown or malformed profile raises instead of
returning something empty, and live_units reads the box through an injectable
runner (so the same function is testable without touching systemctl).
"""
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load():
    # scripts/strix-profile has no .py suffix on purpose (it is a user command), and
    # spec_from_file_location returns None for an extensionless path — the loader must
    # be named explicitly.
    loader = importlib.machinery.SourceFileLoader("strix_profile", str(REPO / "scripts" / "strix-profile"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("strix_profile", loader))
    sys.modules["strix_profile"] = mod      # @dataclass resolves its module via sys.modules
    loader.exec_module(mod)
    return mod


sp = _load()
load_profiles, drift = sp.load_profiles, sp.drift

FIXTURE_DIR = pathlib.Path(tempfile.mkdtemp(prefix="strix-test-")) / "profiles"

LAB_VIDEO = """\
name = lab-video
summary = MiniMax-H3 + LTX video lab, gemma as the text arm
start = comfyui-h3 gemma-collm
text_arm = gemma-collm
text_port = 8080
budget_gtt_gib = 96
workload = video
gate_max_age_h = 168
"""


def fixture():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "lab-video.ini").write_text(LAB_VIDEO)
    return str(FIXTURE_DIR)


def check_loader_fields():
    p = load_profiles(fixture())["lab-video"]
    assert p.name == "lab-video"
    assert p.start == ["comfyui-h3", "gemma-collm"] and p.text_arm == "gemma-collm"
    assert p.gate_max_age_h == 168 and p.experimental is False
    assert p.text_port == 8080 and p.budget_gtt_gib == 96 and p.workload == "video"
    assert isinstance(p.tools, bool)


def check_drift_separates_claim_from_truth():
    p = load_profiles(fixture())["lab-video"]
    d = drift(p, live={"gemma-collm", "open-webui"})
    assert d["missing"] == ["comfyui-h3"], d
    # open-webui is a real unit on this box that no profile manages: never drift
    assert d["extra"] == [], d
    assert d["text_arm_up"] is True
    d2 = drift(p, live={"comfyui-h3", "acestep-serve"})
    assert d2["missing"] == ["gemma-collm"] and d2["extra"] == ["acestep-serve"]
    assert d2["text_arm_up"] is False, "text arm down must never read as healthy"


def check_unknown_profile_raises_not_empty():
    try:
        load_profiles(fixture())["nope"]["start"]
    except KeyError:
        pass
    else:
        raise AssertionError("missing key must raise, not return None")
    try:
        sp.require_profile(fixture(), "nope")
    except sp.ProfileError:
        pass
    else:
        raise AssertionError("require_profile must raise ProfileError for an unknown name")


def check_malformed_profile_raises():
    bad = pathlib.Path(tempfile.mkdtemp(prefix="strix-bad-"))
    (bad / "oops.ini").write_text("start = comfyui-h3\n")          # no name, no text_arm
    try:
        load_profiles(str(bad))
    except sp.ProfileError as e:
        assert "oops.ini" in str(e), "the error must name the offending file"
    else:
        raise AssertionError("a malformed profile must raise ProfileError, not load")


def check_missing_dir_yields_empty_dict():
    assert load_profiles("/nonexistent/profiles") == {}


def check_live_units_reads_through_injected_runner():
    p = load_profiles(fixture())["lab-video"]
    seen = []

    def fake_active(unit):                                 # unit active iff in this set
        seen.append(unit)
        return unit in {"comfyui-h3", "open-webui", "acestep-serve"}

    running, extra = sp.live_units(p, is_active=fake_active)
    assert running == {"comfyui-h3"}, running
    assert extra == {"acestep-serve"}, extra                 # managed, not in profile
    assert "open-webui" not in extra, "unmanaged units are never drift"
    assert set(seen) == set(sp.MANAGED_UNITS), "must probe every managed unit exactly once"


def check_stamp_read():
    d = tempfile.mkdtemp(prefix="strix-stamp-")
    s = pathlib.Path(d) / "profile"
    assert sp.read_stamp(str(s)) is None, "absent stamp is None, not an empty string"
    s.write_text("lab-video\n")
    assert sp.read_stamp(str(s)) == "lab-video", "stamp is stripped"


def check_json_output_is_one_parseable_document():
    """Task 9's collector does json.loads(stdout). A human reason printed after the
    JSON looks fine to a person and breaks the collector."""
    d = tempfile.mkdtemp(prefix="strix-json-")
    prof = pathlib.Path(d, "profiles")
    prof.mkdir()
    (prof / "lab-video.ini").write_text(LAB_VIDEO)
    stamp = pathlib.Path(d, "profile")
    stamp.write_text("lab-video\n")
    sp.PROFILES_DIR, sp.STAMP = str(prof), str(stamp)
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        rc = sp.cmd_current(["--json"], is_active=lambda u: u == "gemma-collm")
    finally:
        sys.stdout = old
    out = json.loads(buf.getvalue())                 # raises if anything else was printed
    assert rc == 1, "missing units must still exit 1"
    assert out["profile"] == "lab-video" and out["missing"] == ["comfyui-h3"]
    assert out["ok"] is False and out["text_arm_up"] is True


def check_json_output_when_no_stamp():
    d = tempfile.mkdtemp(prefix="strix-nostamp-")
    prof = pathlib.Path(d, "profiles")
    prof.mkdir()
    (prof / "lab-video.ini").write_text(LAB_VIDEO)
    sp.PROFILES_DIR, sp.STAMP = str(prof), str(pathlib.Path(d, "absent-stamp"))
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        rc = sp.cmd_current(["--json"], is_active=lambda u: False)
    finally:
        sys.stdout = old
    out = json.loads(buf.getvalue())
    assert rc == 1 and out["profile"] is None and "absent-stamp" in out["reason"]


PROFILES = str(REPO / "configs" / "profiles")
NAMES = {"panic", "emergency", "coding", "lab-image", "lab-video", "lab-audio", "lab-all", "off"}


def check_panic_survives_missing_config():
    """The whole point of BUILTIN: a corrupt or missing configs tree must not be able to
    take away the profile you reach for when the box is misbehaving."""
    assert sp.resolve("panic", PROFILES_DIR="/nonexistent").start == ["sos-collm"]
    assert sp.resolve("emergency", PROFILES_DIR="/nonexistent").text_arm == "27b-collm"


def check_builtin_matches_its_ini_file():
    for name in ("panic", "emergency"):
        f = sp.resolve(name, PROFILES_DIR=PROFILES)
        b = sp.resolve(name, PROFILES_DIR="/nonexistent")
        assert f == b, f"{name} diverges from BUILTIN — the 3 a.m. bug:\n file={f}\n code={b}"


def check_resolve_unknown_raises():
    try:
        sp.resolve("nope", PROFILES_DIR=PROFILES)
    except sp.ProfileError:
        pass
    else:
        raise AssertionError("resolve() must raise for an unknown profile")


def check_profile_files_are_self_consistent():
    problems = sp.check_profiles(PROFILES)
    assert problems == [], problems
    profiles = sp.load_profiles(PROFILES)
    assert set(profiles) == NAMES, set(profiles) ^ NAMES
    for n, p in profiles.items():
        assert p.text_arm or n == "off", f"{n} serves no text model and does not declare it"
        assert len(p.start) == len(set(p.start)), f"{n} lists a unit twice"
        assert set(p.start) <= set(sp.MANAGED_UNITS), f"{n} names a unit outside MANAGED_UNITS"


def check_allow_list_not_deny_list():
    """Operator ruling 260930: a profile lists what MAY run, not what may not. A managed
    unit that is running and not listed is drift to be stopped, so a unit added next month
    fails safe (stopped by every profile) instead of silently blowing a budget."""
    p = sp.resolve("lab-video", PROFILES_DIR=PROFILES)
    d = sp.drift(p, live={"27b-collm", "comfyui-h3"})
    assert d["extra"] == ["27b-collm"], d
    assert "stop" not in vars(p), "the deny-list field must be gone"


def check_off_profile_stops_everything():
    off = sp.load_profiles(PROFILES)["off"]
    assert off.start == [] and off.text_arm is None
    d = sp.drift(off, live=set(sp.MANAGED_UNITS))
    assert d["missing"] == [] and d["extra"] == list(sp.MANAGED_UNITS), d


def check_lab_all_is_experimental_and_names_the_forbidden_stack():
    p = sp.resolve("lab-all", PROFILES_DIR=PROFILES)
    assert p.experimental is True
    assert {"27b-collm", "comfyui-h3", "acestep-serve"} <= set(p.start), \
        "27B + ACE-Step + H3 is the stack AGENTS.md forbids; the gate must be handed it"


def check_check_profiles_bites():
    d = tempfile.mkdtemp(prefix="strix-badset-")
    (pathlib.Path(d) / "bad.ini").write_text(
        "name = bad\nstart = comfyui-h3 not-a-unit comfyui-h3\n"
        "text_arm = gemma-collm\nbudget_gtt_gib = 0\ntext_port = 99999\ngate_max_age_h = 0\n")
    problems = sp.check_profiles(d)
    joined = "\n".join(problems)
    for want in ("not-a-unit", "twice", "text_arm", "budget", "text_port", "gate_max_age_h"):
        assert want in joined, f"check_profiles missed {want!r} in:\n{joined}"


def check_verified_field_is_honest():
    """Operator ruling 260930: the allow-list carries when its co-residency was verified.
    An empty field means exactly one thing — no load test has ever run this set. A non-empty
    one must be three fields pointing at an evidence file whose `units` still equal the
    allow-list: edit `start` and the stamp becomes a claim about a combination nobody ran.
    (Written at Task 2 as "every file must be empty"; that stopped being the rule the first
    time the gate ran a profile, and said so on `main` after the merge.)"""
    problems = [p for p in sp.check_profiles(PROFILES)
                if "verified" in p or "allow-list changed" in p]
    assert not problems, "\n".join(problems)
    stamped = {n for n, p in sp.load_profiles(PROFILES).items() if p.verified.strip()}
    assert stamped, "no profile carries a stamp — a field nothing fills is a dead field"


def _wdir(name, body):
    d = tempfile.mkdtemp(prefix="strix-vchk-")
    (pathlib.Path(d) / f"{name}.ini").write_text(body)
    return d


def check_check_profiles_catches_verification_older_than_the_list():
    d = tempfile.mkdtemp(prefix="strix-stale-")
    ev = pathlib.Path(d) / "ev.json"
    ev.write_text(json.dumps({"units": ["comfyui-h3", "gemma-collm"]}))
    problems = sp.check_profiles(_wdir("lab-video", (
        "name = lab-video\nstart = comfyui-h3 gemma-collm ltx25-ui\n"
        "text_arm = comfyui-h3\nbudget_gtt_gib = 96\n"
        f"verified = 260930T02:14 a966c83 {ev}\n")))
    joined = "\n".join(problems)
    assert "changed since" in joined, f"adding a unit after the stamp must be a problem:\n{joined}"
    assert "ltx25-ui" in joined, "the line must name what is new"


def check_check_profiles_catches_missing_evidence():
    joined = "\n".join(sp.check_profiles(_wdir("lab-video", (
        "name = lab-video\nstart = comfyui-h3 gemma-collm\ntext_arm = comfyui-h3\n"
        "budget_gtt_gib = 96\nverified = 260930T02:14 a966c83 /nonexistent/ev.json\n"))))
    assert "evidence" in joined and "nonexistent" in joined, joined


def check_check_profiles_catches_a_malformed_verified_line():
    joined = "\n".join(sp.check_profiles(_wdir("lab-video", (
        "name = lab-video\nstart = comfyui-h3 gemma-collm\ntext_arm = comfyui-h3\n"
        "budget_gtt_gib = 96\nverified = whenever\n"))))
    assert "verified" in joined, joined


def check_check_profiles_accepts_an_honest_verification():
    d = tempfile.mkdtemp(prefix="strix-good-")
    ev = pathlib.Path(d) / "ev.json"
    ev.write_text(json.dumps({"units": ["comfyui-h3", "gemma-collm"]}))
    problems = sp.check_profiles(_wdir("lab-video", (
        "name = lab-video\nstart = comfyui-h3 gemma-collm\ntext_arm = comfyui-h3\n"
        "budget_gtt_gib = 96\n" + f"verified = 260930T02:14 a966c83 {ev}\n")))
    assert problems == [], problems


class _Stub:
    """A systemctl that records argv and can fail on a chosen call. Every apply test runs
    through this; the box is never touched."""
    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, args, timeout=180):
        self.calls.append(list(args))
        return 1 if any(f in " ".join(args) for f in self.fail_on) else 0


def _ws(stamp="lab-video"):
    d = pathlib.Path(tempfile.mkdtemp(prefix="strix-apply-"))
    (d / "profiles").mkdir()
    for f in (REPO / "configs" / "profiles").glob("*.ini"):
        shutil.copy(f, d / "profiles" / f.name)
    if stamp:
        (d / "stamp").write_text(stamp + "\n")
    return d


def _pass(units=None, age_h=1):
    def fn(box, profile):
        v = {"verdict": "PASS", "age_h": age_h}
        if units is not None:
            v["units"] = units
        return v
    return fn


def _apply(name, d, *, stub=None, verdict=None, busy=(), live=("27b-collm", "comfyui-h3"),
           **kw):
    return sp.apply(name, PROFILES_DIR=str(d / "profiles"), stamp_path=str(d / "stamp"),
                    snapshot_path=str(d / "previous.json"),
                    switches_path=str(d / "switches"),   # else the suite writes the box's real history
                    systemctl=stub or _Stub(),
                    verdict_fn=verdict or _pass(), busy=lambda: list(busy),
                    wait_arm=lambda port, ceiling: True,
                    is_active=lambda u: u in set(live), **kw)


def check_apply_order_and_stamp_last():
    d = _ws()
    stub = _Stub()
    rc = _apply("panic", d, stub=stub)
    assert rc == 0, rc
    assert stub.calls[0][:2] == ["disable", "--now"], stub.calls
    assert {"27b-collm.service", "comfyui-h3.service"} <= set(stub.calls[0][2:]), stub.calls[0]
    assert stub.calls[-1][:2] == ["enable", "--now"] and "sos-collm.service" in stub.calls[-1]
    assert sp.read_stamp(str(d / "stamp")) == "panic"
    snap = json.loads((d / "previous.json").read_text())
    assert sorted(snap["units"]) == ["27b-collm", "comfyui-h3"] and snap["stamp"] == "lab-video"


def check_apply_stops_what_the_allow_list_forbids():
    """The stop set is computed from the probe, not read from a file: off stops everything."""
    d = _ws(stamp="lab-all")
    stub = _Stub()
    live = {"27b-collm", "acestep-serve", "whisper-stt"}
    rc = _apply("off", d, stub=stub, live=live)
    assert rc == 0
    assert sorted(stub.calls[0][2:]) == ["27b-collm.service", "acestep-serve.service",
                                         "whisper-stt.service"], stub.calls[0]
    assert len(stub.calls) == 1, "off starts nothing"


def check_apply_refuses_busy_gpu_before_touching_anything():
    d, stub = _ws(), _Stub()
    err, old = io.StringIO(), sys.stderr
    sys.stderr = err
    try:
        rc = _apply("lab-image", d, stub=stub, busy=("comfyui-h3",))
    finally:
        sys.stderr = old
    assert rc == 1 and "comfyui-h3" in err.getvalue(), err.getvalue()
    assert stub.calls == [], "refusal must precede every systemctl call"
    assert sp.read_stamp(str(d / "stamp")) == "lab-video"
    assert _apply("lab-image", d, stub=_Stub(), busy=("comfyui-h3",), force=True) == 0


def check_apply_refuses_stale_gate_unless_i_know():
    d = _ws()
    assert _apply("lab-video", d, verdict=_pass(age_h=400)) == 1
    assert _apply("lab-video", d, verdict=_pass(age_h=400), i_know=True) == 0
    assert _apply("lab-video", d, verdict=lambda b, p: None) == 1, "never gated = never applied"
    assert _apply("lab-video", d, verdict=lambda b, p: {"verdict": "FAIL", "age_h": 1}) == 1


def check_never_gated_profiles_ignore_the_clock():
    """panic/emergency declare gate_max_age_h = 87600 (10 years): freeing the GPU must not be
    blocked by an evidence file nobody has refreshed in months. Same age, opposite verdicts."""
    d = _ws()
    assert _apply("lab-video", d, verdict=_pass(age_h=4000)) == 1, "lab expires at 168 h"
    assert _apply("panic", d, verdict=_pass(age_h=4000)) == 0


def check_apply_refuses_a_stamp_earned_by_a_different_set():
    d = _ws()
    err, old = io.StringIO(), sys.stderr
    sys.stderr = err
    try:
        rc = _apply("lab-video", d, verdict=_pass(units=["comfyui-h3"]))
    finally:
        sys.stderr = old
    assert rc == 1 and "gemma-collm" in err.getvalue(), err.getvalue()


def check_failed_apply_leaves_the_stamp_alone_and_rolls_back():
    d = _ws()
    stub = _Stub(fail_on=["enable --now qwen-image-test"])
    rc = _apply("lab-image", d, stub=stub, live=("27b-collm",))
    assert rc == 1
    assert sp.read_stamp(str(d / "stamp")) == "lab-video", \
        "a stamp written before the system agrees is a lie waiting to be believed"
    assert ["enable", "--now", "27b-collm.service"] in stub.calls, stub.calls
    # The rollback this failure triggers must land in the injected history, never in the
    # box's real one: a suite that writes ~/.local/state/strix/ teaches the ARM card lies.
    sw = open(str(d / "switches")).read()
    assert '"why": "rollback"' in sw and '"to": "lab-video"' in sw, sw


def check_rollback_restores_the_snapshot():
    d = _ws()
    _apply("panic", d)                      # writes previous.json with the old set
    stub = _Stub()
    rc = sp.rollback(PROFILES_DIR=str(d / "profiles"), stamp_path=str(d / "stamp"),
                     snapshot_path=str(d / "previous.json"),
                     switches_path=str(d / "switches"), systemctl=stub,
                     is_active=lambda u: False)
    assert rc == 0
    assert ["enable", "--now", "27b-collm.service"] in stub.calls, stub.calls
    assert sp.read_stamp(str(d / "stamp")) == "lab-video"


def check_rollback_without_snapshot_is_refused():
    d = _ws()
    stub = _Stub()
    rc = sp.rollback(PROFILES_DIR=str(d / "profiles"), stamp_path=str(d / "stamp"),
                     snapshot_path=str(d / "absent.json"),
                     switches_path=str(d / "switches"), systemctl=stub)
    assert rc == 1 and stub.calls == []


def check_dry_run_prints_argv_and_changes_nothing():
    d, stub = _ws(), _Stub()
    out, old = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        rc = _apply("panic", d, stub=stub, dry_run=True)
    finally:
        sys.stdout = old
    assert rc == 0 and stub.calls == []
    assert "disable --now 27b-collm.service" in out.getvalue(), out.getvalue()
    assert "enable --now sos-collm.service" in out.getvalue()
    assert not (d / "stamp").exists() or sp.read_stamp(str(d / "stamp")) == "lab-video"


def check_dry_run_reports_refusals_it_would_hit():
    """--dry-run is how you preview before spending a GPU minute: it must show the plan AND
    every reason it would refuse, not stop at the first one."""
    d = _ws()
    out, old = io.StringIO(), sys.stdout
    sys.stdout = out
    try:
        rc = _apply("lab-video", d, dry_run=True, verdict=lambda b, p: None,
                    busy=("comfyui-h3",))
    finally:
        sys.stdout = old
    t = out.getvalue()
    assert rc == 1, "a dry run that would refuse exits non-zero so a script can test it"
    assert t.count("WOULD REFUSE") == 2, t
    assert "enable --now comfyui-h3.service h3-video-ui.service ltx25-ui.service" in t, t


def check_the_busy_guard_asks_the_renderer_and_not_the_gpu_percentage():
    # OBSERVED 260930: gpu_busy_percent pinned at 100 with nothing rendering (ROCR
    # AsyncEventsLoop, TheRock#7051) while ComfyUI burned 111 % CPU. A guard built on that
    # number refuses every apply from the first render onwards, so the queue decides.
    # The percentage is injected, NOT read from sysfs: a test that asserts the spin is live
    # breaks the moment the box behaves, and then nobody knows which half regressed.
    assert sp._busy(ask=lambda: False, pct_fn=lambda: 100, renderer_up=lambda: True) == [], \
        "queue idle means apply, whatever the percentage says"
    assert sp._busy(ask=lambda: True, pct_fn=lambda: 0, renderer_up=lambda: True) == \
        ["comfyui queue has a job running"]
    r = sp._busy(ask=lambda: None, pct_fn=lambda: 100, renderer_up=lambda: True)
    assert r and "unreachable" in r[0] and "100" in r[0], "no queue + a live renderer -> the crude reading votes"
    assert sp._busy(ask=lambda: None, pct_fn=lambda: 5, renderer_up=lambda: True) == [], \
        "and a quiet crude reading does not"
    assert sp._busy(ask=lambda: None, pct_fn=lambda: 1 / 0, renderer_up=lambda: True) == [], \
        "an unreadable metric is not busy"
    # 261001: with the renderer's unit stopped there is no job to protect, so the stuck
    # percentage must not veto - least of all the watchdog's automatic `panic`.
    assert sp._busy(ask=lambda: None, pct_fn=lambda: 100, renderer_up=lambda: False) == [], \
        "comfyui not running = nothing rendering, whatever sysfs says"


def check_force_reaches_an_ungated_profile_but_never_a_measured_fail():
    # The emergency cord must be reachable without a load test: panic IS the response to the box
    # already being wrong, and absence of evidence is not evidence of safety. A FAIL is different
    # evidence — we measured it and it broke — so --force does not touch it.
    d = _ws()
    err, old = io.StringIO(), sys.stderr
    sys.stderr = err
    try:
        assert _apply("panic", d, verdict=lambda b, p: None) == 1, "ungated + no force = refuse"
        assert _apply("panic", d, verdict=lambda b, p: None, force=True) == 0
        assert "unmeasured" in err.getvalue(), err.getvalue()
        assert _apply("panic", d, verdict=lambda b, p: {"verdict": "FAIL",
                                                        "reasons": ["swap written"]},
                      force=True) == 1, "force must not override a measured FAIL"
    finally:
        sys.stderr = old


def main():
    for fn in [check_loader_fields, check_drift_separates_claim_from_truth,
               check_unknown_profile_raises_not_empty, check_malformed_profile_raises,
               check_missing_dir_yields_empty_dict, check_live_units_reads_through_injected_runner,
               check_stamp_read, check_json_output_is_one_parseable_document,
               check_json_output_when_no_stamp, check_panic_survives_missing_config,
               check_builtin_matches_its_ini_file, check_resolve_unknown_raises,
               check_profile_files_are_self_consistent, check_allow_list_not_deny_list,
               check_off_profile_stops_everything,
               check_lab_all_is_experimental_and_names_the_forbidden_stack,
               check_check_profiles_bites, check_verified_field_is_honest,
               check_check_profiles_catches_verification_older_than_the_list,
               check_check_profiles_catches_missing_evidence,
               check_check_profiles_catches_a_malformed_verified_line,
               check_check_profiles_accepts_an_honest_verification,
               check_apply_order_and_stamp_last,
               check_apply_stops_what_the_allow_list_forbids,
               check_apply_refuses_busy_gpu_before_touching_anything,
               check_the_busy_guard_asks_the_renderer_and_not_the_gpu_percentage,
               check_force_reaches_an_ungated_profile_but_never_a_measured_fail,
               check_apply_refuses_stale_gate_unless_i_know,
               check_never_gated_profiles_ignore_the_clock,
               check_apply_refuses_a_stamp_earned_by_a_different_set,
               check_failed_apply_leaves_the_stamp_alone_and_rolls_back,
               check_rollback_restores_the_snapshot,
               check_rollback_without_snapshot_is_refused,
               check_dry_run_prints_argv_and_changes_nothing,
               check_dry_run_reports_refusals_it_would_hit]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
