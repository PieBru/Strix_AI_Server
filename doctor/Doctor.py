#!/usr/bin/env python3
"""Doctor — 24/7 system + inference doctor for strixy-9ad3. Runs independently
of llama-server; will host the auto-improving feature (repo Principles #3).
Single file, stdlib only, htmx 2s poll. LAN-exposed :8667, no auth (op decision).
Panels: system cards (GPU/RAM/disk/CPU), inference cards (arm, service, health,
live tg + draft acceptance from the model-router journal), error banner
(health/service/journal/dmesg), tail-f activity log, operator links (+ /res/*
read-only excerpts: ini header, latest morning report, live sweep results).
Design: session 260913, operator-approved."""
import json, shutil, subprocess, socket, glob, re, html, time, threading, os
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

# Router unit names this panel watches (journal + is-active). Reference box:
# model-router-pwilkin / model-router-vanilla. This repo's units: llama-hip, llama-vulkan.
ROUTER_UNITS = ("model-router-pwilkin", "model-router-vanilla")
_JU = [a for u in ROUTER_UNITS for a in ("-u", u)]

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

PEAKS = {}   # key -> {v: max value, t: when set}; accrued in refresh() (always-on sampler)

def track(key, val):
    """Update a card's high-water mark."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return
    p = PEAKS.get(key)
    if p is None or v > p["v"]:
        PEAKS[key] = {"v": v, "t": time.time()}

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
    swt, swf, swc = (int(d.get(k, "0 kB").split()[0]) for k in ("SwapTotal", "SwapFree", "SwapCached"))
    swu = max(swt - swf - swc, 0)          # cached swap pages are reclaimable, not "used"
    s = shutil.disk_usage("/"); ld = open("/proc/loadavg").read().split()[0]
    return (f"{100*(tot-avail)/tot:.0f}%", f"{(tot-avail)/1048576:.0f}/{tot/1048576:.0f} GiB",
            f"{100*s.used/s.total:.0f}%", f"{s.used/1e9:.0f}/{s.total/1e9:.0f} GiB", ld,
            f"{100*swu/swt:.0f}%" if swt else "0%", f"{swu/1048576:.1f}/{swt/1048576:.0f} GiB")

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

ARM_SORT_MODE = 0   # server-side row order: 0 = recency (default), 1 = load time
BENIGN = re.compile(r"request cancelled while waiting for model|requires ctx_other|failed to measure the memory of the extra model"
                    r"|attention rotation force disabled|Qwen-VL models require|image-min-tokens|issues/16842"
                    r"|preserving reasoning|exceeds the available context size")  # routine: arm-swap probe race, memory-fit pre-pass, per-load advisories, client sent an oversized request (probe noise, not a fault)

def _models_max():
    try:
        m = re.search(r"(?m)^\s*models-max\s*=\s*(\d+)", open(ROUTER_INI).read())
        return int(m.group(1)) if m else 1
    except Exception: return 1
MODELS_MAX = _models_max()

def _resident():
    # live truth from /proc: child llama-server procs carry --alias (router main doesn't)
    out = []
    for c in glob.glob("/proc/[0-9]*/cmdline"):
        try: s = open(c, "rb").read().decode(errors="ignore").replace("\0", " ")
        except Exception: continue
        if "llama-server" in s and "--alias" in s:
            a = s.split("--alias")[1].split()[0].strip()
            if a and a not in out: out.append(a)
    return out

def _loads_recent():
    # time-window (6h) load events — the 300-line window floods during sweeps
    try:
        out = subprocess.run(["journalctl","--user"]+_JU+["--since","-6h","--no-pager"],
                             capture_output=True, text=True, timeout=10).stdout.splitlines()
    except Exception:
        return CACHE.get("loads", [])
    loads, p2a, pt = [], {}, {}
    def _sec(hms): return int(hms[:2])*3600+int(hms[3:5])*60+int(hms[6:8])
    for l in out:
        m = re.match(r"^\w+\s+\d+\s+(\d\d:\d\d:\d\d)", l)
        ts = _sec(m.group(1)) if m else None
        if (s := re.search(r"spawning server instance with name=(\S+) on port (\d+)", l)):
            p2a[s.group(2)] = s.group(1); pt[s.group(2)] = ts
        elif (r := re.search(r".*\[(\d+)\].*llama_server: model loaded", l)) and r.group(1) in pt:
            a0, t0, t1 = p2a.get(r.group(1), "?"), pt.pop(r.group(1)), ts
            if t0 is not None and t1 is not None:
                loads.append({"arm": a0, "s": max(t1 - t0, 0), "t": t1, "i": len(loads)})
    loads_h = [d for d in loads][-10:][::-1]     # last 10 load EVENTS, newest first
    return loads_h

def refresh():
    try:
        _g = gpu(); _r = ram_disk_cpu()
        track("GPU", int(_g[0].strip("%") or 0)); track("VRAM", int(_g[1].strip("%") or 0))
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
    if CACHE.get("tg"): track("LIVE tg", CACHE["tg"][2])
    if CACHE.get("acc"): track("DRAFT acc", CACHE["acc"][0])
    try: h = json.load(urlopen("http://127.0.0.1:8080/health", timeout=4))["status"]
    except Exception: h = "unreachable"
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
    arm = arms[0] if arms else "?"
    if time.time() - CACHE.get("loads_t", 0) > 30:
        CACHE["loads"] = _loads_recent(); CACHE["loads_t"] = time.time()
    CACHE["res"] = _resident()
    tg = acc = None
    for l in reversed(jn):
        if tg is None and (m := re.search(r"print_timing: id\s+\d+ \| task\s+(\d+) \| n_gen =\s*(\d+), tg =\s*([\d.]+)", l)):
            tg = (m.group(1), int(m.group(2)), float(m.group(3)))
        if acc is None and (m := re.search(r"draft acceptance = ([\d.]+) .*mean len =\s*([\d.]+)", l)):
            acc = (float(m.group(1)), float(m.group(2)))
        if tg and acc: break
    benign = BENIGN
    errs = [l for l in jn if re.search(r"\bERROR\b|error:|failed|fatal", l, re.I) and not benign.search(l)][-5:]
    try:
        dmesg = subprocess.run(["dmesg","--since","-5min"], capture_output=True, text=True, timeout=4).stdout
        gpu_err = [l for l in dmesg.splitlines() if "amdgpu" in l and re.search(r"error|fault|timeout|hang", l, re.I)][-3:]
    except Exception: gpu_err = []
    CACHE.update(h=h, svc=svc, arm=arm, arms=arms, tg=tg, acc=acc, jn=jn, errs=errs, gpu_err=gpu_err)
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

def stats():
    gp, vr, gt, gpw = gpu(); rp, rt, dp, dt, ld, sp, st = ram_disk_cpu()
    h, svc, arm, tg, acc, jn, errs, gpu_err = inference()
    bar = lambda p, c=None: f'<div class="bar"><i style="width:{min(max(p,0),100)}%;{f"background:{c}" if c else ""}"></i></div>'
    heat = lambda v: f"hsl({120-1.2*min(max(v,0),100)},90%,55%)"
    # VRAM zones (operator 260922): green <90 is the intended-usage zone,
    # yellow 90-95 is the caution band, red >95 is where the danger starts.
    heat_vram = lambda v: "hsl(120,90%,55%)" if v < 90 else ("hsl(60,90%,55%)" if v <= 95 else "hsl(0,90%,55%)")
    card = lambda l, v, b="", w=1, h=1: f'<div class="card"{f" style=\"grid-column:span {w}{f';grid-row:span {h}' if h>1 else ''}\"" if w>1 or h>1 else ""}><b>{l}</b><span>{v}</span>{b}</div>'
    try: tm = float(gt[:-2]) if gt.endswith("°C") else 0
    except ValueError: tm = 0
    try: pw = float(gpw[:-1]) if gpw.endswith("W") else 0
    except ValueError: pw = 0
    try: gpv = int(gp.strip("%"))
    except ValueError: gpv = 0
    NCPU = os.cpu_count() or 1
    cpup = min(float(ld)/NCPU*100, 100)
    def pchip(key, unit="", fmt="{:.0f}"):
        """Peak chip + per-card reset button, both right-aligned at the card title.
        For float:right the source order is reversed — the button is emitted
        first so it lands rightmost (the card edge) and the peak sits just left
        of it; the title text stays left-aligned."""
        p = PEAKS.get(key)
        if not p or p["v"] <= 0: return ""
        t = time.strftime("%H:%M", time.localtime(p["t"]))
        return (f'<button class="cp" style="float:right;margin-left:6px" onclick="peakReset(this,\'{key}\')" title="reset peak">↺</button>'
                f'<i class=pk style="float:right">peak {fmt.format(p["v"])}{unit} {t}</i>')
    sysrow = (card("GPU" + pchip("GPU", "%"), gp, bar(gpv, heat(gpv)))
            + card("VRAM" + pchip("VRAM", "%"), vr, bar((vv := int(vr.strip("%") or 0)), heat_vram(vv)))
              + card("GPU temp" + pchip("GPU temp", "°C"), gt, bar(tm, heat(tm))) + card("GPU power" + pchip("GPU power", "W"), gpw, bar(pw, heat(pw)))
              + card("RAM · GiB" + pchip("RAM", "%"), f"{rp} · {rt.replace(' GiB','')}", bar((rv := int(rp.strip("%") or 0)), heat(rv)))
              + card("SWAP · GiB" + pchip("SWAP", "%") + pchip("SWAP rate", " MB/s", "{:.0f}") + (" <span class=\"bad\">STORM</span>" if sum(CACHE.get("swio", (0.0, 0.0))) > 1.0 else ""),
                     (lambda si, so: f"{st.replace(' GiB','')}" + (f" · in/out {si:.0f}/{so:.0f} MB/s" if si or so else ""))(*CACHE.get("swio", (0.0, 0.0))),
                     bar(max(int(sp.strip("%") or 0), min(int(sum(CACHE.get("swio", (0.0, 0.0)))), 100)), heat(max(int(sp.strip("%") or 0), min(int(sum(CACHE.get("swio", (0.0, 0.0)))), 100)))))
              + card("DISK · GiB" + pchip("DISK", "%"), f"{dp} · {dt.replace(' GiB','')}", bar((dv := int(dp.strip("%") or 0)), heat(dv)))
              + card("DISK I/O · MB/s" + pchip("DISK I/O", " MB/s", "{:.0f}"), (lambda a: f"R {a[0]:.0f} · W {a[1]:.0f}")(CACHE.get("io", (0.0, 0.0))),
                     bar((iop := min(sum(CACHE.get("io", (0.0, 0.0))) / 500 * 100, 100)), heat(iop)))  # ponytail: 500 MB/s bar ceiling — rescale if sustained NVMe range matters
              + card(f"CPU · 1 min avg" + pchip("CPU", "", "{:.2f}"), ld, bar(cpup, heat(cpup)))
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
    _lds = sorted(CACHE.get("loads", []), key=lambda d: d["s"] if ARM_SORT_MODE else -d["i"])
    def _dur(s): return f"{s//60}m{s%60:02d}s" if s >= 60 else f"{s}s"
    _resn = CACHE.get("res") or []
    _pills = "".join(f'<span class="pill">{html.escape(a)}</span>' for a in _resn) or '<span class="pill off">none</span>'
    _rows = "".join(
        f'<i class="m">{html.escape(d["arm"])}</i>'
        f'<span>{_dur(d["s"])}</span><span>{d["t"]//3600:02d}:{d["t"]%3600//60:02d}</span>'
        for d in _lds) or '<i class="m" style="grid-column:1/-1">no loads in last 6h</i>'
    armtxt = (f'<div class="artab"><b>model</b>'
              f'<b class="{"on h" if ARM_SORT_MODE else "h"}" onclick="armOrd(1)">load</b>'
              f'<b class="{"h on" if not ARM_SORT_MODE else "h"}" onclick="armOrd(0)">at</b>'
              + _rows + '</div>')
    infrow = (card(f'ARM {_pills}', armtxt, w=2, h=2)
              + '<div class="card" style="grid-column:span 2"><b>LIVE tg ' + pchip("LIVE tg", " t/s", "{:.1f}") + ' <span id="tgv" style="color:#4c9aff">…</span></b>'
              '<svg class="sp" viewBox="0 0 100 30" preserveAspectRatio="none"><polyline id="tgline" fill="none" stroke="#4c9aff" stroke-width="1.3"/></svg></div>'
              '<div class="card" style="grid-column:span 2"><b>DRAFT acc ' + pchip("DRAFT acc", "", "{:.2f}") + ' <span id="accv" style="color:#6dd66d">…</span></b>'
              '<svg class="sp" viewBox="0 0 100 30" preserveAspectRatio="none"><polyline id="accline" fill="none" stroke="#6dd66d" stroke-width="1.3"/></svg></div>'
              + svc_h + hlt_h)
    charts = ''  # chart shells are static in the page (outside htmx swap)
    probs = []
    if not sok: probs.append(f"model-router service: {svc}")
    if not hok: probs.append(f"/health: {h}")
    probs += [f"journal: {html.escape(e[-160:])}" for e in errs]
    probs += [f"dmesg: {html.escape(e[-160:])}" for e in gpu_err]
    banner = ('<div class="err"><button class="cp" style="float:right;margin-left:8px" onclick="cpBox(this,\'.err\')" title="copy errors">⧉</button>' + "<br>".join(probs) + "</div>") if probs else ""
    act = []
    for l in jn[-60:]:
        t = re.sub(r"^.*?llama-server\[\d+\]: ", "", l)
        if not t.strip() or "ensure_model: waiting" in t or BENIGN.search(t): continue
        cls = "e" if re.search(r"\bERROR\b|error:|failed|fatal", t, re.I) else ("a" if re.search(r"spawn|loaded|unloaded", t) else ("d" if "print_timing" in t else ""))
        act.append(f'<div class="l {cls}">{html.escape(t[-150:])}</div>')
    log = (f'<div class="card log"><b>ACTIVITY — model-router (tail-f, 2s)'
            f'<button class="cp" onclick="cpLog(this)" title="copy log">\u29C9</button></b>{"".join(reversed(act[-20:]))}</div>')
    return (banner + f'<div class="grid">{sysrow}</div><h2>inference</h2><div class="grid">{infrow}</div>',
            f'{log}')

HTML = """<!doctype html><html><head><meta charset=utf-8><title>Doctor</title>
<script src="https://unpkg.com/htmx.org@2"></script>
<script>function armOrd(m){fetch('/armorder?mode='+m)}</script>
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
document.addEventListener('htmx:afterSwap',e=>{if(e.target.id==='stats'){draw('tgline',H_TG);draw('accline',H_ACC);
if(lastTgV)document.getElementById('tgv').innerHTML=lastTgV;
if(lastAccV)document.getElementById('accv').innerHTML=lastAccV}})</script>
<script>function cpBox(btn,sel){var L=btn.closest(sel);var ls=L.textContent.trim();function done(ok){if(ok){btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u29C9',900)}}if(navigator.clipboard){navigator.clipboard.writeText(ls).then(()=>done(1),()=>done(0));return}var ta=document.createElement('textarea');ta.value=ls;ta.style.cssText='position:fixed;top:0;left:0;opacity:0';L.appendChild(ta);ta.select();var ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();done(ok)}
function peakReset(btn,key){fetch('/peak/reset'+(key?'/'+encodeURIComponent(key):'')).then(()=>{btn.textContent='\u2713';setTimeout(()=>btn.textContent='\u21ba',900)})}
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
h1{font-size:1.2em;color:#fff}h2{font-size:.95em;color:#888;margin:20px 0 8px}
summary{font-size:.95em;color:#888;margin:20px 0 8px;cursor:pointer;list-style:none}
summary::before{content:"▸ "}details[open] summary::before{content:"▾ "}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
h1 .up{float:right;font-size:.55em;color:#888;font-weight:normal}
.card{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:12px}
.card b{display:block;font-size:.8em;color:#888;margin-bottom:6px}
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
.log{margin-top:18px;font-family:ui-monospace,monospace;font-size:.72em;line-height:1.5;max-height:340px;overflow-y:auto}
.log .l{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#bbb}
.log .l.e{color:#ff6b6b}.log .l.a{color:#ffc46b}.log .l.d{color:#777}
.artab *{font-size:.78em !important}
.pill{display:inline-block;background:#1d7a2e;color:#eaffea;border-radius:9px;padding:1px 8px;font-size:1.25em;margin-left:8px;vertical-align:middle}
.pill.off{background:#3a3a3a;color:#999}
.artab{display:grid;grid-template-columns:minmax(0,max-content) minmax(52px,max-content) minmax(44px,max-content);gap:0 14px;font-size:.78em;margin-top:2px;line-height:1.5}
.artab > :nth-child(6n+4),.artab > :nth-child(6n+5),.artab > :nth-child(6n+6){background:#1d1d1d}
.artab > *{padding:1px 0}
.artab b{color:#666;font-weight:400}
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
<h1>Doctor · __HOST__ · system + inference<span class="up">__UPTIME__</span></h1>
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
    # ts,cpu,gpu,ram_avail,temp,load1 — CPU% via 1s /proc/stat delta.
    d = os.environ.get("DOCTOR_STATE_DIR", os.path.expanduser("~/.pi/agent/skills/doctor-dream/state"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "metrics.csv")
    if not os.path.exists(p):
        open(p, "w").write("ts,cpu,gpu,ram_avail,temp,load1\n")
    def _cpu():
        s1 = open("/proc/stat").readline().split()[1:5]; time.sleep(1)
        s2 = open("/proc/stat").readline().split()[1:5]
        t1, t2 = sum(map(int, s1)), sum(map(int, s2))
        return int(100 * (1 - (int(s2[3]) - int(s1[3])) / ((t2 - t1) or 1)))
    while True:
        try:
            g = 0
            for f in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
                try: g = max(g, int(open(f).read()))
                except Exception: pass
            t = 0
            for f in glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*/temp1_input"):
                try: t = max(t, int(open(f).read()) // 1000)
                except Exception: pass
            ram = next((int(x.split()[1]) for x in open("/proc/meminfo") if x.startswith("MemAvailable")), 0) // 1024
            l1 = open("/proc/loadavg").read().split()[0]
            row = f"{int(time.time())},{_cpu()},{g},{ram},{t},{l1}"
            with open(p, "a") as fh: fh.write(row + "\n")
        except Exception:
            pass
        time.sleep(60)

def checkup_html():
    # pi-doctor-dream: "Last night's checkup" card from panel.json
    try:
        pj = os.path.expanduser("~/.pi/agent/skills/doctor-dream/state/panel.json")
        d = os.path.getmtime(pj)
        p = json.load(open(pj))
        when = time.strftime("%a %H:%M", time.localtime(d))
        n = p.get("new", {}); b = p.get("backlog", {})
        nums = f"new: P1×{n.get('P1',0)} P2×{n.get('P2',0)} P3×{n.get('P3',0)} · backlog: {b.get('count',0)} (oldest {b.get('oldest_days',0)}d)"
        summ = "".join(f"<div class='l'>{html.escape(s)}</div>" for s in p.get("summary", [])[:6])
        # /chk body only — the collapsible box itself is STATIC html (outside the
        # 2s htmx swap) so the open/closed state survives refreshes, like .actbox
        return (f'<div class="card log"><b>LAST NIGHT\'S CHECKUP — {when} '
                f'</b><span style="color:#888">{nums}</span>'
                '<button class="cp" style="float:right" onclick="cpBox(this,\'.log\')" title="copy report">⧉</button>'
                f'{summ}'
                '<a href="/res/doctor" style="color:#4c9aff;font-size:.8em">full report</a></div>')
    except Exception:
        return ''

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/peak/reset" or self.path.startswith("/peak/reset/"):
            k = self.path.rsplit("/", 1)[-1] if "/" in self.path[13:] else None
            if k: PEAKS.pop(k, None)
            else: PEAKS.clear()
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
        elif self.path.startswith("/res/"):
            body, ct = res(self.path[5:]) or "<pre>?</pre>", "text/html"
        else:
            body, ct = (HTML.replace("__HOST__", socket.gethostname()).replace("__UPTIME__",
            (lambda t: f"up {int(t//86400)}d {int(t%86400//3600)}h {int(t%3600//60)}m")
            (float(open("/proc/uptime").read().split()[0])))), "text/html"
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body.encode())
    def log_message(self, *a): pass

if __name__ == "__main__":
    threading.Thread(target=_sampler, daemon=True).start()
    threading.Thread(target=_metrics_logger, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8667), H).serve_forever()
