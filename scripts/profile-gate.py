#!/usr/bin/env python3
"""profile-gate — does this profile actually fit on this box, measured rather than declared.

    profile-gate.py            # one sample, so a human can see what the box reports

The pass/fail rule lives in `verdict()`, a pure function over samples and counters, so the
whole contract is testable on synthetic input (tests/profile_gate_check.py). Everything that
touches the machine is a separate reader.

GTT is the only GPU-memory truth here. This is a Strix Halo: visible VRAM is a 1 GiB
carve-out, so `rocm-smi`'s VRAM% reads that carve-out and reports ~90 % while the box is
idle. The numbers that matter are `mem_info_gtt_used` over `mem_info_gtt_total` (124 GiB).
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

REPO = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE_DIR = os.path.expanduser("~/.local/share/strix/gate")
UNIT_DIR = os.path.expanduser("~/.config/systemd/user")
DOCTOR_CONFIG = os.environ.get("STRIX_DOCTOR_CONFIG", str(REPO / "doctor" / "doctor.config"))

# unit -> (family, probe kind). A unit that is not listed has no floor and no probe: a gradio
# page is not a model, and the gate must not fail a profile for not loading one.
UNITS = {
    "27b-collm": ("llm", "text"), "gemma-collm": ("llm", "text"), "sos-collm": ("llm", "text"),
    "gufo-llm": ("llm", "text"),
    "gufo-serve": ("image", "image"), "qwen-image-test": ("image", "image"),
    "comfyui-h3": ("video", "video"),
    "acestep-serve": ("audio", "music"), "whisper-stt": ("audio", "stt"),
}
FLOOR_DEFAULTS = {"llm": "4", "image": "4", "video": "8", "audio": "4"}

GTT_USED = "/sys/class/drm/card0/device/mem_info_gtt_used"
GTT_TOTAL = "/sys/class/drm/card0/device/mem_info_gtt_total"
GPU_BUSY = "/sys/class/drm/card0/device/gpu_busy_percent"
PAGES_PER_MIB = 256

# Thresholds live in doctor.config (Task 9 adds the keys) so they can be retuned without
# touching code; these are the defaults the gate falls back to.
DEFAULTS = {
    "PROFILE_GTT_PCT_MAX": "88",
    "PROFILE_MEM_AVAIL_MIN_MIB": "8192",
    "PROFILE_SWAP_MAX_MIB": "16",
    "PROFILE_BUDGET_S_TEXT": "60",
    "PROFILE_BUDGET_S_IMAGE": "180",
    "PROFILE_BUDGET_S_VIDEO": "600",
    "PROFILE_BUDGET_S_MUSIC": "300",
    "PROFILE_BUDGET_S_STT": "120",
}


@dataclass
class Sample:
    """One 1 Hz reading. Any field can be None: an unreadable metric is never a zero, and
    `verdict` turns a missing measurement into a FAIL, never a pass."""
    gtt_pct: float | None
    mem_avail_mib: int | None
    swap_pages: int | None
    gpu_pct: float | None


def _int(path: str) -> int | None:
    try:
        return int(open(path).read().strip())
    except (OSError, ValueError):
        return None


def read_sample() -> Sample:
    used, total = _int(GTT_USED), _int(GTT_TOTAL)
    gtt = round(used * 100.0 / total, 2) if used is not None and total else None

    mem = None
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                mem = int(line.split()[1]) // 1024
                break
    except OSError:
        pass

    swap = None
    try:
        pin = pout = None
        for line in open("/proc/vmstat"):
            if line.startswith("pswpin "):
                pin = int(line.split()[1])
            elif line.startswith("pswpout "):
                pout = int(line.split()[1])
        if pin is not None and pout is not None:
            swap = pin + pout
    except OSError:
        pass

    gpu = _int(GPU_BUSY)
    return Sample(gtt, mem, swap, float(gpu) if gpu is not None else None)


def sampler(stop: threading.Event, out: list[Sample], interval: float = 1.0) -> None:
    """1 Hz for the whole run. Peaks and deltas come from the series, never from a single
    end-of-run read: a swap storm that settles before the last sample is exactly the event
    that must fail the gate."""
    while not stop.is_set():
        out.append(read_sample())
        stop.wait(interval)


def load_cfg(path: str) -> dict[str, str]:
    """KEY=value lines with # comments; a missing file is {} (defaults apply)."""
    out: dict[str, str] = {}
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def verdict(samples, swap_delta_pages, oom_lines, amdgpu_lines, restarts, probes,
            cfg: dict[str, str]) -> dict:
    """The whole pass/fail rule, as data. No I/O: every number is handed in, so a test can
    put the box exactly on each boundary and check which side it falls on."""
    cfg = {**DEFAULTS, **(cfg or {})}
    reasons: list[str] = []

    if not samples:
        reasons.append("no samples measurement — the sampler produced nothing")
    gtts = [s.gtt_pct for s in samples if s.gtt_pct is not None]
    mems = [s.mem_avail_mib for s in samples if s.mem_avail_mib is not None]
    peak_gtt = max(gtts) if gtts else None
    min_mem = min(mems) if mems else None

    if peak_gtt is None:
        reasons.append("no gtt measurement — the profile cannot be priced")
    elif peak_gtt > float(cfg["PROFILE_GTT_PCT_MAX"]):
        reasons.append(f"gtt peaked at {peak_gtt:.1f} % > {cfg['PROFILE_GTT_PCT_MAX']} %")

    if min_mem is None:
        reasons.append("no mem_avail measurement")
    elif min_mem < int(cfg["PROFILE_MEM_AVAIL_MIN_MIB"]):
        reasons.append(f"mem_avail fell to {min_mem} MiB < {cfg['PROFILE_MEM_AVAIL_MIN_MIB']} MiB")

    if swap_delta_pages is None:
        reasons.append("no swap measurement")
    else:
        mib = swap_delta_pages / PAGES_PER_MIB
        if mib > float(cfg["PROFILE_SWAP_MAX_MIB"]):
            reasons.append(f"swap written {mib:.1f} MiB > {cfg['PROFILE_SWAP_MAX_MIB']} MiB "
                           f"— that is a swap storm, not noise")

    for name, lines in (("oom", oom_lines), ("amdgpu", amdgpu_lines)):
        if lines is None:
            reasons.append(f"no {name} measurement — the log scan did not run")
        elif lines:
            reasons.append(f"{name}: {len(lines)} line(s), first: {lines[0][:120]}")

    if restarts is None:
        reasons.append("no restart measurement")
    elif restarts:
        reasons.append(f"{restarts} unit restart(s) during the run")

    if not probes:
        reasons.append("no probe ran — a gate that asked nothing learned nothing")
    for fam, r in (probes or {}).items():
        if not r.get("ok"):
            reasons.append(f"probe {fam} failed: {r.get('detail', 'no positive evidence')}")
            continue
        budget = float(cfg.get(f"PROFILE_BUDGET_S_{fam.upper()}", 0) or 0)
        took = r.get("s")
        if budget and took is not None and took > budget:
            reasons.append(f"probe {fam} answered in {took:.0f} s > {budget:.0f} s budget — a "
                           f"model that answers this slowly under load has passed nothing")

    return {"verdict": "FAIL" if reasons else "PASS", "reasons": reasons,
            "peak_gtt_pct": peak_gtt, "min_mem_avail_mib": min_mem,
            "swap_delta_mib": None if swap_delta_pages is None
            else round(swap_delta_pages / PAGES_PER_MIB, 2)}


def unit_hash(units, unit_dir: str = UNIT_DIR) -> str:
    """sha256 over the unit files and their drop-ins, in sorted order. A PASS is only valid for
    the unit definitions that earned it: adding `ctx256k.conf` to a running arm changes what it
    is, so the hash changes and the old evidence stops applying. A missing file is recorded in
    the suffix rather than skipped — hashing nothing must not look like hashing something."""
    h = hashlib.sha256()
    missing = []
    for u in sorted(units):
        files = [pathlib.Path(unit_dir) / f"{u}.service"]
        files += sorted((pathlib.Path(unit_dir) / f"{u}.service.d").glob("*.conf"))
        for p in files:
            try:
                h.update(p.read_bytes())
            except OSError:
                if u not in missing:
                    missing.append(u)
        h.update(b"\0")
    return "sha256:" + h.hexdigest() + (";missing" if missing else "")


def _systemctl(argv):
    return subprocess.run(["systemctl", *argv], capture_output=True).returncode


def _is_active(unit):
    out = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True)
    return out.stdout.decode().strip() == "active"


def _rss_gib(unit):
    """Main process RSS. This is the residency signal because `is-active` is not: with
    --lazy-mode on-direct a 44 GiB arm reports active while pinning 400 MiB."""
    out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", unit],
                         capture_output=True)
    pid = out.stdout.decode().strip()
    if not pid.isdigit() or pid == "0":
        return 0.0
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 2**20  # KiB -> GiB
    except (OSError, ValueError):
        return 0.0
    return 0.0


def _nrestarts(unit):
    out = subprocess.run(["systemctl", "--user", "show", "-p", "NRestarts", "--value", unit],
                         capture_output=True)
    v = out.stdout.decode().strip()
    return int(v) if v.isdigit() else 0


def _journal_scan(since):
    """Kernel log since the run started: the OOM killer and any amdgpu fault. Read once, at the
    end, from the kernel journal — a unit that was killed leaves no trace in its own log."""
    out = subprocess.run(["journalctl", "-k", "--since", since, "--no-pager"],
                         capture_output=True)
    lines = out.stdout.decode(errors="replace").splitlines()
    low = [l.lower() for l in lines]
    oom = [l for l, s in zip(lines, low) if "killed process" in s or "out of memory" in s]
    amdgpu = [l for l, s in zip(lines, low)
              if "amdgpu" in s and any(w in s for w in ("fault", "reset", "hang", "error"))]
    return oom, amdgpu


def _repo_sha(repo_dir):
    out = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"],
                         capture_output=True)
    return out.stdout.decode().strip() or "unknown"


def _floor(family, cfg):
    return float(cfg.get(f"PROFILE_FLOOR_{family.upper()}_GIB", FLOOR_DEFAULTS[family]))


def run_gate(profile, *, cfg=None, dry_run=False, hold_s=60, evidence_dir=EVIDENCE_DIR,
             unit_dir=UNIT_DIR, repo_dir=REPO, box=None, systemctl=_systemctl,
             active_fn=_is_active, rss_gib_fn=_rss_gib, restarts_fn=_nrestarts,
             probe_fn=None, sample_fn=read_sample, journal_scan=_journal_scan,
             schedule="concurrent", sample_interval=1.0, load_ceiling_s=240):
    """Start the profile's units, load them, run every family's probe at the same time, hold the
    pressure, and write the evidence. Returns the evidence dict (and writes it, unless dry).

    Every machine touch is a parameter. That is not decoration: the concurrency rule, the
    residency floor and the INCONCLUSIVE precedence are only testable if the gate can be driven
    against a box that does not exist.
    """
    cfg = load_cfg(DOCTOR_CONFIG) if cfg is None else cfg
    if probe_fn is None:
        loader = importlib.machinery.SourceFileLoader(
            "profile_probes", str(REPO / "scripts" / "profile_probes.py"))
        mod = importlib.util.module_from_spec(
            importlib.util.spec_from_loader("profile_probes", loader))
        sys.modules["profile_probes"] = mod
        loader.exec_module(mod)
        probe_fn = mod.probe
    box = box or os.uname().nodename
    units = list(profile.start)
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    kinds = [UNITS[u][1] for u in units if u in UNITS]

    if dry_run:
        print(f"gate {profile.name} — dry run, nothing is started:\n"
              f"  units   {' '.join(units) or '(none)'}\n"
              f"  floors  " + " ".join(f"{u}>={_floor(UNITS[u][0], cfg):g} GiB"
                                       for u in units if u in UNITS))
        print(f"  probes  {' '.join(kinds) or '(none)'} concurrently, then hold {hold_s} s\n"
              f"  budget  GTT peak <= {cfg.get('PROFILE_GTT_PCT_MAX', DEFAULTS['PROFILE_GTT_PCT_MAX'])} %, "
              f"mem_avail >= {cfg.get('PROFILE_MEM_AVAIL_MIN_MIB', DEFAULTS['PROFILE_MEM_AVAIL_MIN_MIB'])} MiB, "
              f"swap <= {cfg.get('PROFILE_SWAP_MAX_MIB', DEFAULTS['PROFILE_SWAP_MAX_MIB'])} MiB")
        return _evidence(box, profile, started, t0, units, unit_dir, repo_dir,
                         ["dry run — nothing was measured, so this is not "
                          "evidence and will not be written"],
                         "INCONCLUSIVE", None, None, None, None, None, 0, 0, 0, 0, {})

    # phase 1/2: start everything, then wait for the units to be at least `active`. Being active
    # is not being loaded; residency is judged from RSS below, after the probes have run.
    before = {u: restarts_fn(u) for u in units}
    for u in units:
        systemctl(["--user", "enable", "--now", f"{u}.service"])
    deadline = time.monotonic() + load_ceiling_s
    pending = [u for u in units if not active_fn(u)]
    while pending and time.monotonic() < deadline:
        time.sleep(2)
        pending = [u for u in pending if not active_fn(u)]

    # phase 3: the sampler starts BEFORE the first probe, and every probe is in flight at the
    # same time. Sequential probes measure N separate peaks, which is not the claim being made.
    samples: list[Sample] = []
    rss_peaks = {u: 0.0 for u in units}
    stop = threading.Event()

    def sample_loop():
        while not stop.is_set():
            samples.append(sample_fn())
            stop.wait(sample_interval)

    def rss_loop():
        while not stop.is_set():
            for u in units:
                v = rss_gib_fn(u)
                if v > rss_peaks[u]:
                    rss_peaks[u] = v
            stop.wait(sample_interval)

    sam = threading.Thread(target=sample_loop)
    rsst = threading.Thread(target=rss_loop)
    sam.start()
    rsst.start()

    spans: dict[str, tuple] = {}
    lock = threading.Lock()

    def one(kind):
        t_start = time.monotonic()
        r = probe_fn(kind, cfg)
        with lock:
            spans[kind] = (t_start, time.monotonic(), r)

    threads = [threading.Thread(target=one, args=(k,)) for k in kinds]
    for t in threads:
        t.start()
        if schedule == "sequential":
            t.join()
    for t in threads:
        t.join()
    time.sleep(hold_s)  # keep the weights hot while the sampler keeps reading
    stop.set()
    sam.join(timeout=10)
    rsst.join(timeout=10)

    # phase 4: aftermath. The OOM killer and a GPU fault live in the kernel journal, not in the
    # unit's own log, and a unit that restarted mid-run is a unit that died and came back.
    oom, amdgpu = journal_scan(started)
    restarts = sum(max(0, restarts_fn(u) - before[u]) for u in units)
    first, last = (samples[0], samples[-1]) if len(samples) >= 2 else (None, None)
    swap_delta = (None if not first or first.swap_pages is None or last.swap_pages is None
                  else last.swap_pages - first.swap_pages)
    probes_out = {k: {"ok": r["ok"], "s": r["s"], "detail": r.get("detail", "")}
                  for k, (_, _, r) in spans.items()}
    v = verdict(samples, swap_delta, oom, amdgpu, restarts, probes_out, cfg)
    reasons = list(v["reasons"])
    final = v["verdict"]

    overlap_ms = 0
    if spans:
        window = (min(s[1] for s in spans.values()) - max(s[0] for s in spans.values())) * 1000
        overlap_ms = int(max(0, window))

    resident = [u for u in units if u in UNITS and rss_peaks[u] >= _floor(UNITS[u][0], cfg)]
    below = [u for u in units if u in UNITS and u not in resident]
    if below and final != "FAIL":
        # INCONCLUSIVE, not FAIL: the box may be fine and the unit just slow. What must never
        # happen is a PASS that licenses apply on a shape that OOMs on first use.
        final = "INCONCLUSIVE"
        reasons.append("never reached its residency floor: " +
                       ", ".join(f"{u} peaked at {rss_peaks[u]:.1f} GiB "
                                 f"(floor {_floor(UNITS[u][0], cfg):g} GiB)" for u in below))
    if overlap_ms <= 0 and final != "FAIL":
        final = "INCONCLUSIVE"
        reasons.append(f"no overlap window (overlap_ms={overlap_ms}) — the probes did not run "
                       f"concurrently, so this measured {len(spans)} separate peaks, not one "
                       f"co-resident set")

    ev = _evidence(box, profile, started, t0, units, unit_dir, repo_dir, reasons, final,
                   v["peak_gtt_pct"], v["min_mem_avail_mib"], v["swap_delta_mib"],
                   None if oom is None else len(oom), None if amdgpu is None else len(amdgpu),
                   restarts, overlap_ms, len(resident), len(samples), probes_out)
    path = pathlib.Path(evidence_dir) / f"evidence-{profile.name}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ev, indent=1) + "\n")
        tmp.replace(path)
    except OSError as e:
        # A gate nobody can read did not happen.
        ev["verdict"] = "FAIL"
        ev["reasons"] = reasons + [f"evidence could not be written to {path}: {e} — a gate that "
                                   f"cannot write its evidence has failed, by definition"]
    return ev


def _evidence(box, profile, started, t0, units, unit_dir, repo_dir, reasons, verdict_,
              peak_gtt, min_mem, swap_mib, oom_n, amdgpu_n, restarts, overlap_ms, resident,
              samples_n, probes):
    """The evidence schema. Doctor and the collector parse exactly these keys; extra keys are
    additive, missing ones are a contract break."""
    return {"box": box, "profile": profile.name, "started": started,
            "duration_s": round(time.monotonic() - t0, 1), "verdict": verdict_,
            "reasons": list(reasons), "units": list(units),
            "unit_hash": unit_hash(units, unit_dir), "repo_sha": _repo_sha(repo_dir),
            "peak_gtt_pct": peak_gtt, "min_mem_avail_mib": min_mem, "swap_delta_mib": swap_mib,
            "oom_lines": oom_n, "amdgpu_lines": amdgpu_n, "unit_restarts": restarts,
            "overlap_ms": overlap_ms, "resident_units": resident, "samples": samples_n,
            "probes": probes}


def gate_verdict(box: str, profile: str, evidence_dir: str = EVIDENCE_DIR):
    """The newest gate result for this box and profile, with age_h computed, or None. This is
    what `strix-profile apply` asks before it touches systemd."""
    try:
        ev = json.loads((pathlib.Path(evidence_dir) / f"evidence-{profile}.json").read_text())
    except (OSError, ValueError):
        return None
    if ev.get("box") != box:
        # evidence earned on another machine says nothing about this one
        return None
    try:
        started = datetime.datetime.fromisoformat(ev["started"])
    except (KeyError, ValueError):
        ev["age_h"] = None
        return ev
    ev["age_h"] = round((datetime.datetime.now().astimezone() - started).total_seconds() / 3600,
                        2)
    return ev


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        s = read_sample()
        print(f"gtt {s.gtt_pct}%  mem_avail {s.mem_avail_mib} MiB  "
              f"swap_pages {s.swap_pages}  gpu {s.gpu_pct}%")
        sys.exit(0)

    loader = importlib.machinery.SourceFileLoader("strix_profile",
                                                  str(REPO / "scripts" / "strix-profile"))
    sp = importlib.util.module_from_spec(importlib.util.spec_from_loader("strix_profile", loader))
    sys.modules["strix_profile"] = sp  # @dataclass in the loaded module resolves via sys.modules
    loader.exec_module(sp)
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    hold = 60
    if "--hold" in args:
        i = args.index("--hold")
        hold = float(args[i + 1])
        del args[i:i + 2]
    prof = sp.resolve(args[0])
    ev = run_gate(prof, dry_run=dry, hold_s=hold)
    print(json.dumps(ev, indent=1))
    print(f"gate {prof.name}: {ev['verdict']} — {'; '.join(ev['reasons']) or 'clean'}", file=sys.stderr)
    sys.exit(0 if ev["verdict"] == "PASS" else 1)
