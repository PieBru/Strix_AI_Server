"""Runnable check for scripts/profile-gate.py — the measurement core and the gate itself.

    uv run --no-project python tests/profile_gate_check.py

Exit 0 = the pass/fail rule is data (every threshold boundary tested on both sides), a missing
measurement is a FAIL rather than a pass, the real reader agrees with sysfs, and the gate
refuses to certify a box whose units never actually loaded. Every gate test drives injected
seams (systemctl, RSS, probes, /proc, journal), so nothing here can start a unit.
"""
import datetime
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import time
import types

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


def _gate_ns(**over):
    """A stand-in for Profile: run_gate only reads these fields."""
    d = dict(name="lab-video", start=["comfyui-h3", "gemma-collm"], text_arm="gemma-collm",
             text_port=8080, gate_max_age_h=168)
    d.update(over)
    return types.SimpleNamespace(**d)


def _unit_dir():
    d = pathlib.Path(tempfile.mkdtemp(prefix="strix-units-"))
    for u in ("comfyui-h3", "gemma-collm", "27b-collm"):
        (d / f"{u}.service").write_text(f"[Service]\nExecStart=/bin/{u}\n")
    return d


class GateHarness:
    """Drives run_gate with every machine seam replaced: systemd, RSS, probes, /proc, journal.
    Nothing here can start a unit, which is the only way the concurrency rule is testable."""

    def __init__(self, units=("comfyui-h3", "gemma-collm"), rss=30.0, probe_s=0.2,
                 samples=None, schedule="concurrent", evidence=None):
        self.units = list(units)
        self.rss = rss
        self.probe_s = probe_s
        self.calls = []
        self.spans = {}
        self.lock = threading.Lock()
        self.evidence = evidence or tempfile.mkdtemp(prefix="strix-ev-")
        self.p = _gate_ns(start=list(units))
        self.samples = samples or [g.Sample(50.0, 20000, 0, 10.0)]
        self._i = 0
        self._lock2 = threading.Lock()
        self.schedule = schedule

    def systemctl(self, argv):
        self.calls.append(argv)
        return 0

    def active(self, u):
        return True

    def rss_gib(self, u):
        return self.rss

    def restarts(self, u):
        return 0

    def probe(self, name, kind, cfg):
        t0 = time.monotonic()
        time.sleep(self.probe_s)
        with self.lock:
            self.spans[kind] = (t0, time.monotonic())
        return {"ok": True, "s": self.probe_s, "detail": "stub"}

    def sample_fn(self):
        with self._lock2:
            s = self.samples[min(self._i, len(self.samples) - 1)]
            self._i += 1
        return s

    def journal(self, since):
        return [], []

    def run(self, **over):
        kw = dict(cfg={}, hold_s=0, evidence_dir=self.evidence, unit_dir=str(_unit_dir()),
                  repo_dir=str(REPO), box="testbox", systemctl=self.systemctl,
                  active_fn=self.active, rss_gib_fn=self.rss_gib, restarts_fn=self.restarts,
                  probe_fn=self.probe, sample_fn=self.sample_fn, journal_scan=self.journal,
                  schedule=self.schedule, sample_interval=0.01)
        kw.update(over)
        return g.run_gate(self.p, **kw)


def check_unit_hash_covers_dropins():
    d = _unit_dir()
    h = g.unit_hash(["gemma-collm"], unit_dir=str(d))
    assert h.startswith("sha256:")
    # a PASS earned before this edit is void: the drop-in changes what the unit really is
    (d / "gemma-collm.service.d").mkdir()
    (d / "gemma-collm.service.d" / "ctx.conf").write_text("[Service]\nExecStart=\n")
    assert g.unit_hash(["gemma-collm"], unit_dir=str(d)) != h
    assert g.unit_hash(["comfyui-h3"], unit_dir=str(d)) != h
    assert g.unit_hash(["nope-collm"], unit_dir=str(d)).endswith("missing"), "absent unit file"


def check_gate_writes_evidence_or_fails():
    r = GateHarness(evidence="/proc/nope").run()
    assert r["verdict"] == "FAIL" and "evidence" in " ".join(r["reasons"]), r


def check_concurrent_not_sequential():
    h = GateHarness(probe_s=0.25)
    r = h.run(evidence_dir=tempfile.mkdtemp(prefix="strix-ev-"))
    assert r["verdict"] == "PASS", r
    assert max(s[0] for s in h.spans.values()) < min(s[1] for s in h.spans.values()), \
        "probes ran sequentially; the gate proves nothing"
    assert r["overlap_ms"] > 0 and r["resident_units"] == 2 and r["samples"] > 1, r


def check_evidence_file_matches_the_schema():
    d = tempfile.mkdtemp(prefix="strix-ev-")
    r = GateHarness(probe_s=0.05).run(evidence_dir=d)
    on_disk = json.loads((pathlib.Path(d) / "evidence-lab-video.json").read_text())
    assert on_disk == r, (on_disk, r)
    for key in ["box", "profile", "started", "duration_s", "verdict", "reasons", "units",
                "unit_hash", "repo_sha", "peak_gtt_pct", "min_mem_avail_mib", "swap_delta_mib",
                "oom_lines", "amdgpu_lines", "unit_restarts", "overlap_ms", "resident_units",
                "samples", "probes"]:
        assert key in on_disk, key
    assert on_disk["box"] == "testbox" and on_disk["profile"] == "lab-video"
    assert set(on_disk["probes"]) == {"video", "text"}, on_disk["probes"]


def check_a_unit_that_never_loaded_is_inconclusive():
    """27b-collm runs --lazy-mode on-direct: `active` with 400 MiB pinned is NOT loaded.
    Certifying that shape is worse than not testing — it licenses apply."""
    r = GateHarness(rss=0.4).run()
    assert r["verdict"] == "INCONCLUSIVE", r
    assert r["resident_units"] < 2
    assert "floor" in " ".join(r["reasons"]).lower(), r


def check_no_overlap_window_is_inconclusive():
    r = GateHarness(schedule="sequential", probe_s=0.05).run()
    assert r["verdict"] == "INCONCLUSIVE" and r["overlap_ms"] == 0, r


def check_swap_storm_fails_even_if_it_settles():
    h = GateHarness(samples=[g.Sample(50.0, 20000, 0, 10.0),
                             g.Sample(52.0, 19000, 9_000_000, 40.0),
                             g.Sample(51.0, 19500, 9_000_010, 20.0)])
    r = h.run()
    assert r["verdict"] == "FAIL" and "swap" in " ".join(r["reasons"]), r


def check_gate_verdict_reads_evidence_and_computes_age():
    d = tempfile.mkdtemp(prefix="strix-ev-")
    assert g.gate_verdict("testbox", "lab-video", evidence_dir=d) is None
    started = (datetime.datetime.now().astimezone()
               - datetime.timedelta(hours=3)).isoformat(timespec="seconds")
    (pathlib.Path(d) / "evidence-lab-video.json").write_text(json.dumps(
        {"box": "testbox", "profile": "lab-video", "started": started, "verdict": "PASS",
         "units": ["comfyui-h3", "gemma-collm"], "reasons": []}))
    v = g.gate_verdict("testbox", "lab-video", evidence_dir=d)
    assert v["verdict"] == "PASS" and 2.9 < v["age_h"] < 3.1, v
    assert v["units"] == ["comfyui-h3", "gemma-collm"]


def check_dry_run_starts_nothing():
    h = GateHarness()
    r = h.run(dry_run=True)
    assert h.calls == [], h.calls
    assert r["verdict"] == "INCONCLUSIVE" and "dry run" in " ".join(r["reasons"]), r


def main():
    for fn in [check_pass_at_the_boundaries, check_each_threshold_alone_flips_it,
               check_a_probe_that_answers_too_slow_has_passed_nothing,
               check_missing_measurements_fail_never_pass,
               check_an_unreadable_metric_in_one_sample_is_not_a_pass,
               check_reasons_are_specific_enough_to_act_on, check_sampler_collects_at_interval,
               check_load_cfg_is_lenient, check_read_sample_reads_this_box,
               check_unit_hash_covers_dropins, check_gate_writes_evidence_or_fails,
               check_concurrent_not_sequential, check_evidence_file_matches_the_schema,
               check_a_unit_that_never_loaded_is_inconclusive,
               check_no_overlap_window_is_inconclusive,
               check_swap_storm_fails_even_if_it_settles,
               check_gate_verdict_reads_evidence_and_computes_age,
               check_dry_run_starts_nothing]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
