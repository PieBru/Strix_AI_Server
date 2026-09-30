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
stop = 27b-collm llama-llm
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
    assert isinstance(p.tools, bool) and isinstance(p.stop, list)


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


def main():
    for fn in [check_loader_fields, check_drift_separates_claim_from_truth,
               check_unknown_profile_raises_not_empty, check_malformed_profile_raises,
               check_missing_dir_yields_empty_dict, check_live_units_reads_through_injected_runner,
               check_stamp_read, check_json_output_is_one_parseable_document,
               check_json_output_when_no_stamp]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
