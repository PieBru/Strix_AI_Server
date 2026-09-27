"""Browser gate for the :7862 music UI — drive a real Generate click, prove nothing leaves the box.

    uv run --offline --with playwright python acestep/ui_check.py   # ~15 s after model load
Set URL to http://192.168.50.15:7862 to exercise the LAN path instead of loopback.

Pass = the generated wav is served over localhost with 200 and real bytes, the page shows
the RTF status line from the engine, and no non-localhost URL was ever requested.
(gradio 6 plays via a blob: built from GET /gradio_api/file=..., so the wav fetch is the
observable that the round trip completed.)
"""
import re, sys, time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:7862"
LOCAL = re.compile(r"^(blob:)?(https?|wss?)://(127.0.0.1|localhost|192.168.50.15|10.180.243.2)(:\d+)?/")
WAV = re.compile(r"/gradio_api/file=[^\s]*acestep_\d+\.wav")
allreq, hits = [], []

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.on("request", lambda r: allreq.append(r.url))
    pg = ctx.new_page()
    pg.on("response", lambda r: hits.append(r.status) if WAV.search(r.url) else None)
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    print("h1:", pg.locator("h1").first.inner_text())

    pg.get_by_label("Prompt").fill("dreamy synth pop with soft female vocals")
    pg.get_by_label("Lyrics").fill("[verse]\nwe build the night from neon air")
    pg.get_by_role("slider", name="range slider for Duration (s)").fill("5")
    pg.get_by_role("button", name="Generate").click()

    t0 = time.time()
    while time.time() - t0 < 240 and not hits:
        pg.wait_for_timeout(1000)
    wav_url = next((u for u in allreq if WAV.search(u)), None)
    print(f"wav fetched after {time.time()-t0:.1f}s:", wav_url)

    stat = re.findall(r"seed \d+ ·[^|]*RTF[^|]*", pg.inner_text("body"))
    print("status line:", stat[0] if stat else "(none)")
    print("audio elements:", pg.evaluate(
        "() => [...document.querySelectorAll('audio')].map(a => ({src: (a.src||'').slice(0,60), dur: a.duration}))"))
    fetch = ctx.request.get(wav_url) if wav_url else None
    nbytes, fstatus = len(fetch.body()), fetch.status
    pg.screenshot(path="/tmp/ace_ui.png", full_page=True)
    b.close()

ext = [u for u in allreq if not LOCAL.match(u)]
ok = bool(hits) and all(s == 200 for s in hits) and fetch is not None \
    and nbytes > 10000 and bool(stat) and not ext
print("wav fetch:", fstatus, nbytes, "bytes",
      "| non-localhost requests:", len(ext), ext[:3])
print("G4:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
