#!/usr/bin/env python3
"""Restart limits must be reachable: a crash-loop has to end by itself.

Why this exists (260930, Doctor pass): systemd's default is StartLimitIntervalSec=10s
with Burst=5, but every managed unit here uses RestartSec=5s (27b-collm: 20s). Five
restarts spaced 5s apart span 20s — wider than the 10s window that counts them — so the
limit can never trip and a failing unit restarts forever. The SOS arm looped for three
hours (09:36->12:48) and stopped only because an operator stopped it.

Two things are pinned: the arithmetic over the unit files in systemd/, and the fact that
the live user manager actually carries the mirror's value (manager options need
daemon-reexec, so "file edited, never applied" is a real failure mode).

    uv run --no-project python tests/restart_limit_check.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNITS = os.path.join(ROOT, "systemd")
MIRROR = os.path.join(UNITS, "user.conf.d", "startlimit.conf")


def sec(v):
    """'300' / '5s' / '100ms' / '5min' / 'infinity' -> seconds."""
    v = (v or "").strip()
    if v == "infinity":
        return 10 ** 9
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|min|h)?", v)
    if not m:
        raise AssertionError(f"unparseable systemd time {v!r}")
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "min": 60, "h": 3600, None: 1}[m.group(2)]


def field(text, name):
    m = re.search(rf"(?m)^\s*{name}\s*=\s*(.+?)\s*$", text)
    return m.group(1) if m else None


def reachable(restart, restart_sec, interval, burst):
    """systemd trips when `burst` restarts happen inside `interval`; restarts are spaced
    by RestartSec, so the burst needs (burst-1)*RestartSec of wall clock."""
    if restart in (None, "no"):
        return True
    return (burst - 1) * restart_sec <= interval


mirror = open(MIRROR).read()
mgr_interval = sec(field(mirror, "DefaultStartLimitIntervalSec"))
mgr_burst = int(field(mirror, "DefaultStartLimitBurst") or 5)
assert mgr_interval > 0, "start limit disabled (0) — loops never end either"

bad = []
checked = 0
for fn in sorted(os.listdir(UNITS)):
    if not fn.endswith(".service"):
        continue
    t = open(os.path.join(UNITS, fn)).read()
    restart, rsec = field(t, "Restart"), sec(field(t, "RestartSec") or "0.1s")
    ivl, b = field(t, "StartLimitIntervalSec"), int(field(t, "StartLimitBurst") or mgr_burst)
    ivl = sec(ivl) if ivl else mgr_interval
    checked += 1
    if not reachable(restart, rsec, ivl, b):
        bad.append(f"{fn}: RestartSec={rsec}s burst={b} needs {(b - 1) * rsec:.0f}s > window {ivl:.0f}s")
    # A gradio/uv unit dies on SIGTERM (143). Without SuccessExitStatus=143 a hand stop or a
    # profile switch is filed as Result=exit-code and the Doctor counts a crash that never
    # happened. Observed 261001 on both :7860 apps - the second had been missed by the 260927
    # sweep precisely because it was not running that day.
    if "ExecStart=/usr/bin/uv run" in t and "SuccessExitStatus=143" not in t:
        bad.append(f"{fn}: a uv/gradio unit without SuccessExitStatus=143 reads FAILED on a clean stop")
assert checked >= 8, f"only {checked} unit files found in systemd/ — did the scan break?"
assert not bad, "unreachable restart limit:\n  " + "\n  ".join(bad)

# The mirror is only a mirror if the manager is carrying it.
try:
    live = subprocess.run(["systemctl", "--user", "show", "-p", "DefaultStartLimitIntervalUSec", "--value"],
                          capture_output=True, text=True, timeout=10).stdout.strip()
except (OSError, subprocess.SubprocessError):
    live = ""
if live:
    assert sec(live) == mgr_interval, f"live user manager says {live!r}, mirror says {mgr_interval:.0f}s — daemon-reexec?"

# Same "edited but never applied" trap for the stop semantics: the repo file and the live
# unit (drop-ins included) must agree, or the fix is fiction.
for fn in sorted(os.listdir(UNITS)):
    if not fn.endswith(".service") or "SuccessExitStatus=143" not in open(os.path.join(UNITS, fn)).read():
        continue
    try:
        got = subprocess.run(["systemctl", "--user", "show", fn, "-p", "SuccessExitStatus", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        break
    if got == "":
        continue  # unit not installed on this box
    assert "143" in got, f"{fn}: mirror says 143, live user manager says {got!r} — daemon-reload?"

print(f"restart_limit_check: PASS — {checked} units, window {mgr_interval:.0f}s / burst {mgr_burst}"
      + (f", live {live}" if live else " (no systemctl: mirror only)"))
sys.exit(0)
