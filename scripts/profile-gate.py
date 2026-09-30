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

import os
import threading
import time
from dataclasses import dataclass

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


if __name__ == "__main__":
    s = read_sample()
    print(f"gtt {s.gtt_pct}%  mem_avail {s.mem_avail_mib} MiB  "
          f"swap_pages {s.swap_pages}  gpu {s.gpu_pct}%")
