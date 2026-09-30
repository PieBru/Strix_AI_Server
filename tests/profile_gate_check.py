"""Runnable check for scripts/profile-gate's measurement core.

    uv run --no-project python tests/profile_gate_check.py

Exit 0 = the pass/fail rule is data (every threshold boundary tested on both sides), a
missing measurement is a FAIL rather than a pass, and the real reader agrees with sysfs.
`verdict` is a pure function so the whole rule can be tested without touching the box.
"""
import importlib.machinery
import importlib.util
import pathlib
import sys
import threading
import time

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load():
    loader = importlib.machinery.SourceFileLoader("profile_gate", str(REPO / "scripts" / "profile-gate.py"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("profile_gate", loader))
    sys.modules["profile_gate"] = mod
    loader.exec_module(mod)
    return mod


g = _load()
Sample, verdict = g.Sample, g.verdict

CFG = {
    "PROFILE_GTT_PCT_MAX": "88",
    "PROFILE_MEM_AVAIL_MIN_MIB": "8192",
    "PROFILE_SWAP_MAX_MIB": "16",
    "PROFILE_BUDGET_S_TEXT": "60",
    "PROFILE_BUDGET_S_IMAGE": "180",
    "PROFILE_BUDGET_S_VIDEO": "600",
    "PROFILE_BUDGET_S_MUSIC": "300",
    "PROFILE_BUDGET_S_STT": "120",
}
BASE = dict(samples=[Sample(50.0, 20000, 0, 10.0), Sample(87.9, 8192, 0, 90.0)],
            swap_delta_pages=16 * 256, oom_lines=[], amdgpu_lines=[], restarts=0,
            probes={"text": {"ok": True, "s": 3.4}}, cfg=CFG)


def _v(**over):
    return verdict(**{**BASE, **over})


def check_pass_at_the_boundaries():
    v = _v()
    assert v["verdict"] == "PASS", v
    assert v["peak_gtt_pct"] == 87.9 and v["min_mem_avail_mib"] == 8192
    assert v["swap_delta_mib"] == 16.0


def check_each_threshold_alone_flips_it():
    cases = [
        ({"samples": [Sample(88.1, 20000, 0, 10.0)]}, "gtt"),
        ({"samples": [Sample(50.0, 8191, 0, 10.0)]}, "mem"),
        ({"swap_delta_pages": 17 * 256}, "swap"),
        ({"oom_lines": ["Out of memory: Killed process 4242 (llama-server)"]}, "oom"),
        ({"amdgpu_lines": ["amdgpu 0000:c3:00.0: GPU fault detected"]}, "amdgpu"),
        ({"restarts": 1}, "restart"),
        ({"probes": {"text": {"ok": False, "s": 2.0}}}, "text"),
    ]
    for over, why in cases:
        v = _v(**over)
        assert v["verdict"] == "FAIL", (over, v)
        assert why in " ".join(v["reasons"]).lower(), (over, v["reasons"])


def check_a_probe_that_answers_too_slow_has_passed_nothing():
    v = _v(probes={"text": {"ok": True, "s": 400}})
    assert v["verdict"] == "FAIL" and "budget" in " ".join(v["reasons"]).lower(), v
    # the same probe inside its family's budget is fine, and families differ
    assert _v(probes={"video": {"ok": True, "s": 400}})["verdict"] == "PASS"


def check_missing_measurements_fail_never_pass():
    for over, why in [({"samples": []}, "samples"),
                      ({"swap_delta_pages": None}, "swap"),
                      ({"oom_lines": None}, "oom"),
                      ({"amdgpu_lines": None}, "amdgpu"),
                      ({"probes": {}}, "probe")]:
        v = _v(**over)
        assert v["verdict"] == "FAIL", (over, v)
        assert why in " ".join(v["reasons"]).lower(), (over, v["reasons"])


def check_an_unreadable_metric_in_one_sample_is_not_a_pass():
    v = _v(samples=[Sample(None, 20000, 0, None), Sample(None, 19000, 0, None)])
    assert v["verdict"] == "FAIL" and "gtt" in " ".join(v["reasons"]).lower(), v
    # gpu_pct is informational: a box that cannot read it still passes on the real criteria
    assert _v(samples=[Sample(50.0, 20000, 0, None)])["verdict"] == "PASS"


def check_reasons_are_specific_enough_to_act_on():
    v = _v(samples=[Sample(95.0, 4000, 0, 10.0)], swap_delta_pages=99 * 256,
           oom_lines=["Killed process"], restarts=2)
    r = " ".join(v["reasons"])
    assert "95.0" in r and "4000" in r and "99" in r, r


def check_sampler_collects_at_interval():
    stop, out = threading.Event(), []
    t = threading.Thread(target=g.sampler, args=(stop, out), kwargs={"interval": 0.05})
    t.start()
    time.sleep(0.3)
    stop.set()
    t.join(timeout=2)
    assert not t.is_alive(), "sampler must stop when the event is set"
    assert 3 <= len(out) <= 12, len(out)


def check_load_cfg_is_lenient():
    d = pathlib.Path(__file__).resolve().parent
    f = d / "_gate_cfg_tmp"
    f.write_text("# comment\n\nPROFILE_GTT_PCT_MAX=88\nPROFILE_SWAP_MAX_MIB = 16\n")
    try:
        cfg = g.load_cfg(str(f))
        assert cfg["PROFILE_GTT_PCT_MAX"] == "88" and cfg["PROFILE_SWAP_MAX_MIB"] == "16"
    finally:
        f.unlink()
    assert g.load_cfg(str(d / "definitely-absent")) == {}


def check_read_sample_reads_this_box():
    s = g.read_sample()
    assert s.gtt_pct is not None and 0.0 <= s.gtt_pct < 100.0, s
    assert s.mem_avail_mib is not None and s.mem_avail_mib > 1024, s
    assert s.swap_pages is not None and s.swap_pages >= 0, s
    assert 0 <= s.gpu_pct <= 100, s


def main():
    for fn in [check_pass_at_the_boundaries, check_each_threshold_alone_flips_it,
               check_a_probe_that_answers_too_slow_has_passed_nothing,
               check_missing_measurements_fail_never_pass,
               check_an_unreadable_metric_in_one_sample_is_not_a_pass,
               check_reasons_are_specific_enough_to_act_on, check_sampler_collects_at_interval,
               check_load_cfg_is_lenient, check_read_sample_reads_this_box]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
