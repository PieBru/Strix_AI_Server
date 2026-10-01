#!/usr/bin/env python3
"""Doctor — 24/7 system + inference doctor for strixy-9ad3. Runs independently
of llama-server; will host the auto-improving feature (repo Principles #3).
Single file, stdlib only, htmx 2s poll. LAN-exposed :8667, no auth (op decision).
Panels: system cards (GPU/RAM/disk/CPU), inference cards (arm, service, health,
live tg + draft acceptance from the model-router journal), error banner
(health/service/journal/dmesg), tail-f activity log, operator links (+ /res/*
read-only excerpts: ini header, latest morning report, live sweep results).
Design: session 260913, operator-approved."""
import json, shutil, subprocess, socket, glob, re, html, time, threading, os, sys, shlex
import importlib.machinery, importlib.util
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import unquote, parse_qs, urlparse

REPO = os.path.dirname(os.path.abspath(__file__)).rsplit("/doctor", 1)[0]

# Router unit names this panel watches (journal + is-active). Reference box:
# model-router-pwilkin / model-router-vanilla. This repo's units: llama-hip, llama-vulkan.
# Per-box override: DOCTOR_UNITS env (comma-separated) set in the unit — keeps the
# checkout pristine, no re-edits on git pull (strixy2: q5-serve, q6-serve-192k, ...).
# Fleet units this panel watches (journal + is-active). Gufo era (260925):
# gufo-llm (champion engine, :8080) + gufo-serve (image, :8081); the llama.cpp
# router names stay as fallback. Per-box override: DOCTOR_UNITS env (comma-
# separated) set in the unit — keeps the checkout pristine, no re-edits on
# git pull.
ROUTER_UNITS = tuple(u for u in (os.environ.get("DOCTOR_UNITS") or
    "llama-llm,gufo-llm,27b-collm,gemma-collm,gufo-serve,model-router-pwilkin,model-router-vanilla").split(",") if u)
_JU = [a for u in ROUTER_UNITS for a in ("-u", u)]

# The :8080 text arms, most-preferred first. Both copies of the old hardcoded list
# omitted gemma-collm, so with Gemma live the toggle resolved to a DIFFERENT arm and
# started a second one on a busy port (operator 261001). One source, read by the title
# row and by /llmtoggle alike; per-box override stays DOCTOR_UNITS for the panel rows.
LLM_ARMS = ("27b-collm", "gemma-collm", "gufo-llm", "llama-llm")
ARM_TAG = {"27b-collm": "27b", "gemma-collm": "gemma", "gufo-llm": "gufo", "llama-llm": "webui"}

# The start/stop buttons. One source for the button, the probe that colours it and the
# systemctl argv (operator 261001: lab services kept appearing with no button at all). The
# LAST unit decides "running"; start/stop takes the whole list, so a UI and the engine
# behind it cannot be left half up. The :8080 text arms are NOT here - /llmtoggle resolves
# which arm is live and acts on that one. ltx25-ui is out on purpose (no render path on
# gfx1151, same reason :7864 has no icon) and gradio-v6-relay / routers are plumbing.
SVC_TOGGLES = {
    "demo":    ("demo",    7860, ["gufo-serve", "qwen-image-demo"]),
    "test":    ("test",    7860, ["gufo-serve", "qwen-image-test"]),
    "comfy":   ("comfy",   8188, ["comfyui-h3"]),
    "h3ui":    ("h3ui",    7861, ["h3-video-ui"]),
    "acestep": ("acestep", 7862, ["acestep-serve", "acestep-ui"]),
    "whisper": ("whisper", 7863, ["whisper-stt"]),
    "webui":   ("webui",   3000, ["open-webui"]),
    "sos":     ("sos",     8082, ["sos-collm"]),
}


def _unit(u, verb):
    try:
        return subprocess.run(["systemctl", "--user", verb, u],
                              capture_output=True, text=True, timeout=4).returncode == 0
    except Exception:
        return False


def arm_live():
    """Whichever text arm is active right now, else None."""
    return next((a for a in LLM_ARMS if _unit(f"{a}.service", "is-active")), None)


def arm_target():
    """The arm the toggle acts on: the live one, else the first that exists."""
    return arm_live() or next((a for a in LLM_ARMS if _unit(f"{a}.service", "cat")), LLM_ARMS[0])

def _router_ini():
    # the ini the LIVE router units point at (truth by construction, survives renames)
    try:
        for r in ROUTER_UNITS:
            u = open(f"/home/piero/.config/systemd/user/{r}.service").read()
            m = re.search(r"--models-preset\s+(\S+)", u)
            if m: return m.group(1)
    except Exception: pass
ROUTER_INI = _router_ini() or "/home/piero/Piero/Work/Qwen38/models.ini"
JN = lambda n=300: subprocess.run(["journalctl","--user"]+_JU+["-n",str(n),"--no-pager"],
                                  capture_output=True, text=True, timeout=8).stdout.splitlines()
# 260923: time-windowed journal for the error banner — a line-count window
# (-n 300) on an idle router shows hours-old storm tails forever; 30 min keeps
# the banner fresh-only (stale classes age out, new ones appear instantly).
JN_TW = lambda m=30: subprocess.run(["journalctl","--user"]+_JU+[f"--since=-{m}min","--no-pager"],
                                    capture_output=True, text=True, timeout=8).stdout.splitlines()

PEAKS = {}   # key -> {v: highest SUSTAINED level, t: when set}; accrued in refresh() (always-on sampler)
_HIST = {}   # key -> deque of the last PEAK_N samples; the sustained floor is min(window)
# A peak must be held, not touched (operator 260930): the high-water mark used to follow
# single samples, so one 2 s reading of a transient set the chip for the rest of the day.
# Same logic as the swap-storm latch below — N consecutive samples are a state, one sample
# is a spike. min(window) is the level that held across the whole window, so a spike cannot
# raise the peak and a real plateau converges on its true level within PEAK_N samples (~6 s
# at the 2 s sampler). Cost, accepted: a single-sample I/O burst is no longer a peak — the
# card's live bar still shows it and metrics.csv still keeps every sample.
PEAK_N = 3

# Swap-storm latch (operator 260930): the badge used to follow the instantaneous 2 s
# rate, so it blinked during a storm and was white again before anyone could read it.
# Trip on STORM_N consecutive samples over STORM_MBPS (idle floor measured 260930 is
# 0.00 MB/s, so it cannot trip on noise), then HOLD until the ✕ on the card clears it:
# a past storm is exactly the evidence you want to look at. Survives a Doctor restart.
STORM_MBPS, STORM_N = 1.0, 3
STORM_FILE = os.path.expanduser("~/.local/state/strix/doctor-storm.json")
STORM = {}
try:
    STORM.update(json.load(open(STORM_FILE)))
except Exception:
    pass

def storm_save():
    """Atomic: a half-written latch file would read back as 'no storm' and lose evidence."""
    try:
        os.makedirs(os.path.dirname(STORM_FILE), exist_ok=True)
        with open(STORM_FILE + ".tmp", "w") as f:
            json.dump(STORM, f)
        os.replace(STORM_FILE + ".tmp", STORM_FILE)
    except OSError:
        pass

def vmswap_snapshot():
    """{pid: (comm, VmSwap_kB)} for every readable process that has ANY swap right now.
    Called only while a storm is arming or live (see storm_tick), so the ~1200-file walk
    costs nothing at rest. VmSwap is the only per-process swap counter the kernel exposes
    (/proc/<pid>/io has no swap field), so this is 'who is sitting in swap', which during a
    storm is the same thing as who is pushing it."""
    out = {}
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return out
    for d in pids:
        try:
            with open(f"/proc/{d}/status", errors="ignore") as f:
                name = f.readline().split("\t", 1)[-1].strip()
                kb = 0
                for line in f:
                    if line.startswith("VmSwap:"):
                        kb = int(line.split()[1])
                        break
            if kb:
                out[d] = (name, kb)
        except (OSError, ValueError):
            continue      # process vanished mid-walk, or /proc/<pid> is unreadable
    return out


def storm_tick(r, pg, snap=None):
    """The swap-storm latch, one sample at a time: trip on STORM_N consecutive samples over
    STORM_MBPS, then hold. `r` = MB/s in+out, `pg` = (pswpin, pswpout) cumulative pages.
    `snap` = optional callable -> {pid: (comm, VmSwap_kB)}; it is invoked ONLY while a storm
    is arming or live, and its result names the culprit on the badge (operator 261001: a
    storm that says 30 GiB moved but not WHO moved it sends you hunting with a shell).
    Split out of refresh() so tests/storm_latch_check.py can drive it without the sampler."""
    _SW["hits"] = _SW.get("hits", 0) + 1 if r > STORM_MBPS else 0
    if _SW["hits"] < STORM_N:
        return
    if not STORM.get("t0"):
        STORM.update(t0=time.time(), peak=r, moved=0.0, p0=list(pg), wt=0.0)
        # A new storm must not inherit the previous one's culprit (a latch file can outlive
        # the ✕ if Doctor was mid-write; a wrong name is worse than no name).
        for _k in ("who", "who_kb", "base", "mx"):
            STORM.pop(_k, None)
        storm_save()
    else:
        moved = ((pg[0] - STORM["p0"][0]) + (pg[1] - STORM["p0"][1])) * 4096 / 2**20
        was = (STORM.get("moved", 0.0), STORM.get("peak", 0.0))
        STORM["moved"] = max(moved, was[0])          # the card always shows the current tally
        STORM["peak"] = max(r, was[1])
        if (moved > was[0] + 64 or r > was[1] * 1.2) \
           and time.time() - STORM.get("wt", 0) > 30:   # ponytail: 30 s write ceiling
            STORM["wt"] = time.time()
            storm_save()
    # Culprit attribution: the largest VmSwap GROWTH since the storm tripped, not the largest
    # resident swapper (an idle 6 GiB tenant that never moved would otherwise out-shout the
    # process that actually paged 30 GiB). ponytail: keyed by pid, so pid reuse inside one
    # storm could misname it; storms here last minutes and pids are not recycled that fast.
    if snap is not None:
        try:
            procs = snap() or {}
        except Exception:
            procs = {}
        if procs:
            base = STORM.setdefault("base", {p: kb for p, (_, kb) in procs.items()})
            mx = STORM.setdefault("mx", {})
            for pid, (comm, kb) in procs.items():
                d = kb - base.get(pid, 0)
                if d > mx.get(pid, [0])[0]:
                    mx[pid] = [d, comm]
            if len(mx) > 24:      # the latch file is written every 30 s: keep it small
                STORM["mx"] = mx = dict(sorted(mx.items(), key=lambda kv: -kv[1][0])[:12])
            if mx:
                d, comm = max(mx.values())
                if d > 1048576:   # only name someone above 1 GiB of growth
                    STORM["who"], STORM["who_kb"] = comm, d

def track(key, val):
    """Update a card's high-water mark — sustained levels only, see PEAK_N."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return
    w = _HIST.setdefault(key, deque(maxlen=PEAK_N))
    w.append(v)
    if len(w) < PEAK_N:
        return                      # nothing is known about a level until the window is full
    s = min(w)
    p = PEAKS.get(key)
    if p is None or s > p["v"]:
        PEAKS[key] = {"v": s, "t": time.time()}

def gpu():
    # pure sysfs (UMA truth 260914): rocm-smi's VRAM% is the 1GiB carve-out (always ~90%),
    # not real use; GTT counters are the actual GPU-addressable memory (matches nvtop).
    try:
        d = "/sys/class/drm/card0/device/"
        pct = lambda p: int(open(p).read())
        gpup = pct(d + "gpu_busy_percent")
        used, tot = pct(d + "mem_info_gtt_used"), pct(d + "mem_info_gtt_total")
        vram = f"{100 * used // tot}%"
        h = next(p for p in __import__('glob').glob('/sys/class/hwmon/hwmon*/')
                 if open(p + 'name').read().strip() == 'amdgpu')
        temp = pct(h + 'temp1_input') / 1000.0
        power = pct(h + 'power1_average') / 1e6
        return f"{gpup}%", vram, f"{temp:.1f}\N{DEGREE SIGN}C", f"{power:.1f}W"  # gpu%, gtt%, temp, power
    except Exception: pass
    return "—","—","—","—"

def ram_disk_cpu():
    with open("/proc/meminfo") as f: d = dict(l.split(":",1) for l in f)
    tot, avail = int(d["MemTotal"].split()[0]), int(d["MemAvailable"].split()[0])
    swt, swf, swc, zaw = (int(d.get(k, "0 kB").split()[0]) for k in ("SwapTotal", "SwapFree", "SwapCached", "Zswapped"))
    swu = max(swt - swf - swc, 0)          # cached swap pages are reclaimable, not "used"
    # Zswapped = uncompressed bytes of the pages zswap is holding compressed IN RAM: swap slots
    # that never reached the NVMe. htop subtracts it too (linux/Platform.c: "subtract Zswapped from
    # SwapUsed"), which is why htop and `free` disagree on this box (measured 260930: 121 MiB vs
    # 1461 MiB). We keep the kernel's committed figure and name the zswap share instead of hiding
    # it — the committed number is the one that cannot understate how close we are to out of swap.
    s = shutil.disk_usage("/"); ld = open("/proc/loadavg").read().split()[0]
    return (f"{100*(tot-avail)/tot:.0f}%", f"{(tot-avail)/1048576:.0f}/{tot/1048576:.0f} GiB",
            f"{100*s.used/s.total:.0f}%", f"{s.free/2**30:.0f} GiB free", ld,
            f"{100*swu/swt:.0f}%" if swt else "0%", f"{swu/1048576:.1f}/{swt/1048576:.0f} GiB"
            + (f" \u00b7 {zaw/1048576:.1f} in zswap" if zaw > 51200 else ""))  # bar parses the number before '/', suffix-safe

def _load_mod(name, path):
    """Import a sibling script that is not an importable module name (strix-profile has no
    .py). sys.modules must be set or @dataclass inside the loaded file cannot resolve."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


SP = _load_mod("strix_profile", f"{REPO}/scripts/strix-profile")
GATE = _load_mod("profile_gate", f"{REPO}/scripts/profile-gate.py")


def profile_line_html(stamp, missing, extra, gate):
    """One line in the ARM card: what the stamp claims, whether the gate still stands for it,
    and where reality disagrees. Everything is escaped — there is no auth on this LAN, so the
    profile name is somebody-else-editable text appearing in a page."""
    if not stamp:
        return '<span class="m">no profile — units were started by hand</span>'
    parts = [f"profile <b>{html.escape(stamp)}</b>"]
    if gate:
        v = str(gate.get("verdict", "?"))
        cls = "bad" if v == "FAIL" else ("m" if v == "INCONCLUSIVE" else "on")
        parts.append(f'gate <b class="{cls}">{html.escape(v)}</b> '
                     f'{html.escape(str(gate.get("started", ""))[:10])}'
                     f' (peak GTT {gate.get("peak_gtt_pct")} %)')
    else:
        parts.append('gate <b class="m">never gated</b>')
    if missing:
        parts.append('<span class="bad">DRIFT: missing ' + html.escape(", ".join(missing))
                     + "</span>")
    if extra:
        parts.append('<span class="bad">DRIFT: extra ' + html.escape(", ".join(extra))
                     + "</span>")
    return " · ".join(parts)


def profile_select_html(names, current):
    """The dropdown in the title row. panic and emergency are always offered even if the
    profiles dir is gone or unreadable — they are the way out, not a preference."""
    opts = list(dict.fromkeys(list(names) + ["panic", "emergency"]))
    # A stamp that is not in the list must not fall back to the first option: the row would
    # claim a profile nobody applied. Say --- and let the next poll be right.
    ph = "" if current in opts else '<option selected disabled>---</option>'
    return ('<select id="prof" onchange="profGo(this)">' + ph + "".join(
        f'<option value="{html.escape(n)}"' + (' selected' if n == current else '') +
        f'>{html.escape(n)}</option>' for n in opts) + "</select>")


# What `/` puts in the chip before the first poll. The first paint used to render the real
# dropdown, and a hard refresh showed a profile that was not applied: Chrome restores the
# <select>'s previous selection over the `selected` attribute when it re-renders the same
# URL, so the honest value was overwritten by whatever the tab last held ("panic", here).
# A one-option placeholder cannot be restored to a lie; #profchip pulls the truth on load.
PROF_PLACEHOLDER = '<select id="prof" disabled><option>---</option></select>'


def profile_starts():
    """{profile name: the units it starts}. Files first, then the built-ins the panel offers
    but that have no .ini. Needed because the reply must match the action: 'off' has an empty
    allow-list, so applying it stops thirteen units in a couple of seconds, and answering
    "weights take a minute" to that is a lie the operator sees immediately (261001)."""
    out = {n: list(p.start) for n, p in SP.load_profiles(SP.PROFILES_DIR).items()}
    for n, p in SP.BUILTIN.items():
        out.setdefault(n, list(p.start))
    return out


def profile_apply(path, known, spawn, preflight=None):
    """POST /profile?name=X -> (code, body). `known` is {name: units started}; the name is
    checked against its keys BEFORE anything is spawned: with no auth on this box the
    validator is the only thing between a stray request and systemctl. Returns (404, ...)
    and spawns nothing otherwise.

    `preflight` runs `apply --dry-run` and returns (rc, text). A detached apply cannot report
    its own outcome, and answering "starting profile 'panic'…" when the gate is about to
    refuse it is the same lie as /health on a wedged arm: the card keeps saying the old
    profile and nobody knows why. So the refusal is said here, in the message the page
    already shows, and the force decision stays in the CLI where it is typed deliberately.
    """
    name = (parse_qs(urlparse(path).query).get("name") or [""])[0]
    if name not in known:
        return 404, f"unknown profile {name!r}"
    if preflight is not None:
        rc, out = preflight(name)
        if rc != 0:
            # The dry run prints the whole plan AFTER the reason, so the tail of it is the
            # least useful line: show the WOULD REFUSE line, which is the actual answer.
            why = next((ln.strip() for ln in out.splitlines() if "refuse" in ln.lower()),
                       " ".join(out.split())[-280:])
            return 409, "NOT applied — " + why.lower().replace("would refuse", "").strip()
    spawn(name)
    # A profile that starts units loads weights; one with an empty allow-list ('off') only
    # stops things and is done in seconds. Say which one happened.
    if known[name]:
        return 200, f"starting profile '{name}'… (weights take a minute; the card updates itself)"
    return 200, f"stopping everything for '{name}'… (a few seconds; the card updates itself)"


def apply_dry_run(name):
    """(rc, output) of `strix-profile apply NAME --dry-run` — pure, touches nothing."""
    p = subprocess.run(["/bin/bash", "-c", f"{REPO}/scripts/strix-profile apply "
                        f"{shlex.quote(name)} --dry-run"], capture_output=True, text=True,
                       timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# Mirror of TIERS in scripts/strix-watchdog.py. ponytail: duplicated rather than imported so
# the panel never depends on the actor it reports on; share a module if the ladder ever grows.
WD_TIERS = ("restart", "emergency", "panic", "shout")
WD_STATE = os.path.expanduser("~/.local/state/strix/watchdog.json")
SWITCH_LOG = os.path.expanduser("~/.local/state/strix/profile-switches.jsonl")
ANVIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anvil")
# The arm /llm/ forwards to. A name, not a literal in the handler, so tests can point it
# at a throwaway server instead of at the live :8080 (tests/llm_proxy_check.py).
LLM_UP = os.environ.get("STRIX_LLM_UP", "http://127.0.0.1:8080")


def watchdog_state():
    """(state dict or None, timer enabled?) — read once per refresh, like profile_state."""
    try:
        st = json.loads(open(WD_STATE).read())
    except (OSError, ValueError):
        st = None
    on = subprocess.run(["systemctl", "--user", "is-enabled", "strix-watchdog.timer"],
                        capture_output=True).returncode == 0
    return st, on


def watchdog_html(st, timer_on, now):
    """One line under the profile line: is the watchdog alive, and what did it do today.
    A dead watchdog is the failure nobody notices — the box looks fine and nothing is
    watching it — so 'off' and 'silent' are said out loud instead of rendering nothing."""
    if not timer_on:
        return ('<span class="m">watchdog <b>off</b> — '
                'systemctl --user enable --now strix-watchdog.timer</span>')
    if not st or not st.get("last_tick_ts"):
        return '<span class="bad">watchdog timer ON but no tick has ever been recorded</span>'
    age = int(now - st["last_tick_ts"])
    alive = age < 300  # timer fires every 2 min; 5 without a tick means the tick is not running
    out = f'watchdog <b class="{"on" if alive else "bad"}">{"ok" if alive else "SILENT"}</b> {age} s'
    if st.get("actions"):
        hits = " ".join(f'{WD_TIERS[int(k)]}×{v}' for k, v in sorted(st.get("tier_hits", {}).items())
                        if k.isdigit() and int(k) < len(WD_TIERS))
        out += f' · <b class="bad">{st["actions"]} action(s) today</b>' + (f' ({hits})' if hits else "")
    return out


def profile_state():
    """(stamp, missing, extra, gate) for this box. Called by the collector, not per render:
    it probes every managed unit with systemctl."""
    stamp = SP.read_stamp()
    if stamp is None:
        return None, [], [], None
    try:
        prof = SP.resolve(stamp)
    except Exception as e:
        return stamp, [], [], None
    live, extra = SP.live_units(prof)
    d = SP.drift(prof, live)
    return stamp, d["missing"], [u for u in extra if u in SP.MANAGED_UNITS], \
        GATE.gate_verdict(socket.gethostname(), stamp)


def _spawn_apply(name):
    """Detached, like /restart: the request must never wait on a model load. `apply` can take
    minutes (weights), and a browser POST that blocks is a browser that retries."""
    subprocess.Popen(["/bin/bash", "-c",
                      f"sleep 1; {REPO}/scripts/strix-profile apply {shlex.quote(name)}"],
                     start_new_session=True)


CACHE = {"h": "?", "svc": "?", "arm": "?", "tg": None, "acc": None, "jn": [], "errs": [], "gpu_err": [], "sig": None, "sig_t": 0.0}

TG_H, ACC_H = deque(maxlen=120), deque(maxlen=120)  # ~4 min at live pace
_IO = {"t": 0.0, "r": 0, "w": 0}   # prev /sys/block/nvme0n1/stat snapshot for I/O deltas

_SW = {"t": 0.0, "i": 0, "o": 0}   # prev /proc/vmstat pswpin/pswpout snapshot for swap-rate deltas

def _sw_pages():
    # /proc/vmstat: pswpin/pswpout are CUMULATIVE pages swapped in/out since boot
    try:
        d = dict(l.split() for l in open("/proc/vmstat") if l.startswith(("pswpin", "pswpout")))
        return int(d["pswpin"]), int(d["pswpout"])
    except Exception: return None

def _io_bytes():
    # /sys/block/nvme0n1/stat fields: reads, merges, sectors_read, ... writes, merges, sectors_written (512B sectors)
    try:
        f = open("/sys/block/nvme0n1/stat").read().split()
        return int(f[2]) * 512, int(f[6]) * 512   # bytes read, bytes written
    except Exception: return None

def swap_body(st, si, so):
    """The SWAP card body: the GiB figure, and the in/out rate ONLY when it survives being
    printed. The gate used to be `if si or so`, which is true for a trickle - and 0.3 MB/s
    renders as "in/out 0/0 MB/s", an alarm about nothing (operator 261001). Rounding the
    same way the format does is what makes 0/0 unrepresentable."""
    return f"{st.replace(' GiB','')}" + (f" · in/out {si:.0f}/{so:.0f} MB/s" if round(si) or round(so) else "")


ARM_SORT_MODE = 0   # server-side row order: 0 = recency (default), 1 = load time
BENIGN = re.compile(r"request cancelled while waiting for model|requires ctx_other|failed to measure the memory of the extra model"
                    r"|attention rotation force disabled|Qwen-VL models require|image-min-tokens|issues/16842"
                    r"|preserving reasoning|exceeds the available context size"
                    # The arm's HF model manager phoning home when something opens its /models —
                    # the llama-ui's own model picker does exactly that. This box has no internet
                    # by design, so the lookup always fails and the UI still works: 9 lines in 7 d,
                    # all of them from opening http://<box>:8080/ (seen 260930).
                    r"|http client error: Could not establish connection")  # routine: arm-swap probe race, memory-fit pre-pass, per-load advisories, client sent an oversized request (probe noise, not a fault)

def _models_max():
    try:
        m = re.search(r"(?m)^\s*models-max\s*=\s*(\d+)", open(ROUTER_INI).read())
        return int(m.group(1)) if m else 1
    except Exception: return 1
MODELS_MAX = _models_max()

def _resident():
    # live truth from /proc: child llama-server procs carry --alias (router
    # main doesn't); gufo era: gufo serve llm procs → "gufo:QUANT·MTPdN·cC"
    out = []
    for c in glob.glob("/proc/[0-9]*/cmdline"):
        try: s = open(c, "rb").read().decode(errors="ignore").replace("\0", " ")
        except Exception: continue
        if "gufo serve llm" in s:
            def _f(f, d="?"):
                m = re.search(rf"{f} (\S+)", s)
                return m.group(1) if m else d
            q = os.path.basename(os.path.dirname(_f("--model"))) or "?"
            out.append(f"gufo:{q}\u00b7MTPd{_f('-d')}\u00b7c{_f('-c')}")
            continue
        if "llama-server" in s and "--alias" in s:
            a = s.split("--alias")[1].split()[0].strip()
            if a and a not in out: out.append(a)
    return out

def _loads_recent():
    # time-window (6h) load events — llama router spawns + gufo load_completed
    try:
        out = subprocess.run(["journalctl","--user"]+_JU+["--since","-6h","--no-pager"],
                             capture_output=True, text=True, timeout=10).stdout.splitlines()
    except Exception:
        return CACHE.get("loads", [])
    loads, p2a, pt = [], {}, {}
    def _sec(hms): return int(hms[:2])*3600+int(hms[3:5])*60+int(hms[6:8])
    for l in out:
        m = re.match(r"^(\w+\s+\d+)\s+(\d\d:\d\d:\d\d)", l)
        ts = _sec(m.group(2)) if m else None
        ep = _epoch(m.group(1), m.group(2)) if m else None
        if (s := re.search(r"spawning server instance with name=(\S+) on port (\d+)", l)):
            p2a[s.group(2)] = s.group(1); pt[s.group(2)] = ts
        elif (g := re.search(r"gufo\[\d+\].*load_completed.*elapsed_ms=(\d+)", l)):
            if ts is not None:
                # gufo-serve emits the same event for the image model; without the
                # model= field these rows showed up as "? 0s" in the ARM table (260930).
                mdl = re.search(r"model=(\S+)", l)
                loads.append({"arm": mdl.group(1) if mdl else CACHE.get("arm", "gufo"),
                              "s": max(int(g.group(1))//1000, 0), "t": ts, "i": len(loads), "e": ep})
        elif (r := re.search(r".*\[(\d+)\].*llama_server: model loaded", l)) and r.group(1) in pt:
            a0, t0, t1 = p2a.get(r.group(1), "?"), pt.pop(r.group(1)), ts
            if t0 is not None and t1 is not None:
                loads.append({"arm": a0, "s": max(t1 - t0, 0), "t": t1, "i": len(loads), "e": ep})
    loads_h = [d for d in loads][-10:][::-1]     # last 10 load EVENTS, newest first
    return loads_h


def _epoch(dstr, hms):
    """Journal short-format stamps carry no year: assume this one, and step back a year when
    that would land in the future (the Jan-1 edge of a 6 h window)."""
    try:
        e = int(time.mktime(time.strptime(f"{time.localtime().tm_year} {dstr} {hms}",
                                          "%Y %b %d %H:%M:%S")))
        return e - 365 * 86400 if e > time.time() + 3600 else e
    except ValueError:
        return 0


def _switches_recent(hours=6):
    """The apply/rollback timeline that strix-profile appends: what the box was switched to,
    how many units moved, when. Merged with the model loads so one table answers 'what
    happened to this box recently' — a mapped image load is noise next to a profile switch."""
    out = []
    try:
        lines = open(SWITCH_LOG).read().splitlines()[-40:]
    except OSError:
        return out
    cut = time.time() - hours * 3600
    for l in lines:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if d.get("at", 0) < cut:
            continue
        out.append({"arm": "\u2192 " + (d.get("to") or "?") + (" (rollback)" if d.get("why") else ""),
                    "s": -1, "t": int(d["at"]) % 86400, "e": int(d["at"]),
                    "d": f"+{len(d.get('started') or [])} \u2212{len(d.get('stopped') or [])}"})
    return out


def refresh():
    try:
        _g = gpu(); _r = ram_disk_cpu()
        track("VRAM", int(_g[1].strip("%") or 0))  # gpu_busy_percent is not tracked: see sysrow
        track("GPU temp", float(_g[2][:-2] or 0)); track("GPU power", float(_g[3][:-1] or 0))
        track("RAM", int(_r[0].strip("%") or 0)); track("SWAP", int(_r[5].strip("%") or 0))
        track("DISK", int(_r[2].strip("%") or 0)); track("CPU", float(_r[4]))
    except Exception: pass
    sw = _sw_pages()
    if sw and _SW["t"]:
        dt = max(time.time() - _SW["t"], 1e-3)
        CACHE["swio"] = (max(sw[0] - _SW["i"], 0) * 4096 / 1e6 / dt, max(sw[1] - _SW["o"], 0) * 4096 / 1e6 / dt)
    if sw: _SW.update(t=time.time(), i=sw[0], o=sw[1])
    io = _io_bytes()
    if io and _IO["t"]:
        dt = max(time.time() - _IO["t"], 1e-3)
        CACHE["io"] = (max(io[0] - _IO["r"], 0) / 1e6 / dt, max(io[1] - _IO["w"], 0) / 1e6 / dt)
    if io: _IO.update(t=time.time(), r=io[0], w=io[1])
    if CACHE.get("io"): track("DISK I/O", sum(CACHE["io"]))
    if CACHE.get("swio"): track("SWAP rate", sum(CACHE["swio"]))
    # Storm latch: held until cleared by hand (see storm_tick + the badge on the SWAP card).
    storm_tick(sum(CACHE.get("swio", (0.0, 0.0))), sw or (0, 0), vmswap_snapshot)
    if CACHE.get("tg"): track("LIVE tg", CACHE["tg"][2])
    if CACHE.get("acc"): track("DRAFT acc", CACHE["acc"][0])
    try:
        _hr = urlopen("http://127.0.0.1:8080/health", timeout=4)  # gufo and llama-router share the contract
        h = json.load(_hr)["status"]
        CACHE["srv"] = _hr.headers.get("Server", "")  # "llama.cpp" -> that arm ships its own web UI on :8080
    except Exception:
        h = "unreachable"; CACHE["srv"] = ""
    try:
        _gufo = subprocess.run(["systemctl", "--user", "is-active", "gufo-llm"],
                               capture_output=True, text=True, timeout=4).stdout.strip() == "active"
    except Exception: _gufo = False
    try:
        _llm_any = _gufo or subprocess.run(["systemctl", "--user", "is-active", "llama-llm"],
                               capture_output=True, text=True, timeout=4).stdout.strip() == "active"
    except Exception: _llm_any = _gufo
    try: svc = next((s for s in (
                subprocess.run(["systemctl","--user","is-active",u],
                               capture_output=True, text=True, timeout=4).stdout.strip()
                for u in (f"{r}.service" for r in ROUTER_UNITS))
                if s == "active"), "inactive")
    except Exception: svc = "?"
    jn = JN()
    spawned = [m.group(1) for l in jn if (m := re.search(r"spawning server instance with name=(\S+)", l))]
    arms, seen = [], set()
    for a in reversed(spawned):            # newest first, distinct, resident = last MODELS_MAX
        if a not in seen: arms.append(a); seen.add(a)
    arms = arms[:MODELS_MAX]
    res = CACHE.get("res") or []
    if _gufo:
        arm = next((a for a in res if a.startswith("gufo:")), "gufo")   # gufo era: arm = live proc truth
    else:
        arm = arms[0] if arms else "?"
    if time.time() - CACHE.get("loads_t", 0) > 30:
        CACHE["loads"] = _loads_recent(); CACHE["loads_t"] = time.time()
    CACHE["res"] = _resident()
    CACHE["prof"] = profile_state()   # stamp vs truth vs last gate; probes units, so only here
    CACHE["wd"] = watchdog_state()
    tg = acc = None
    for l in reversed(jn):
        if tg is None and (m := re.search(r"print_timing: id\s+\d+ \| task\s+(\d+) \| n_gen =\s*(\d+), tg =\s*([\d.]+)", l)):
            tg = (m.group(1), int(m.group(2)), float(m.group(3)))
        if acc is None and (m := re.search(r"draft acceptance = ([\d.]+) .*mean len =\s*([\d.]+)", l)):
            acc = (float(m.group(1)), float(m.group(2)))
        if tg and acc: break
    benign = BENIGN
    errs = [l for l in JN_TW(30) if re.search(r"\bERROR\b|error:|failed|fatal", l, re.I) and not benign.search(l)][-5:]
    try:
        dmesg = subprocess.run(["dmesg","--since","-5min"], capture_output=True, text=True, timeout=4).stdout
        gpu_err = [l for l in dmesg.splitlines() if "amdgpu" in l and re.search(r"error|fault|timeout|hang", l, re.I)][-3:]
    except Exception: gpu_err = []
    CACHE.update(h=h, svc=svc, arm=arm, arms=arms, gufo=_gufo, llm_any=_llm_any, tg=tg, acc=acc, jn=jn, errs=errs, gpu_err=gpu_err)
    sig = (arm, tg[:2] if tg else None)          # append chart point only when journal advanced
    if sig != CACHE["sig"]:
        CACHE["sig"] = sig
        CACHE["sig_t"] = time.time()
        now = time.time()
        if tg: TG_H.append((now, tg[2]))
        if acc: ACC_H.append((now, acc[0]))

def _sampler():
    while True:
        try: refresh()
        except Exception: pass
        time.sleep(2)

def inference():
    if CACHE["jn"] == []: refresh()
    return CACHE["h"], CACHE["svc"], CACHE["arm"], CACHE["tg"], CACHE["acc"], CACHE["jn"], CACHE["errs"], CACHE["gpu_err"]

def uptime_str():
    # Machine uptime. It used to be substituted once by `/` and froze at page load; the
    # operator moved it onto the control bar (261001), which is polled, so it ticks now.
    try:
        t = float(open("/proc/uptime").read().split()[0])
    except Exception:
        return "up ?"
    return f"up {int(t//86400)}d {int(t%86400//3600)}h {int(t%3600//60)}m"

def boxinfo(vh=""):
    # The title-row controls (operator 260925 as a footer, 261001 moved up when the footer
    # was deleted): the lab icon buttons AND the llm/image swap buttons. The units carry
    # Conflicts=, so each start tears the other side down - the dashboard just calls
    # systemctl. Box identity is the h1 itself, so nothing else survives here.
    #
    # The icons are inside THIS polled fragment on purpose (operator 261001): they used to
    # be rendered once by `/`, outside the poll, so starting any profile left every icon
    # frozen at its page-load colour until a hard refresh. `/` still server-renders them as
    # the span's initial content, so the first paint is not a 5 s hole.
    vh = vh or socket.gethostname()
    def _btn(path, label, on=False):
        # `on` is the unit's real state, not the glyph: green text while it runs, the same
        # grey as everything else when it does not (operator 261001).
        return (f'<button class="cp{" on" if on else ""}" onclick="'
                f'this.textContent=\'working…\';fetch(\'{path}\',{{method:\'POST\'}})'
                f'.then(()=>setTimeout(()=>window.dispatchEvent(new Event(\'box-refresh\')),3000))'
                f'.catch(()=>this.textContent=\'failed\')">{label}</button>')
    _eps = []
    # LLM arm toggle (260925; 260926 +27b-collm co-resident arm; 261001 moved into the
    # title row when the footer went). Label carries the state of whichever arm is LIVE;
    # the old "open ↗" link is gone because the 🤖 icon opens the same port off the
    # request Host, which works from a LAN browser too.
    _arm = arm_target()
    _live = _arm == arm_live()
    _lbl = ARM_TAG.get(_arm, "llm")
    _eps.append(_btn("/llmtoggle", ("⏹ " if _live else "▶ ") + f"{_lbl} :8080", _live))
    for _key, (_name, _port, _units) in SVC_TOGGLES.items():
        _dec = f"{_units[-1]}.service"
        if not _unit(_dec, "cat"):      # not installed on this box -> no button
            continue
        _on = _unit(_dec, "is-active")
        _eps.append(_btn(f"/svctoggle?u={_key}", ("⏹ " if _on else "▶ ") + f"{_name} :{_port}", _on))
    # ComfyUI :8188, ACE-Step :7862 and Open WebUI :3000 used to be links here. They are
    # icon buttons in the same row now (LAB_UI), which also shows them when stopped.
    up8080 = port_up(8080)
    # Only what answers gets a button (operator 261001): a grey icon you cannot open is
    # decoration, and the start/stop line below is where a stopped unit is started.
    robot = (f'<a class="lab" href="http://{vh}:8080/" target="_blank" rel="noopener" '
             f'title="AI chat - the llama-server arm on :8080">\U0001F916 llm</a>') if up8080 else ""
    # Two groups (operator 261001): the icons OPEN a webui, the word buttons START or STOP a
    # unit. The CSS puts .opens on the bar's first line and gives .tog its own line under it.
    return (f'<span class="opens">{ANVIL_BTN}{robot}{lab_ui_html(vh)}</span>'
            f'<span class="up">{uptime_str()}</span>'
            f'<span class="tog">' + " ".join(_eps) + "</span>")

# The Anvil button opens the vendored console and is always up, so it used to sit in the
# template, outside the polled #hact. That made it the only thing on the bar's left margin:
# both polled lines (opens, start/stop) started ~80px to its right. It is now the first item
# of .opens, so the two lines and the anvil share one left edge. The glyph is the same path
# as Anvil's own favicon (title_row_check pins the two together).
ANVIL_BTN = ('<a class="anv" href="/anvil" target="_blank" rel="noopener" '
             'title="Anvil - chat + agent console (vendored, talks to the arm on :8080)">'
             # One literal: title_row_check greps this path out of the source and pins it
             # against Anvil.html's favicon, so wrapping it mid-path breaks that check.
             '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5v5c4.03 2.47-.56 4.97-3 6v3h15v-3c-6.41-2.73-3.53-7 1-8V5zM2 6c.81 2.13 2.42 3.5 5 4V6z"/></svg>anvil</a>')


def stats():
    _gp, vr, gt, gpw = gpu(); rp, rt, dp, dt, ld, sp, st = ram_disk_cpu()
    h, svc, arm, tg, acc, jn, errs, gpu_err = inference()
    bar = lambda p, c=None: f'<div class="bar"><i style="width:{min(max(p,0),100)}%;{f"background:{c}" if c else ""}"></i></div>'
    heat = lambda v: f"hsl({120-1.2*min(max(v,0),100)},90%,55%)"
    # VRAM zones (operator 260922): green <90 is the intended-usage zone,
    # yellow 90-95 is the caution band, red >95 is where the danger starts.
    heat_vram = lambda v: "hsl(120,90%,55%)" if v < 90 else ("hsl(60,90%,55%)" if v <= 95 else "hsl(0,90%,55%)")
    # DISK zones (operator 260922): 80% is normal for an LLM-serving disk —
    # green to 80, yellow to 90, red beyond.
    heat_disk = lambda v: "hsl(120,90%,55%)" if v < 80 else ("hsl(60,90%,55%)" if v <= 90 else "hsl(0,90%,55%)")
    # RAM zones (operator 260922; red threshold raised to >95 on 260923):
    # RAM is there to be used — green to 80, yellow to 95, red beyond
    # (zram-backed box; ~95% is where reclaim pressure starts to bite).
    heat_ram = lambda v: "hsl(120,90%,55%)" if v < 80 else ("hsl(60,90%,55%)" if v <= 95 else "hsl(0,90%,55%)")
    # DISK I/O zones (operator-approved batch 260922): saturation semantics
    # against the 500 MB/s bar ceiling — green <250, yellow to 500, red pegged
    # (sustained red while serving = the row-eviction streaming disease).
    heat_io = lambda v: "hsl(120,90%,55%)" if v < 50 else ("hsl(60,90%,55%)" if v < 100 else "hsl(0,90%,55%)")
    # SWAP zones (operator 260922): swap is an emergency resource, graded in
    # ABSOLUTE GiB not percent — green to 0.5 (OS noise), yellow to 2, red
    # beyond (may signal a loading problem). The bar fills toward the 2 GiB
    # red threshold so the emergency scale is readable at a glance.
    heat_swap = lambda g: "hsl(120,90%,55%)" if g < 0.5 else ("hsl(60,90%,55%)" if g <= 2 else "hsl(0,90%,55%)")
    def storm_html():
        """(title extra, value extra) for the latched swap storm: red while still over the
        line, amber once it subsided, plus the ✕ that clears the latch by hand."""
        if not STORM.get("t0"): return "", ""
        live = sum(CACHE.get("swio", (0.0, 0.0))) > STORM_MBPS
        badge = '<span class="bad">STORM</span>' if live else '<span style="color:#d9a441">STORM past</span>'
        btn = ('<button class="cp" style="float:right;margin-left:6px" onclick="stormReset(this)"'
               ' title="clear the storm latch">\u2715</button>')
        det = (f" · since {time.strftime('%H:%M:%S', time.localtime(STORM['t0']))}"
               f" · peak {STORM.get('peak', 0):.0f} MB/s · {STORM.get('moved', 0)/1024:.1f} GiB moved"
               + (f" · <b>{html.escape(STORM['who'])}</b> {STORM['who_kb']/1048576:.1f} GiB"
                  if STORM.get("who") else ""))
        return f"{btn}{badge}", det
    card = lambda l, v, b="", w=1, h=1: f'<div class="card"{f" style=\"grid-column:span {w}{f';grid-row:span {h}' if h>1 else ''}\"" if w>1 or h>1 else ""}><b>{l}</b><span>{v}</span>{b}</div>'
    try: tm = float(gt[:-2]) if gt.endswith("°C") else 0
    except ValueError: tm = 0
    try: pw = float(gpw[:-1]) if gpw.endswith("W") else 0
    except ValueError: pw = 0
    NCPU = os.cpu_count() or 1
    cpup = min(float(ld)/NCPU*100, 100)
    def pchip(key, unit="", fmt="{:.0f}", hf=None, xform=lambda v: v):
        """Peak chip + per-card reset button, both right-aligned at the card title.
        For float:right the source order is reversed — the button is emitted
        first so it lands rightmost (the card edge) and the peak sits just left
        of it; the title text stays left-aligned.
        hf = the card's bar heat fn; xform converts the peak's native unit into
        the quantity the bar feeds hf (260923: chip graded like the bar)."""
        p = PEAKS.get(key)
        if not p or p["v"] <= 0: return ""
        t = time.strftime("%H:%M", time.localtime(p["t"]))
        c = ""
        if hf:
            col = hf(xform(p["v"]))
            m = re.match(r"hsl\(([\d.]+)", col)
            # 260923 (revised ×2): grey through the whole green range incl.
            # light-green (hue > 60); colorize only from true yellow up to red.
            # Peaks that never left the green zone are not shown at all — the
            # operator's rule: only "it reached at least yellow" is interesting.
            if m and float(m.group(1)) <= 60:
                c = f";color:{col}"
        if not c:
            return ""
        return (f'<button class="cp" style="float:right;margin-left:6px" onclick="peakReset(this,\'{key}\')" title="reset peak">↺</button>'
                f'<i class=pk style="float:right{c}">peak {fmt.format(p["v"])}{unit} {t}</i>')
    # No "GPU busy" card: on this APU gpu_busy_percent reads 100 whenever any process holds
    # /dev/kfd, idle or not (measured 260930: flat 100 across 41 W idle and a 111 W generation).
    # A permanently red card is not an alarm, it is the loss of one. GTT (VRAM) and power are the
    # two GPU signals that actually move here; the raw counter still lands in metrics.csv.
    sysrow = (card("VRAM" + pchip("VRAM", "%", hf=heat_vram), vr, bar((vv := int(vr.strip("%") or 0)), heat_vram(vv)))
              + card("GPU temp" + pchip("GPU temp", "°C", hf=heat), gt, bar(tm, heat(tm))) + card("GPU power" + pchip("GPU power", "W", hf=heat_power), gpw, bar(pw / 140 * 100, heat_power(pw)))
              + card("RAM · GiB" + pchip("RAM", "%", hf=heat_ram), f"{rp} · {rt.replace(' GiB','')}", bar((rv := int(rp.strip("%") or 0)), heat_ram(rv)))
              + card("SWAP · GiB" + pchip("SWAP", "%", hf=heat_swap, xform=lambda v: v*64//100) + pchip("SWAP rate", " MB/s", "{:.0f}") + storm_html()[0],
                     swap_body(st, *CACHE.get("swio", (0.0, 0.0))) + storm_html()[1],
                     bar(min((sg := float((st.replace(' GiB','') or '0').split('/')[0])) / 2.0 * 100, 100), heat_swap(sg)))
              + card("DISK · GiB" + pchip("DISK", "%", hf=heat_disk), f"{dp} · {dt.replace(' GiB','')}", bar((dv := int(dp.strip("%") or 0)), heat_disk(dv)))
              + card("DISK I/O · MB/s" + pchip("DISK I/O", " MB/s", "{:.0f}", hf=heat_io, xform=lambda v: min(v/500*100, 100)), (lambda a: f"R {a[0]:.0f} · W {a[1]:.0f}")(CACHE.get("io", (0.0, 0.0))),
                     bar((iop := min(sum(CACHE.get("io", (0.0, 0.0))) / 500 * 100, 100)), heat_io(iop)))  # ponytail: 500 MB/s bar ceiling — rescale if sustained NVMe range matters
              + card(f"CPU · 1 min avg" + pchip("CPU", "", "{:.2f}", hf=heat, xform=lambda v: min(v/NCPU*100, 100)), ld, bar(cpup, heat(cpup)))
              )
    hok, sok = h == "ok", svc == "active"
    def spark(series, color):
        if len(series) < 2: return '<svg class="sp" viewBox="0 0 100 30"></svg>'
        t0, t1 = series[0][0], series[-1][0]
        dt = (t1 - t0) or 1.0                     # true-time x spacing
        vals = [v for _, v in series]
        lo, hi = min(vals), max(vals); dv = (hi - lo) or 1.0
        pts = " ".join(f"{(t-t0)/dt*100:.1f},{29-27*(v-lo)/dv:.1f}" for t, v in series)
        return (f'<svg class="sp" viewBox="0 0 100 30" preserveAspectRatio="none">'
                f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.3"/></svg>')
    tgs = f"{tg[2]:.1f} t/s <i>({tg[1]:,} tok)</i>" if tg else "idle"
    accs = f"{acc[0]:.2f} <i>(len {acc[1]:.1f})</i>" if acc else "—"
    svc_h = "" if sok else card("SERVICE", f'<span class="bad">{svc}</span>')
    hlt_h = "" if hok else card("HEALTH", f'<span class="bad">{h}</span>')
    def _dur(s): return f"{s//60}m{s%60:02d}s" if s >= 60 else f"{s}s"
    _ev = list(CACHE.get("loads", [])) + _switches_recent()
    _ev.sort(key=lambda d: -(d.get("e") or 0))
    for _i, _d in enumerate(_ev): _d["i"] = _i
    _lds = sorted(_ev, key=lambda d: d["s"] if ARM_SORT_MODE else -d["i"])
    _resn = CACHE.get("res") or []
    _pills = "".join(f'<span class="pill">{html.escape(a)}</span>' for a in _resn) or '<span class="pill off">none</span>'
    def _row(d):
        hhmm = (time.strftime("%H:%M", time.localtime(d["e"])) if d.get("e")
                else f'{d["t"]//3600:02d}:{d["t"]%3600//60:02d}')
        return (f'<i class="{"sw" if d.get("d") else "m"}">{html.escape(d["arm"])}</i>'
                f'<span>{html.escape(d.get("d") or _dur(d["s"]))}</span><span>{hhmm}</span>')
    _rows = "".join(_row(d) for d in _lds) or \
        '<i class="m" style="grid-column:1/-1">no load and no profile switch in the last 6h</i>'
    armtxt = (f'<div class="artab"><b>event</b>'
              f'<b class="{"on h" if ARM_SORT_MODE else "h"}" onclick="armOrd(1)">load</b>'
              f'<b class="{"h on" if not ARM_SORT_MODE else "h"}" onclick="armOrd(0)">at</b>'
              + _rows + '</div>')
    wd = CACHE.get("wd") or (None, False)
    infrow = (card(f'ARM {_pills}', '<div class="prof">' + profile_line_html(*CACHE.get("prof") or (None, [], [], None))
                   + '</div><div class="prof">' + watchdog_html(wd[0], wd[1], time.time()) + '</div>' + armtxt, w=2, h=2)
              + '<div class="card" style="grid-column:span 2"><b>LIVE tg ' + pchip("LIVE tg", " t/s", "{:.1f}") + ' <span id="tgv" style="color:#4c9aff">…</span></b>'
              '<svg class="sp" viewBox="0 0 100 30" preserveAspectRatio="none"><polyline id="tgline" fill="none" stroke="#4c9aff" stroke-width="1.3"/></svg></div>'
              '<div class="card" style="grid-column:span 2"><b>DRAFT acc ' + pchip("DRAFT acc", "", "{:.2f}") + ' <span id="accv" style="color:#6dd66d">…</span></b>'
              '<svg class="sp" viewBox="0 0 100 30" preserveAspectRatio="none"><polyline id="accline" fill="none" stroke="#6dd66d" stroke-width="1.3"/></svg></div>'
              + svc_h + hlt_h)
    charts = ''  # chart shells are static in the page (outside htmx swap)
    probs = []
    _eng = "gufo" if CACHE.get("gufo") else "model-router"
    if not sok: probs.append(f"{_eng} service: {svc}")
    if not hok and CACHE.get("llm_any") is not None and not CACHE.get("llm_any"):
        probs.append("LLM parked — image mode (no :8080 arm; the title-row ▶ button switches)")   # informational, not an outage
    elif not hok: probs.append(f"/health: {h}")
    probs += [f"journal: {html.escape(e[-160:])}" for e in errs]
    probs += [f"dmesg: {html.escape(e[-160:])}" for e in gpu_err]
    banner = ('<div class="err"><button class="cp" style="float:right;margin-left:8px" onclick="cpBox(this,\'.err\')" title="copy errors">⧉</button>' + "<br>".join(probs) + "</div>") if probs else ""
    act = []
    for l in jn[-60:]:
        t = re.sub(r"^.*?llama-server\[\d+\]: ", "", l)
        if not t.strip() or "ensure_model: waiting" in t or BENIGN.search(t): continue
        cls = "e" if re.search(r"\bERROR\b|error:|failed|fatal", t, re.I) else ("a" if re.search(r"spawn|loaded|unloaded", t) else ("d" if "print_timing" in t else ""))
        act.append(f'<div class="l {cls}">{html.escape(t[-150:])}</div>')
    log = (f'<div class="card log"><b>ACTIVITY — {_eng} (tail-f, 2s)'
            f'<button class="cp" onclick="cpLog(this)" title="copy log">\u29C9</button></b>{"".join(reversed(act[-20:]))}</div>')
    # The inference section is a <details> collapsed by default (operator 261001). It lives
    # INSIDE the 2s htmx target, so the open/closed state cannot survive the swap on its own:
    # the client re-bakes `open` into the response in htmx:beforeSwap (see INF in HTML), which
    # applies the state before insertion, so there is no flicker and no extra endpoint.
    return (banner + f'<div class="grid">{sysrow}</div>'
            + '<details id="infdet"><summary>inference</summary><div class="grid">' + infrow + '</div></details>',
            f'{log}')

# Lab webuis as buttons in the control bar (operator 261001): icon + short name on the
# button, long description + port + liveness in the tooltip - the short name is what pairs
# visually with the start/stop word under it. One line per service, so adding a server to
# the lab is one entry here and nothing else. Dead ones render DIM instead of vanishing: a
# grey icon means "stopped", a missing icon would mean "this box has no such thing".
# ponytail: "listening" is not "serving" - a front like socat :7860 answers even with the
# gradio behind it down; the start/stop buttons are the authority on unit state, these are
# shortcuts.
LAB_UI = [("\U0001F3A8", "comfy", 8188, "ComfyUI - MiniMax-H3 workflows"),
          ("\U0001F5BC", "img", 7860, "Qwen-Image web app"),
          ("\U0001F3AC", "h3ui", 7861, "MiniMax-H3 video UI"),
          ("\U0001F3B5", "acestep", 7862, "ACE-Step music UI"),
          ("\U0001F3A4", "whisper", 7863, "Whisper STT"),
          ("\U0001F4AC", "webui", 3000, "Open WebUI")]


# GPU POWER zones (operator 261001): ~105 W is the NORMAL steady state while an arm infers
# on this APU, and the card used the generic watts-as-percent heat(), which saturates at 100
# -> hue 0 -> the bar and the peak chip were red for ordinary inference, i.e. the alarm was
# the loss of one. Green below 110 (105 W is the measured steady state mid-inference), yellow
# across the operator's 110-118 band, red beyond 118. The bar's ceiling is the 140 W chassis rating, not 100, so the bar still reads
# as headroom. Module level so tests/power_zones_check.py can bite it.
heat_power = lambda w: "hsl(120,90%,55%)" if w < 110 else ("hsl(45,90%,55%)" if w <= 118 else "hsl(0,90%,55%)")


def port_up(port):
    """50 ms loopback connect to 127.0.0.1 - and specifically NOT to "localhost".

    261001 note, reversed: the version below probed "localhost", added because `ss -ltn`
    showed [::]:7860 and an IPv4-only probe was believed to call a live UI dead. The
    listener on [::]:7860 is gradio-v6-relay (socat, ipv6only=1, fork), which exists for
    REMOTE v6 clients and accepts the TCP handshake even when its IPv4 backend is gone - so
    the probe reported the Qwen-Image web app live in every profile, all day, with nothing
    behind it (measured: `curl http://[::1]:7860/` -> 000 while the icon stayed lit).
    Gradio and every lab unit here bind 0.0.0.0, so the IPv4 address is the service itself.
    A box that ever serves a UI on IPv6 alone needs a second probe, and the relay must be
    excluded from it."""
    try:
        socket.create_connection(("127.0.0.1", port), 0.05).close()
        return True
    except OSError:
        return False


def lab_ui_html(vh):
    """Buttons for the lab UIs that are UP right now - icon AND short name, because seven
    identical glyphs meant hovering the whole row to find the page you wanted (operator
    261001). A stopped service renders NOTHING here: the row is "what can I open", and the
    start/stop line under it is "what can I turn on". Host comes from the request, so a
    laptop reading strixy-9ad3.local:8667 gets links it can actually open. Rendered inside
    the #hact
    fragment, so the 5 s poll (and box-refresh after any start/stop) re-probes them; `/`
    server-renders the same markup for the first paint. Liveness is a 50 ms loopback connect - no subprocess, no visible latency. The probe goes
    through create_connection so BOTH families are tried: socat fronts :7860 on IPv6 only
    (measured 261001, `ss -ltn` shows [::]:7860), so an AF_INET/127.0.0.1-only probe called
    a live UI dead."""
    out = []
    for ico, name, port, tip in LAB_UI:
        if not port_up(port):
            continue
        out.append(f'<a class="lab" href="http://{vh}:{port}/" target="_blank" '
                   f'rel="noopener" title="{html.escape(tip)} :{port}">'
                   f'{ico} {html.escape(name)}</a>')
    return "".join(out)


HTML = """<!doctype html><html><head><meta charset=utf-8><title>Doctor</title>
<script src="/htmx.min.js"></script>
<script>function armOrd(m){fetch('/armorder?mode='+m)}
function profGo(s){const m=document.getElementById('profmsg');m.textContent='…';
 fetch('/profile?name='+encodeURIComponent(s.value),{method:'POST'}).then(r=>r.text()).then(t=>{m.textContent=t;m.title=t;
  window.dispatchEvent(new Event('box-refresh'))})
 .catch(()=>{m.textContent='request failed'})}
</script>
<script>const H_TG=[],H_ACC=[];let lastSig=null,N=180;
function draw(id,arr){if(arr.length<2)return;var t0=arr[0][0],t1=arr[arr.length-1][0],dt=(t1-t0)||1;
var vs=arr.map(p=>p[1]),lo=Math.min(...vs),hi=Math.max(...vs),dv=(hi-lo)||1;
document.getElementById(id).setAttribute('points',
arr.map(p=>(p[0]-t0)/dt*100+','+(29-27*(p[1]-lo)/dv)).join(' '))}
async function pollPoint(){try{var d=await(await fetch('/point')).json();
if(d.sig!==lastSig){lastSig=d.sig;if(d.tg!=null){H_TG.push([d.t,d.tg]);if(H_TG.length>N)H_TG.shift();draw('tgline',H_TG);
document.getElementById('tgv').textContent=d.tg.toFixed(1)+' t/s ('+d.tgtok+' tok)';lastTgV=document.getElementById('tgv').innerHTML}
if(d.acc!=null){H_ACC.push([d.t,d.acc]);if(H_ACC.length>N)H_ACC.shift();
document.getElementById('accv').textContent=d.acc.toFixed(2);lastAccV=document.getElementById('accv').innerHTML}}
else if(d.age>8){H_TG.push([d.t,0]);if(H_TG.length>N)H_TG.shift();H_ACC.push([d.t,0]);if(H_ACC.length>N)H_ACC.shift();
document.getElementById('tgv').textContent='0.0 t/s (idle)';lastTgV=document.getElementById('tgv').innerHTML;
document.getElementById('accv').textContent='\u2014';lastAccV=document.getElementById('accv').innerHTML}
draw('tgline',H_TG);draw('accline',H_ACC)}catch(e){}}
setInterval(pollPoint,2000);pollPoint()
var lastTgV='',lastAccV='';
// The inference <details> is re-created by the 2s swap; remember whether the operator opened
// it and re-bake the attribute before the fragment is inserted (default: collapsed).
let INF=false;
document.addEventListener('htmx:beforeSwap',e=>{if(e.target.id==='stats'&&INF)
 e.detail.serverResponse=e.detail.serverResponse.replace('<details id="infdet">','<details id="infdet" open>')});
document.addEventListener('toggle',e=>{if(e.target.id==='infdet')INF=e.target.open},true);
document.addEventListener('htmx:afterSwap',e=>{if(e.target.id==='stats'){draw('tgline',H_TG);draw('accline',H_ACC);
if(lastTgV)document.getElementById('tgv').innerHTML=lastTgV;
if(lastAccV)document.getElementById('accv').innerHTML=lastAccV}})</script>
<script>function cpBox(btn,sel){var L=btn.closest(sel);var ls=L.textContent.trim();function done(ok){if(ok){btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u29C9',900)}}if(navigator.clipboard){navigator.clipboard.writeText(ls).then(()=>done(1),()=>done(0));return}var ta=document.createElement('textarea');ta.value=ls;ta.style.cssText='position:fixed;top:0;left:0;opacity:0';L.appendChild(ta);ta.select();var ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();done(ok)}
function peakReset(btn,key){fetch('/peak/reset'+(key?'/'+encodeURIComponent(key):'')).then(()=>{btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u21ba',900)})}
function stormReset(btn){fetch('/storm/reset',{method:'POST'}).then(()=>{btn.textContent='\u2713';setTimeout(()=>location.reload(),500)})}
function cpLog(btn){var L=btn.closest('.log');var ls=[].map.call(L.querySelectorAll('.l'),d=>d.textContent).join('\\n');
function fallback(){var ta=document.createElement('textarea');ta.value=ls;ta.style.cssText='position:fixed;top:0;left:0;opacity:0';L.appendChild(ta);ta.focus();ta.select();ta.setSelectionRange(0,ls.length);
var ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();
if(ok){btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u29C9',900)}
else{var r=document.createRange();r.selectNodeContents(L);var s=getSelection();s.removeAllRanges();s.addRange(r);
btn.textContent='Ctrl+C';setTimeout(()=>btn.textContent='\u29C9',2000)}}
if(navigator.clipboard&&navigator.clipboard.writeText)
navigator.clipboard.writeText(ls).then(()=>{btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u29C9',900)}).catch(fallback);
else fallback()}</script><style>
body{font-family:system-ui;margin:40px auto;max-width:80%;color:#ddd;background:#111}
h1{font-size:1.2em;color:#fff;display:flex;align-items:center;gap:8px}h2{font-size:.95em;color:#888;margin:20px 0 8px}
summary{font-size:.95em;color:#888;margin:20px 0 8px;cursor:pointer;list-style:none}
summary::before{content:"▸ "}details[open] summary::before{content:"▾ "}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
/* The switch result is a sentence. It used to sit inside h1, and h1 is a flex row with about
   160 px of slack: measured 261001, 22 characters kept the row at 29px and 26 pushed it to
   48px — the title wrapped as soon as a profile name was long. It gets its own reserved line
   under the title instead: full text, no layout jump, and a message cannot wrap the row. */
#profmsg{font-size:.62em;color:#8b98a5;min-height:1.2em;margin:-2px 0 4px}
h1 #rst{font-size:.7em;color:#888;background:none;border:1px solid #444;border-radius:6px;cursor:pointer;padding:0 8px}
h1 #rst:hover{color:#4c9aff;border-color:#4c9aff}
.anv{font-size:.72em;color:#d9a441;border:1px solid #4a3c22;border-radius:6px;padding:1px 6px;text-decoration:none;line-height:1.5;display:inline-flex;align-items:center;justify-content:center;gap:.3em;height:1.5em}
/* Same box as .lab (line-height 1.5 + 1px padding + 1px border = 24.7px measured) and an
 svg at the advance width of an emoji glyph, so the anvil is not a smaller button. */
.anv svg{width:1.15em;height:1.15em;fill:currentColor;display:block}.anv:hover{border-color:#d9a441}
/* Lab webuis: icon + short name (operator 261001), green like a running service button -
   and only the ones that answer are rendered at all, so green is the only state here. */
.lab{font-size:.72em;text-decoration:none;padding:1px 6px;border:1px solid #3a3a3a;border-radius:6px;line-height:1.5;color:#6dd66d}
.lab:hover{border-color:#4c9aff}
.card{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:12px}
/* The title rule only — `.card b` hit every nested <b> too, so the profile and
   watchdog lines broke one fragment per line (260930, operator screenshot). */
.card>b{display:block;font-size:.8em;color:#888;margin-bottom:6px}
.card>span{font-size:1.25em}.card span i{font-size:.7em;color:#999}
.bar{height:6px;background:#333;border-radius:3px;margin-top:8px}
.bar i{display:block;height:100%;background:#4c9aff;border-radius:3px}
.sp{width:100%;height:52px;margin-top:8px;background:#151515;border-radius:5px}
.ok{color:#6dd66d}.bad{color:#ff6b6b}
.pk{color:#888;font-style:normal;font-size:.8em}
details.chk summary{cursor:pointer;list-style:none}
details.chk summary::-webkit-details-marker{display:none}
details.chk summary::before{content:"▸ ";color:#4c9aff}
details.chk[open] summary::before{content:"▾ "}
.err{background:#3a1111;border:1px solid #ff6b6b;color:#ffb3b3;border-radius:10px;padding:12px;margin-bottom:14px;font-size:.85em;white-space:pre-wrap}
/* The icons moved inside the polled span (261001), so the span has to lay its children out
 like h1 does or the row collapses into one clump of tiny glyphs. The span itself stays at
 h1 size (that is what makes .lab render at its normal .72em); only the word buttons shrink. */
/* The control bar is its own line under the title (operator 261001: the title row was
 crowded). Same 1.2em as h1 so every glyph keeps the size it had inside the title. Opens
 left, start/stop pushed to the right edge by .tog{margin-left:auto}. */
#bar{display:flex;align-items:flex-start;gap:8px;font-size:1.2em;margin:-2px 0 4px;position:relative}
/* The uptime sits at the right end of the opens line, opposite the icons: absolute so it is
 out of the flex flow and cannot push the groups, and it polls with them (see uptime_str). */
#bar .up{position:absolute;right:0;font-size:.55em;color:#888;font-weight:normal;white-space:nowrap}
/* Opens on the first line, start/stop on their OWN line under them (operator 261001),
 left-aligned so each button sits under the icon of the page it controls. flex-basis:100%
 is what forces the second line. */
#hact{display:flex;flex-wrap:wrap;align-items:center;flex:1;row-gap:4px}
#hact .cp{font-size:.62em}
#hact .opens{display:flex;align-items:center;gap:8px}
#hact .tog{flex-basis:100%;display:flex;align-items:center;gap:6px;justify-content:flex-start}
#hact .tog .cp{margin-left:0}
/* Running = green label, stopped = the ordinary grey. The glyph says the action, the
 colour says the state, so the row is readable at a glance from the far side of the room. */
#hact .tog .cp.on{color:#6dd66d}
.log{margin-top:18px;font-family:ui-monospace,monospace;font-size:.72em;line-height:1.5;max-height:340px;overflow-y:auto}
.log .l{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#bbb}
.log .l.e{color:#ff6b6b}.log .l.a{color:#ffc46b}.log .l.d{color:#777}
.artab *{font-size:.78em !important}
.pill{display:inline-block;background:#1d7a2e;color:#eaffea;border-radius:9px;padding:1px 8px;font-size:1.25em;margin-left:8px;vertical-align:middle}
#prof{margin-left:auto;font-size:.85em;background:#101418;color:#cfe3ff;border:1px solid #2a3a4a;border-radius:6px;padding:2px 6px}
.prof{display:block;font-weight:400;font-size:.8em;margin-top:4px;opacity:.95}
.prof .on{color:#6dd66d}.prof .bad{color:#ff6b6b}.prof .m{color:#8b98a5}
.pill.off{background:#3a3a3a;color:#999}
.artab{display:grid;grid-template-columns:minmax(0,max-content) minmax(52px,max-content) minmax(44px,max-content);gap:0 14px;font-size:.78em;margin-top:2px;line-height:1.5}
.artab > :nth-child(6n+4),.artab > :nth-child(6n+5),.artab > :nth-child(6n+6){background:#1d1d1d}
.artab > *{padding:1px 0}
.artab b{color:#666;font-weight:400}
.artab i.sw{color:#e0b352}
.artab b.h{cursor:pointer;text-align:right}
.artab b.on{color:#ddd;text-decoration:underline}
.artab .m{font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.artab span{color:#999;font-variant-numeric:tabular-nums;text-align:right}
.cp{background:#262626;border:1px solid #444;color:#aaa;border-radius:5px;cursor:pointer;font-size:1em;padding:0 6px;margin-left:auto}
.log>b{display:flex;align-items:center;gap:6px}
.links{margin-top:12px;display:flex;flex-direction:column;gap:6px}
.links a{color:#4c9aff;text-decoration:none;font-size:.85em}
@media(max-width:720px){.grid{grid-template-columns:1fr 1fr}}
</style></head><body>
<h1><button id="rst" title="restart Doctor.service" onclick="this.textContent='…';fetch('/restart',{method:'POST'}).then(()=>setTimeout(()=>location.reload(),2500)).catch(()=>{})">↻</button>__HOST__<span id="profchip" hx-get="/profchip" hx-trigger="load, box-refresh from:body, every 5s[document.activeElement.id!=='prof']" hx-swap="innerHTML">__PROF__</span></h1>
<div id="bar"><span id="hact" hx-get="/boxinfo" hx-trigger="load, every 5s, box-refresh from:body" hx-swap="innerHTML">__WEBUI__</span></div>
<div id="profmsg" class="m"></div>
<div id="stats" hx-get="/stats" hx-trigger="every 2s" hx-swap="innerHTML">loading…</div>
<details class="actbox"><summary>morning report</summary>
<div id="chk" hx-get="/chk" hx-trigger="load, every 60s" hx-swap="innerHTML">loading…</div>
</details>
<details class="actbox"><summary>activity</summary>
<div id="stats2" hx-get="/stats2" hx-trigger="every 2s" hx-swap="innerHTML"></div>
</details>
</body></html>"""

def res(name):
    try:
        if name == "ini":
            txt = open(ROUTER_INI).read().split("\n")[:80]
        elif name == "doctor":
            p = "/home/piero/.pi/agent/skills/doctor-dream/DOCTOR_REPORT_latest.md"
            txt = open(p, errors="ignore").read().split("\n")[:400] if os.path.exists(p) else ["no doctor report yet"]
            return "<pre>" + html.escape("\n".join(txt)) + "</pre>"
        elif name == "report":
            fs = sorted(glob.glob("/home/piero/Piero/Work/Qwen38/gbench/MORNING-REPORT-*"))
            txt = open(fs[-1]).read().split("\n")[-80:] if fs else ["no morning report yet — run night-bench.sh <task> overnight"]
        elif name == "sweep":
            txt = open("/tmp/spec-sweep/results.md").read().split("\n")[-60:]
        elif name == "stats":
            s = json.load(open("/home/piero/Piero/Work/Qwen38/gbench/stats.json"))
            txt = [f"{a}: loads n={len(v.get('loads_s',[]))} med={v.get('load_med_s')}s | tg n={len(v.get('tg',[]))} | acc n={len(v.get('acc',[]))}" for a, v in s["arms"].items()]
        else: return None
        return "<pre>" + html.escape("\n".join(txt)) + "</pre>"
    except Exception as e:
        return f"<pre>unavailable: {html.escape(str(e))}</pre>"

def _metrics_logger():
    # pi-doctor-dream: append one CSV line/min for c_resources.py trends.
    # ts,cpu,gpu,ram_avail,temp,load1,gtt_used — CPU% via 1s /proc/stat delta;
    # ram/gtt in MB (260923 F2: gtt_used added, old rows simply lack the col).
    d = os.environ.get("DOCTOR_STATE_DIR", os.path.expanduser("~/.pi/agent/skills/doctor-dream/state"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "metrics.csv")
    if not os.path.exists(p):
        open(p, "w").write("ts,cpu,gpu,ram_avail,temp,load1,gtt_used\n")
    else:
        # one-time migration: rewrite a 6-col header so new rows align
        with open(p) as fh: first = fh.readline().rstrip("\n")
        if first and "gtt_used" not in first:
            lines = open(p).read().splitlines(True)
            lines[0] = first + ",gtt_used\n"
            open(p, "w").writelines(lines)
    def _cpu():
        s1 = open("/proc/stat").readline().split()[1:5]; time.sleep(1)
        s2 = open("/proc/stat").readline().split()[1:5]
        t1, t2 = sum(map(int, s1)), sum(map(int, s2))
        return int(100 * (1 - (int(s2[3]) - int(s1[3])) / ((t2 - t1) or 1)))
    while True:
        try:
            # gpu_busy_percent: kept for the record and for c_resources.py's schema, but it is
            # pinned to 100 while any process holds /dev/kfd. Chart power or gtt_used instead.
            g = 0
            for f in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
                try: g = max(g, int(open(f).read()))
                except Exception: pass
            t = 0
            for f in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input"):
                try: t = max(t, int(open(f).read()) // 1000)
                except Exception: pass
            ram = next((int(x.split()[1]) for x in open("/proc/meminfo") if x.startswith("MemAvailable")), 0) // 1024
            try: gtt = int(open("/sys/class/drm/card0/device/mem_info_gtt_used").read()) // 2**20
            except Exception: gtt = ""
            l1 = open("/proc/loadavg").read().split()[0]
            row = f"{int(time.time())},{_cpu()},{g},{ram},{t},{l1},{gtt}"
            with open(p, "a") as fh: fh.write(row + "\n")
        except Exception:
            pass
        time.sleep(60)

SKILL_DIR = os.path.expanduser("~/.pi/agent/skills/doctor-dream")


def checkup_html(skill=SKILL_DIR):
    # pi-doctor-dream: the morning-report card. Two artifacts, two jobs: panel.json holds the
    # numbers of the last pass that RAN; LAST-PASS.json holds what the pipeline DID, including
    # not running. The title used to be panel.json's mtime under a hardcoded "LAST NIGHT'S",
    # so a night the idle gate refused was indistinguishable from a fresh pass (OBSERVED
    # 261001: gate busy 03:15→06:51, no report, and the card showed a manual 10:14 pass as
    # though it were the night's).
    try:
        pj = f"{skill}/state/panel.json"
        d = os.path.getmtime(pj)
        p = json.load(open(pj))
    except (OSError, ValueError):
        return ''
    today = time.strftime("%y%m%d")
    has_today = bool(glob.glob(f"{skill}/DOCTOR_REPORT_{today}-*.md"))
    # Only a report dated today may be titled like today's; anything older shows its date.
    when = time.strftime("%a %H:%M" if has_today else "%b %d %H:%M", time.localtime(d))
    warn = ''
    if not has_today:
        try:
            lp = json.load(open(f"{skill}/state/LAST-PASS.json"))
            why = lp.get("reason") or lp.get("outcome") or "no reason recorded"
        except (OSError, ValueError):
            why = "no LAST-PASS.json, so the pipeline cannot say why"
        warn = f"<div class='l bad'>NO REPORT today — {html.escape(str(why))}</div>"
    n = p.get("new", {}); b = p.get("backlog", {})
    nums = f"new: P1×{n.get('P1',0)} P2×{n.get('P2',0)} P3×{n.get('P3',0)} · backlog: {b.get('count',0)} (oldest {b.get('oldest_days',0)}d)"
    summ = "".join(f"<div class='l'>{html.escape(s)}</div>" for s in p.get("summary", [])[:6])
    # /chk body only — the collapsible box itself is STATIC html (outside the
    # 2s htmx swap) so the open/closed state survives refreshes, like .actbox
    return (f'<div class="card log"><b>CHECKUP — {when} '
            f'</b><span style="color:#888">{nums}</span>'
            '<button class="cp" style="float:right" onclick="cpBox(this,\'.log\')" title="copy report">⧉</button>'
            f'{warn}{summ}'
            '<a href="/res/doctor" style="color:#4c9aff;font-size:.8em">full report</a></div>')

class H(BaseHTTPRequestHandler):
    def _llm_proxy(self):
        # Same-origin pass-through for Anvil (served from /anvil). llama.cpp build 10977 answers
        # the OPTIONS preflight with ACA-Methods/Headers but sends no Access-Control-Allow-Origin
        # on the real response (observed 260930, curl -D- on /v1/chat/completions and /v1/models),
        # so a browser on :8667 cannot read :8080. Forwarding here leaves the arm's flags alone;
        # the arm is already LAN-open with no auth (260911), so this grants no new capability.
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = Request(LLM_UP + self.path[4:], data=raw or None, method=self.command,
                      headers={"Content-Type": self.headers.get("Content-Type") or "application/json"})
        try:
            up = urlopen(req, timeout=1800)
        except HTTPError as e:
            up = e  # the arm DID answer, with 4xx/5xx: relay its status and body. urlopen raises
                    # instead of returning, and swallowing that into a 502 hides the one message
                    # Anvil needs ("model not loaded", "unknown model", a template error).
        except Exception as e:  # nothing listening, or a timeout: that failure is ours
            body = f"llm proxy: {type(e).__name__}: {e}".encode()[:600]
            self.send_response(502); self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); return
        self.send_response(up.status)
        self.send_header("Content-Type", up.headers.get("Content-Type", "application/json"))
        self.end_headers()
        # read1, not read: read(8192) blocks until it has 8192 bytes or the stream ends, which
        # turns a token stream into one dump at the end (measured 260930: first chunk arrived
        # 0.50 s late through the proxy with the upstream pausing 0.5 s between chunks).
        read = getattr(up, "read1", None) or up.read
        try:
            while True:
                chunk = read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()  # no-op today (wbufsize=0); cheap if a subclass buffers
        except Exception:
            pass  # the viewer navigated away mid-stream
        finally:
            up.close()

    def do_POST(self):
        code = 200

        # Anvil talks to the arm through us: same origin, no CORS (see _llm_proxy).
        if self.path.startswith("/llm/"):
            return self._llm_proxy()
        # /restart: restart own service. POST-only (no stray GET/link/prefetch can
        # fire it); the systemctl call is a fixed argv, not user input. LAN-trusted
        # posture matches the :8080 no-auth decision (260911).
        if self.path == "/restart":
            subprocess.Popen(["/bin/bash", "-c", "sleep 1; systemctl --user restart Doctor.service"],
                             start_new_session=True)
            body, ct = "restarting Doctor.service…", "text/plain"
        elif self.path == "/storm/reset":
            # POST-only, like /restart: a link or prefetch must not erase storm evidence.
            STORM.clear(); storm_save()
            body, ct = "storm latch cleared", "text/plain"
        elif self.path == "/llmtoggle":
            # 260925; 260926: toggle the LIVE :8080 arm if any, else start the preferred
            # one. POST-only. 261001: the arm list is LLM_ARMS, not a copy of it here.
            _arm = arm_target()
            _act = _arm == arm_live()
            subprocess.run(["systemctl", "--user", ("stop" if _act else "start"), f"{_arm}.service"], timeout=60)
            body, ct = f"{('stopping' if _act else 'starting')} {_arm}…", "text/plain"
        elif self.path.startswith("/svctoggle"):
            # The generic start/stop (operator 261001). The key is looked up in SVC_TOGGLES
            # and nothing else: with no auth on this box the dict is the only thing between
            # a stray POST and an arbitrary systemctl call. Same semantics the old
            # /imgtoggle had by hand: stop the list if the deciding unit is up, else start
            # the whole list (a UI and its engine never half-up).
            _key = (parse_qs(urlparse(self.path).query).get("u") or [""])[0]
            _ent = SVC_TOGGLES.get(_key)
            if not _ent:
                code, body, ct = 404, f"unknown service {_key!r}", "text/plain"
            else:
                _units = [f"{u}.service" for u in _ent[2]]
                _on = _unit(_units[-1], "is-active")
                subprocess.run(["systemctl", "--user", "stop" if _on else "start", *_units],
                               timeout=60)
                body, ct = f"{'stopping' if _on else 'starting'} {' + '.join(_units)}…", "text/plain"
        elif self.path.startswith("/profile"):
            # Apply a profile from the panel. The name is validated against the profile keys
            # before anything is spawned (profile_apply), and the apply is detached like
            # /restart: loading weights takes minutes and a blocked POST gets retried.
            code, body = profile_apply(self.path, profile_starts(), _spawn_apply, apply_dry_run)
            ct = "text/plain"
        else:
            code, body, ct = 404, "not found", "text/plain"
        # One writer for every POST branch (operator 261001): /storm/reset and /imgtoggle
        # set body/ct and then fell through to nothing, so the button DID the action and
        # the browser saw a closed socket (curl 000). A branch must not be able to forget
        # the response.
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):

        # Anvil talks to the arm through us: same origin, no CORS (see _llm_proxy).
        if self.path.startswith("/llm/"):
            return self._llm_proxy()
        if self.path == "/peak/reset" or self.path.startswith("/peak/reset/"):
            # 260923: was [13:] — an off-by-one past the key's first char, so
            # every per-card reset fell through to PEAKS.clear() (all cards).
            # Also unquote: multi-word keys arrive percent-encoded from the UI.
            k = unquote(self.path[12:]) or None
            if k: PEAKS.pop(k, None); _HIST.pop(k, None)   # window too: a reset while the level
            else: PEAKS.clear(); _HIST.clear()             # is still held would re-arm next sample
            body, ct = "ok", "text/plain"
        elif self.path == "/chk":
            try: body, ct = checkup_html(), "text/html"   # swapped into the STATIC morning-report box (60s cadence, not 2s)
            except Exception as e: body, ct = f"<div class='err'>chk error: {html.escape(str(e))}</div>", "text/html"
        elif self.path == "/stats":
            try: body, ct = stats()[0], "text/html"   # err box first after title; the morning report has its own /chk box
            except Exception as e: body, ct = f"<div class='err'>dash error: {html.escape(str(e))}</div>", "text/html"
        elif self.path.startswith("/armorder"):
            global ARM_SORT_MODE
            m = re.search(r"mode=(\d)", self.path)
            if m: ARM_SORT_MODE = int(m.group(1))
            self.send_response(204); self.end_headers(); return
        elif self.path == "/profchip":
            # The dropdown's selected option is state, and it used to be rendered once by `/`
            # outside any polled slot: apply a profile from the CLI and the row kept claiming
            # the old one until a hard reload (operator 261001). Same lesson as the icons.
            try:
                body, ct = profile_select_html(list(SP.load_profiles(SP.PROFILES_DIR)),
                                               SP.read_stamp()), "text/html"
            except Exception as e:
                body, ct = f"<div class='err'>profchip error: {html.escape(str(e))}</div>", "text/html"
        elif self.path == "/boxinfo":
            vh = (self.headers.get("Host") or "").split(":")[0] or socket.gethostname()
            try: body, ct = boxinfo(vh), "text/html"
            except Exception as e: body, ct = f"<div class='err'>boxinfo error: {html.escape(str(e))}</div>", "text/html"
        elif self.path == "/stats2":
            try: body, ct = stats()[1], "text/html"
            except Exception as e: body, ct = f"<div class='err'>dash error: {html.escape(str(e))}</div>", "text/html"
        elif self.path == "/point":
            tg, acc = CACHE["tg"], CACHE["acc"]
            body = json.dumps({"sig": CACHE["sig"] and str(CACHE["sig"]),
                               "t": time.time(),
                               "age": round(time.time() - CACHE["sig_t"], 1),
                               "tg": tg[2] if tg else None, "tgtok": tg[1] if tg else 0,
                               "acc": acc[0] if acc else None})
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body.encode()); return
        elif self.path == "/log":
            lines = [re.sub(r"^.*?llama-server\[\d+\]: ", "", l) for l in CACHE["jn"][-200:]]
            body, ct = "<pre>" + html.escape("\n".join(lines)) + "</pre>", "text/html"
        elif self.path in ("/anvil", "/anvil/"):
            # Vendored 260930 from the .150 laptop. Anvil.html is self-contained (its settings
            # live in the browser's localStorage); anvil-config.json and anvil-serve.py come
            # along for provenance and are deliberately not served.
            # The two CDN <script> tags are pointed at the local copies on the way out: they are
            # parser-blocking, so with no internet the page never reached DOMContentLoaded (the
            # same reason htmx is vendored). The file on disk stays byte-identical to upstream,
            # so re-copying Anvil.html from the laptop cannot silently undo this.
            try:
                body = open(os.path.join(ANVIL, "Anvil.html"), errors="ignore").read()
                for lib in ("marked.min.js", "purify.min.js"):
                    body = re.sub(r"https://cdnjs\.cloudflare\.com/ajax/libs/[a-z.]+/[\d.]+/" + lib,
                                  "/anvil/" + lib, body)
                # The Google-Fonts stylesheet is the last request that used to hold the page at
                # readyState=loading forever on this LAN-gapped box; media="print" makes it
                # non-blocking, and a viewer with internet still gets IBM Plex a moment later.
                body = body.replace('''<link href="https://fonts.googleapis.com/css2?''',
                                    '''<link media="print" onload="this.media='all'"
                                       href="https://fonts.googleapis.com/css2?''')
                # Anvil ships 127.0.0.1 as the endpoint default. The dashboard is read from a
                # laptop, where 127.0.0.1 is the laptop, so point the defaults at whoever asked
                # for the page; Anvil keeps the value in localStorage once the user edits it.
                host = self.headers.get("Host") or "127.0.0.1:8667"
                # The chat endpoint is the one URL that must come back through us (/llm/, CORS);
                # the other local ports (image :8081, audio :8001, raw arm :8080) stay direct.
                body = body.replace("http://127.0.0.1:8080/v1/chat/completions",
                                    "http://" + host + "/llm/v1/chat/completions")
                bare = host.rsplit(":", 1)[0]
                for port in ("8080", "8081", "8001"):
                    body = body.replace("127.0.0.1:" + port, bare + ":" + port)
            except OSError:
                body = "<pre>anvil is not vendored - doctor/anvil/Anvil.html is missing</pre>"
            ct = "text/html"
        elif self.path in ("/anvil/marked.min.js", "/anvil/purify.min.js"):
            try:
                body = open(os.path.join(ANVIL, self.path[7:]), errors="ignore").read()
            except OSError:
                body = ""
            ct = "application/javascript"
        elif self.path == "/htmx.min.js":
            # Vendored 260927 (operator): the dashboard used to load htmx from
            # unpkg.com, so with no internet the whole page was inert. Served
            # from the repo next to this file; missing file must not kill the page.
            try:
                body = open("/home/piero/Piero/Work/Strix_AI_Server/doctor/htmx.min.js",
                            errors="ignore").read()
            except OSError:
                body = ""
            ct = "application/javascript"
        elif self.path.startswith("/res/"):
            body, ct = res(self.path[5:]) or "<pre>?</pre>", "text/html"
        else:
            # First paint of the title row is the SAME boxinfo() fragment the 5 s poll
            # replaces, so the icons and the swap buttons are already correct before the
            # first htmx round trip. Host comes from the request, so a laptop reading
            # strixy-9ad3.local:8667 gets links it can actually open.
            vh = (self.headers.get("Host") or "").split(":")[0] or socket.gethostname()
            body, ct = (HTML.replace("__HOST__", socket.gethostname()).replace("__PROF__",
            # Not the real dropdown: see PROF_PLACEHOLDER. The poll fills it in on load.
            PROF_PLACEHOLDER).replace("__WEBUI__",
            boxinfo(vh))), "text/html"
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body.encode())
    def log_message(self, *a): pass

if __name__ == "__main__":
    threading.Thread(target=_sampler, daemon=True).start()
    threading.Thread(target=_metrics_logger, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("DOCTOR_PORT", "8667"))), H).serve_forever()
