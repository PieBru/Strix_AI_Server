#!/usr/bin/env python3
"""Single-file system monitor: embedded HTML + htmx, polls a /stats endpoint."""
import json, shutil, subprocess, time, threading, socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = """<!doctype html><html><head><meta charset=utf-8>
<title>sysmon</title>
<script src="https://unpkg.com/htmx.org@2"></script>
<style>
  body{font-family:system-ui;margin:40px auto;max-width:640px;color:#ddd;background:#111}
  h1{font-size:1.2em;margin:0 0 24px;color:#fff}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .card{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:14px}
  .card b{display:block;font-size:.85em;color:#888;margin-bottom:6px}
  .card span{font-size:1.4em}
  .bar{height:6px;background:#333;border-radius:3px;margin-top:8px}
  .bar i{display:block;height:100%;background:#4c9aff;border-radius:3px}
</style></head><body>
<h1>sysmon · __HOST__</h1>
<div class="grid" id="stats" hx-get="/stats" hx-trigger="every 2s" hx-swap="innerHTML">
  <div class="card"><b>GPU</b><span>…</span></div>
  <div class="card"><b>VRAM</b><span>…</span></div>
  <div class="card"><b>GPU temp</b><span>…</span></div>
  <div class="card"><b>GPU power</b><span>…</span></div>
  <div class="card"><b>RAM</b><span>…</span></div>
  <div class="card"><b>DISK</b><span>…</span></div>
</div>
</body></html>"""

def gpu():
    out = subprocess.run(["/opt/rocm/bin/rocm-smi"], capture_output=True, text=True, timeout=5).stdout
    row = [t for t in out.splitlines() if t.startswith("0 ") and "N/A" in t or "°C" in t]
    toks = row[-1].split() if row else []
    if len(toks) >= 4:
        return f"{toks[4]}", f"{float(toks[5][:-1]):.1f}W", f"{toks[-2]}", f"{toks[-1]}"  # temp, power, VRAM%, GPU%
    return "—", "—", "—", "—"

def gpuname():
    out = subprocess.run(["/opt/rocm/bin/rocminfo"], capture_output=True, text=True, timeout=5).stdout
    for ln in out.splitlines():
        if "Marketing Name" in ln and "CPU" not in ln:
            return ln.split(":", 1)[1].strip()
    return "—"

def ram():
    with open("/proc/meminfo") as f: d = dict(l.split(":", 1) for l in f)
    tot, free, avail = int(d["MemTotal"].split()[0]), int(d["MemFree"].split()[0]), int(d["MemAvailable"].split()[0])
    pct = 100 * (tot - avail) / tot
    return f"{pct:.0f}%", f"{(tot-avail)/1048576:.1f}/{tot/1048576:.0f} GiB", f"{avail/1048576:.0f} GiB free"

def disk():
    s = shutil.disk_usage("/")
    return f"{100*s.used/s.total:.0f}%", f"{s.used/1e9:.0f}/{s.total/1e9:.0f} GiB", f"{(s.total-s.used)/1e9:.0f} GiB free"

def stats():
    t, pw, vr, gp = gpu()
    dp, dt, dfree = disk()
    rp, rt, rfree = ram()
    def bar(p, color=None):
        return f'<div class="bar"><i style="width:{p}%;{f"background:{color};" if color else ""}"></i></div>'
    def heat(v): return f'hsl({120 - 1.2 * min(max(v, 0), 100)}, 90%, 55%)'  # green->yellow->red
    def tempbar(v):
        c = float(v[:-2]) if v.endswith("°C") else 0
        return bar(min(max(c, 0), 100), heat(c))   # 0..100°C -> 0..100%
    def powerbar(v):
        w = float(v[:-1]) if v.endswith("W") else 0
        return bar(min(max(w, 0), 100), heat(w))   # 0..100W -> 0..100%
    cards = [
        ("GPU", gp, bar(int(gp.strip("%")))),
        ("VRAM", vr, bar(int(vr.strip("%")))),
        ("GPU temp", t, tempbar(t)),
        ("GPU power", pw, powerbar(pw)),
        ("RAM", f"{rp} · {rt} · {rfree}", bar(int(rp.strip("%")))),
        ("DISK", f"{dp} · {dt} · {dfree}", bar(int(dp.strip("%")))),
    ]
    return ("".join(f'<div class="card"><b>{l}</b><span>{v}</span>{b}</div>' for l, v, b in cards)
        + f"<div class='card'><b>GPU model</b><span style='font-size:.9em'>{gpuname()}</span></div>")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/stats":
            body = stats().encode()
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(HTML.replace("__HOST__", socket.gethostname()).encode())

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8666), H).serve_forever()
