#!/usr/bin/env python3
"""power-sampler — the last thing the machine writes before a HARD power cut.

Why this exists and sysmon/Doctor do not cover it: a hard cut (GMKtec EVO-X2
brick OCP / EC cooling-gated power-off) leaves **zero** OS trace — no journal
shutdown record, no kernel error, no wtmp entry. journald is buffered, so
whatever it had not yet flushed is gone with the rail. This sampler calls
`fsync` after **every** line: the last surviving line of the log *is* the
machine state at the instant of the cut.

Reads /sys hwmon resolved by `name`, never by index (hwmonN is not stable
across boots). No subprocesses, no rocm-smi — a monitor that can hang stops
writing, which is indistinguishable from a quiet system.

Two sensor notes, measured on this box 260926:
  * `k10temp Tctl` and `acpitz` read a fixed 98/97 °C regardless of load and
    are **unusable**. Logged anyway (cheap) so the claim stays checkable;
    trust `amdgpu edge` only.
  * `power1_*` is in **microwatts** here (not milliwatts like the temps), and
    this board exposes **no** `power1_max`/`rated_max` — the PPT cap in force
    cannot be read from software, so the performance-mode switch is invisible.
    A rising `ppt` ceiling across boots is the only proxy.

Usage:
  power-sampler.py             # sample forever (systemd runs this)
  power-sampler.py --once      # one line to stdout, non-zero if the sensors
                               # did not resolve (self-check)
  power-sampler.py --tail [N]  # last N lines, newest first

Install: see doctor/power-sampler.service.
"""
import datetime
import glob
import os
import sys
import time

INTERVAL_S = 5.0
LOG = os.path.expanduser("~/logs/power-sample.log")
MAX_BYTES = 4 * 1024 * 1024  # ~10 days at 5 s
KEEP_BYTES = 1 * 1024 * 1024


def hwmon(name):
    """Resolve an hwmon dir by its `name` file — hwmonN ordering is not stable."""
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(h + "/name") as f:
                if f.read().strip() == name:
                    return h
        except OSError:
            continue
    return None


def milli(path, default=None):
    """hwmon values are milli-units; plain float, or default if unreadable."""
    try:
        with open(path) as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return default


def uwatt(path):
    """amdgpu power1_* is microwatts on this board (measured 260926)."""
    v = milli(path)
    return v / 1000.0 if v is not None else None


def rd(path, default="?"):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def f(v):
    return f"{v:.1f}" if isinstance(v, float) else "?"


def top_rss(n=2):
    """Top-n processes by RSS in GiB as 'comm:GiB'. /proc scan, no subprocess."""
    best = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/statm") as fh:
                rss = int(fh.read().split()[1])
            if rss <= 262144:  # <= 1 GiB: not worth naming on this box
                continue
            with open(f"/proc/{pid}/comm") as fh:
                best.append((rss, fh.read().strip()))
        except (OSError, ValueError, IndexError):
            continue  # process vanished mid-scan — normal
    best.sort(reverse=True)
    return ",".join(f"{c}:{r / 262144:.1f}" for r, c in best[:n]) or "-"


def sample(sensors):
    edge = milli(f"{sensors['amd']}/temp1_input")
    ppt = uwatt(f"{sensors['amd']}/power1_input")
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return (
        f"{ts} edge={f(edge)}C ppt={f(ppt)}W "
        f"gpu={rd('/sys/class/drm/card0/device/gpu_busy_percent')}% "
        f"nvme={f(milli(sensors['nvme'] + '/temp1_input'))}C "
        f"load1={rd('/proc/loadavg').split()[0]} "
        f"bogus_k10={f(milli(sensors['k10'] + '/temp1_input'))} "
        f"bogus_acpi={f(milli(sensors['acpi'] + '/temp1_input'))} "
        f"big={top_rss()}"
    )


def resolve():
    return {
        "amd": hwmon("amdgpu") or "/dev/null",
        "nvme": hwmon("nvme") or "/dev/null",
        "k10": hwmon("k10temp") or "/dev/null",
        "acpi": hwmon("acpitz") or "/dev/null",
    }


def rotate():
    try:
        size = os.path.getsize(LOG)
        if size <= MAX_BYTES:
            return
        with open(LOG) as fh:
            fh.seek(max(0, size - KEEP_BYTES))
            fh.readline()  # drop the partial first line
            tail = fh.read()
        with open(LOG + ".1", "w") as fh:
            fh.write(tail)
        open(LOG, "w").close()
    except OSError:
        pass


def main():
    if "--tail" in sys.argv:
        k = sys.argv.index("--tail")
        n = int(sys.argv[k + 1]) if k + 1 < len(sys.argv) else 20
        print("\n".join(reversed(open(LOG).read().splitlines()[-n:])))
        return 0

    sensors = resolve()
    if "--once" in sys.argv:
        line = sample(sensors)
        print(line)
        # Self-check: the sensors must resolve, or this tool writes "?" forever
        # and the next cut yields nothing.
        assert "edge=?C" not in line, f"amdgpu hwmon not resolved: {line}"
        assert "gpu=?%" not in line, f"gpu_busy_percent unreadable: {line}"
        assert "ppt=?W" not in line, f"PPT unreadable: {line}"
        # Unit-scale guard: this box never draws outside 5..400 W, so a
        # microwatt/milliwatt mix-up (measured live 260926) fails here.
        ppt = float(line.split("ppt=")[1].split("W")[0])
        assert 5.0 < ppt < 400.0, f"implausible PPT {ppt} W — check power1_* units"
        return 0

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    rotate()
    with open(LOG, "a", buffering=1) as out:
        out.write(f"=== boot {rd('/proc/sys/kernel/random/boot_id')} sampler start ===\n")
        out.flush()
        os.fsync(out.fileno())
        while True:
            out.write(sample(sensors) + "\n")
            out.flush()
            os.fsync(out.fileno())  # the whole point: survive the rail dropping
            rotate()
            time.sleep(INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())