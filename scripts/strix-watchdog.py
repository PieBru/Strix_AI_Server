#!/usr/bin/env python3
"""strix-watchdog.py — keep a text arm answering. One tick per run; a timer runs the ticks.

The contract is the STAMP (§2 of proposals/UNBREAKABLE_WATCHDOG_PROPOSAL_260930.md), not
":8080 answers": no stamp means the operator parked the box on purpose (image mode, an H3
render) and the watchdog has no business starting a 40 GiB model at 03:00.

The probe is functional, never /health: a wedged generation loop answers /health with 200
forever. We reuse the gate's probe_text — one implementation of "this model completed a turn
with a tool call", not two.

    strix-watchdog.py --dry-run     print the action, touch nothing (read this before enabling)
    strix-watchdog.py               one real tick (what the timer calls)

stdlib only, no uv, no venv, no network at start: a unit that has only ever started online is
an untested unit (the qwen-image-test lesson, 260927).
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
# The profile library lives beside this script, so the unit needs no env. When the branch lands
# in Strix_AI_Server this resolves there automatically; an explicit STRIX_PROFILES still wins.
os.environ.setdefault("STRIX_PROFILES", str(REPO / "configs" / "profiles"))
STATE = pathlib.Path(os.path.expanduser("~/.local/state/strix/watchdog.json"))
DISABLE = pathlib.Path(os.path.expanduser("~/.config/strix/watchdog.disable"))
TIERS = ("restart", "emergency", "panic", "shout")
# Consecutive failed probes before acting: one miss on a box mid-render is not an outage.
N_TRIP = int(os.environ.get("STRIX_WATCHDOG_TRIP", "3"))
# After acting, give the load its chance. A watchdog that re-acts every tick flaps the box.
COOLDOWN_S = int(os.environ.get("STRIX_WATCHDOG_COOLDOWN", "900"))
# Same tier reached this many times in a day => structural; stop acting and shout.
MAX_TIER_PER_DAY = 3


def _mod(name, path):
    s = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m  # @dataclass in the loaded file resolves through sys.modules
    s.loader.exec_module(m)
    return m


def libs():
    sp = _mod("strix_profile", REPO / "scripts" / "strix-profile")
    pr = _mod("profile_probes", REPO / "scripts" / "profile_probes.py")
    return sp, pr


def read_state(path=STATE):
    try:
        st = json.loads(path.read_text())
    except (OSError, ValueError):
        st = {}
    if st.get("day") != time.strftime("%Y%m%d"):
        st = {"day": time.strftime("%Y%m%d"), "failures": 0, "tier": 0, "actions": 0,
              "tier_hits": {}, "last_action_ts": 0}
    return st


def write_state(st, path=STATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st) + "\n")
    tmp.replace(path)  # a corrupt watchdog state reads as "never acted" and stamps on the box


def decide(*, disabled, stamp, probe_ok, failures, cooldown_left, slow_but_busy, tier,
           tier_hits=0, n_trip=N_TRIP, tiers=TIERS):
    """(action, reason). Pure: every input is an argument so the ladder is testable without
    a box. This function is the whole policy; everything else is I/O."""
    if disabled:
        return "ignore", "disabled by operator (watchdog.disable / STRIX_WATCHDOG=off)"
    if not stamp:
        return "ignore", "no stamp — the box is parked by hand, that is not our contract"
    if probe_ok:
        return "ok", None
    if failures < n_trip:
        return "watch", f"probe failed {failures}/{n_trip}"
    if cooldown_left > 0:
        return "wait", f"acted {int(cooldown_left)} s ago, giving the load its chance"
    if slow_but_busy:
        return "wait", "listener up and the render queue is busy — slow is not dead"
    if tier_hits >= MAX_TIER_PER_DAY:
        return "shout", f"tier {tiers[tier]} reached {tier_hits}× today — structural, stop acting"
    return tiers[min(tier, len(tiers) - 1)], None


def probe(sp, pr, prof, budget_s):
    """Functional probe of the declared arm. Returns (ok, detail)."""
    try:
        ok, detail = pr.probe_text(prof.text_port, budget_s)
    except Exception as e:  # a probe that cannot run is a failed probe, never a pass
        return False, f"{type(e).__name__}: {e}"
    alias = getattr(prof, "alias", "default")
    return bool(ok), detail


def refused_by_evidence(name, sp):
    """True when the gate measured this profile and it broke. --force must not paper over
    that (proposal §7): a refusal for ABSENCE of evidence is fine, a FAIL is not."""
    try:
        v = sp._gate_verdict(os.uname().nodename, name)
    except Exception:
        return False
    return bool(v) and v.get("verdict") == "FAIL"


def act(action, prof, sp, dry):
    """One action per tick, idempotent, journalled. Returns (done, note)."""
    def run(argv):
        if dry:
            print(f"WOULD RUN  {' '.join(argv)}")
            return 0, "dry run"
        p = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        return p.returncode, " ".join((p.stdout + p.stderr).split())[-200:]

    if action == "restart":
        return run(["systemctl", "--user", "restart", f"{prof.text_arm}.service"])
    if action in ("emergency", "panic"):
        if refused_by_evidence(action, sp):
            return 2, f"{action} has a measured FAIL — advancing, not forcing"
        return run([str(REPO / "scripts" / "strix-profile"), "apply", action, "--force"])
    return 3, "shout: journal ERROR + Doctor banner; no further automated action"


def tick(dry=False, *, spawn=None, probe_fn=None, now=None):
    sp, pr = libs()
    st = read_state()
    disabled = (DISABLE.exists() or os.environ.get("STRIX_WATCHDOG") == "off")
    stamp = sp.read_stamp()
    prof = None
    if stamp:
        try:
            prof = sp.resolve(stamp)
        except Exception as e:
            print(f"stamp '{stamp}' does not resolve: {e}")
            return "ignore"
    budget = int(os.environ.get("STRIX_WATCHDOG_BUDGET", "60"))
    ok, detail = probe_fn(prof, budget) if probe_fn else (
        (False, "no arm declared") if not prof or not prof.text_port else probe(sp, pr, prof, budget))
    cooldown_left = max(0.0, COOLDOWN_S - ((now or time.time()) - st.get("last_action_ts", 0)))
    slow_but_busy = bool(prof and prof.text_port and _listener_up(prof.text_port)
                         and _queue_running())
    action, reason = decide(disabled=disabled, stamp=stamp, probe_ok=ok,
                            failures=st["failures"], cooldown_left=cooldown_left,
                            slow_but_busy=slow_but_busy, tier=st["tier"],
                            tier_hits=st["tier_hits"].get(str(st["tier"]), 0))

    print(f"tick {time.strftime('%H:%M:%S')} stamp={stamp or '-'} probe={'ok' if ok else 'FAIL'}"
          f" {detail or ''} | failures={st['failures']} tier={st['tier']} -> {action}"
          + (f" ({reason})" if reason else ""))

    def save():
        # last_tick_ts is written on EVERY tick, including ignore: "the watchdog is quiet"
        # and "the watchdog is dead" must not look the same in the Doctor.
        if not dry:
            st["last_tick_ts"] = now or time.time()
            write_state(st)

    if action == "ok":
        st.update(failures=0, tier=0)
        save()
        return action
    if action == "watch":
        st["failures"] += 1
        save()
        return action
    if action in ("ignore", "wait"):
        save()
        return action

    rc, note = act(action, prof, sp, dry)
    print(f"  action {action} rc={rc} {note}")
    if not dry:
        acted = st["tier"]  # the tier that was USED, not the next one
        st["actions"] += 1
        st["last_action_ts"] = now or time.time()
        st["tier"] = min(acted + 1, len(TIERS) - 1)
        st["tier_hits"][str(acted)] = st["tier_hits"].get(str(acted), 0) + 1
        save()
    return action


def _listener_up(port):
    import socket
    s = socket.socket()
    s.settimeout(2)
    try:
        return s.connect_ex(("127.0.0.1", int(port))) == 0
    finally:
        s.close()


def _queue_running():
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=4) as r:
            return bool(json.load(r).get("queue_running"))
    except Exception:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the action, touch nothing")
    sys.exit(0 if tick(dry=ap.parse_args().dry_run) else 1)
