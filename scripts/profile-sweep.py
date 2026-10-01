#!/usr/bin/env python3
"""profile-sweep — apply every profile and prove the box AND the Doctor row agree with it.

Three different failure modes per profile, checked separately:
  1. the unit set matches the profile's allow-list (nothing missing, nothing extra, no drift)
  2. every server the profile owns actually ANSWERS — a real HTTP exchange over IPv4
     loopback, not a listening socket: gradio-v6-relay (socat, ipv6only=1) completes the TCP
     handshake with its backend gone, and a connect-probe called that "live" all day 261001
  3. the Doctor title row, in a real browser, shows exactly that state: <select> on the
     profile, every toggle ⏹ iff its unit is active, every icon link lit iff its port
     answers HTTP, still one line, no horizontal overflow

Expectations come out of the repo (the .ini allow-lists, Doctor's LAB_UI and ARM_TAG,
strix-profile's MANAGED_UNITS), never restated here, so the sweep cannot drift from the app.
Ports get a ceiling to come up (ComfyUI loads 46 GB of H3 weights); "not yet" is reported
with the seconds it took, "never" is a failure.

Usage (offline, from the repo root):
    uv run --with playwright python scripts/profile-sweep.py off panic 'lab-image:force'
    uv run --with playwright python scripts/profile-sweep.py            # all 8, safe order
A name suffixed ':force' is retried with --force when the gate refuses it; without the
suffix a refusal is recorded as the profile's own verdict and the sweep moves on.
Writes /tmp/sweep/<profile>.json, <profile>-row.png, <port>.png and report.json.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP = os.path.join(ROOT, "scripts", "strix-profile")
INIS = os.path.join(ROOT, "configs", "profiles")
DOC = os.path.join(ROOT, "doctor", "Doctor.py")
OUT = "/tmp/sweep"
DOCTOR = "http://127.0.0.1:8667"

# Ports each unit must answer on once active. The four arms share :8080 (Conflicts keeps one).
PORTS = {
    "27b-collm": [8080], "gemma-collm": [8080], "llama-llm": [8080], "gufo-llm": [8080],
    "sos-collm": [8082], "gufo-serve": [8081], "qwen-image-test": [7860],
    "qwen-image-demo": [7860], "comfyui-h3": [8188], "h3-video-ui": [7861],
    "acestep-serve": [8001], "acestep-ui": [7862], "whisper-stt": [7863], "ltx25-ui": [7864],
}
# Seconds a port is allowed to take after its unit is active (weights, not unit start).
CEIL = {8188: 240, 8081: 200, 8080: 180, 7860: 90, 7862: 90, 8001: 60, 8082: 60,
        7861: 60, 7863: 60, 7864: 60}
GRADIO = (7860, 7861, 7862, 7863, 7864)   # rendered by the browser, not by urllib
PATH = {8080: "/v1/models", 8082: "/v1/models", 8001: "/health"}
MARK = {8080: '"models"', 8082: '"models"'}   # the right thing answered, not just something
DEFAULT = ["off", "panic", "emergency", "lab-audio", "coding", "lab-image:force",
           "lab-video", "lab-all"]


def txt(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def managed_units():
    body = re.search(r"(?ms)^MANAGED_UNITS = \((.*?)^\)", txt(SP), re.M).group(1)
    return tuple(re.findall(r'"([\w-]+)"', body))          # quoted unit names, not prose


def profile_start(name, units_all):
    """The ini's allow-list, continuation lines included (lab-all wraps over three)."""
    t = txt(os.path.join(INIS, name + ".ini"))
    m = re.search(r"(?ms)^start\s*=\s*(.*?)(?=^\w|\Z)", t)
    return [u for u in re.findall(r"[\w-]+", m.group(1) if m else "") if u in units_all]


def doctor_maps():
    t = txt(DOC)
    tag = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"',
                          re.search(r"ARM_TAG = \{(.*?)\}", t, re.S).group(1)))
    lab = [int(p) for _ico, _n, p in
           re.findall(r'\("(\\U[0-9a-fA-F]{8}|.)",\s*"([^"]*)",\s*(\d+)\)',
                      re.search(r"LAB_UI = \[(.*?)\]\n", t, re.S).group(1))]
    return tag, lab


def sh(*a, timeout=420):
    p = subprocess.run(a, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def active(u):
    return sh("systemctl", "--user", "is-active", u, timeout=15)[1] == "active"


def _http(port, path):
    """0 = nothing answered. An HTTPError is still a server being there (404 counts)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2.0) as r:
            return r.status, r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                    # noqa: BLE001
        return 0, type(e).__name__


async def http(port, path="/"):
    return await asyncio.to_thread(_http, port, path)


async def renders(pg, port):
    """A gradio page must actually mount a widget, not just return bytes."""
    try:
        await pg.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=45000)
        await pg.wait_for_selector("gradio-app, .gradio-container", timeout=30000)
        await pg.screenshot(path=f"{OUT}/{port}.png")
        return True, ""
    except Exception as e:                                    # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e).splitlines()[0][:80]}"


def owner_ok(unit, port):
    """The IPv4 listener on the port must belong to the unit systemd credits for it.
    'active' + 'the port answers' is not the same statement as 'this unit serves it': a stale
    process, or the arm that was supposed to be stopped, satisfies both."""
    out = sh("ss", "-ltnp", f"( sport = :{port} )", timeout=20)[1]
    m = re.search(r"pid=(\d+)", out)
    main = int(sh("systemctl", "--user", "show", f"{unit}.service", "-p", "MainPID",
                  "--value", timeout=15)[1] or 0)
    if not m:
        return f":{port} has no IPv4 listener although {unit} is active"
    pid, chain = int(m.group(1)), set()
    while pid > 1 and pid not in chain:
        chain.add(pid)
        try:
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            break
    if pid == main or main in chain:
        return None
    return f":{port} is served by pid {m.group(1)}, not by {unit} (MainPID {main})"


async def wait_port(pg, unit, port):
    """Poll until the port answers what it is supposed to answer. Returns (seconds, error)."""
    t0 = time.time()
    while True:
        if port in GRADIO:
            ok, why = await renders(pg, port)
        else:
            code, body = await http(port, PATH.get(port, "/"))
            want = MARK.get(port)
            ok, why = bool(code) and (not want or want in body), f"HTTP {code} {body[:40]}"
        if ok:
            return round(time.time() - t0, 1), None
        if time.time() - t0 > CEIL.get(port, 60):
            return round(time.time() - t0, 1), f"{unit}:{port} never answered ({why})"
        await asyncio.sleep(5)


async def check_row(pg, prof, live, arm_tag, icon_ports):
    """The Doctor's title row must show exactly the live state, on one line."""
    bad = []
    # What is really up, probed independently of the app's own probe.
    alive = {}
    for port in sorted(set(icon_ports) | {8080}):
        alive[port] = bool((await http(port, "/"))[0])
    await pg.goto(DOCTOR + "/", wait_until="load")
    await pg.wait_for_selector("#hact button.cp", timeout=20000)
    await pg.wait_for_timeout(1500)                            # let the 5s poll land once
    sel = await pg.locator("select#prof").input_value()
    if sel != prof:
        bad.append(f"profile select shows {sel!r}, applied {prof!r}")

    icons = await pg.evaluate("""[...document.querySelectorAll('#hact a.lab')].map(a => ({
        port: +new URL(a.href).port, dn: a.classList.contains('dn')}))""")
    have = {i["port"] for i in icons}
    for port in sorted(set(icon_ports) | {8080}):
        if port not in have:
            bad.append(f"no icon link for :{port} in the row")
    for i in icons:
        if i["dn"] == alive[i["port"]]:
            bad.append(f"icon :{i['port']} dn={i['dn']} but HTTP says "
                       f"{'alive' if alive[i['port']] else 'dead'}")

    back = {v: k for k, v in arm_tag.items()}                  # "27b" -> "27b-collm"
    for label in await pg.locator("#hact button.cp").all_inner_texts():
        m = re.match(r"([⏹▶])\s+(\S+)\s+:(\d+)", label.strip())
        if not m:
            bad.append(f"unparsable toggle {label!r}")
            continue
        unit = back.get(m.group(2)) or {"demo": "qwen-image-demo",
                                        "test": "qwen-image-test"}.get(m.group(2))
        if unit is None:
            bad.append(f"toggle {label!r} names no unit I know")
            continue
        if (m.group(1) == "⏹") != active(unit):
            bad.append(f"toggle {label.strip()!r} but {unit} is "
                       f"{'active' if active(unit) else 'inactive'}")

    box = await pg.locator("h1").bounding_box()
    if box["height"] > 40:
        bad.append(f"title row is {box['height']:.0f}px tall (one line is ~29)")
    if await pg.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        bad.append("row overflows horizontally")
    await pg.screenshot(path=f"{OUT}/{prof}-row.png", clip={
        "x": 0, "y": box["y"] - 6, "width": 1440, "height": box["height"] + 12})
    return bad


async def sweep(specs):
    os.makedirs(OUT, exist_ok=True)
    units_all, (arm_tag, lab_ports) = managed_units(), doctor_maps()
    results = []
    async with async_playwright() as p:
        br = await p.chromium.launch()
        ctx = await br.new_context(viewport={"width": 1440, "height": 900})
        page, ui = await ctx.new_page(), await ctx.new_page()
        for spec in specs:
            prof, force = (spec.split(":")[0], spec.endswith(":force")) if ":" in spec else (spec, False)
            print(f"\n=== {prof}{' (force allowed)' if force else ''} ===", flush=True)
            code, out = sh(sys.executable, SP, "apply", prof, timeout=900)
            print("    " + out.replace("\n", "\n    "), flush=True)
            gate = "applied"
            if code != 0 and "refus" in out.lower():
                if not force:
                    results.append({"profile": prof, "gate": "gate refused (not forced)",
                                    "verdict": "REFUSED", "failures": [],
                                    "note": out.splitlines()[0][:160]})
                    continue
                code, out = sh(sys.executable, SP, "apply", prof, "--force", timeout=900)
                print("    --force: " + out.replace("\n", "\n    "), flush=True)
                gate = "gate refused, forced"
            if code != 0:
                results.append({"profile": prof, "gate": gate, "verdict": "APPLY FAILED",
                                "failures": [out[-300:]]})
                continue

            rc, cur = sh(sys.executable, SP, "current", timeout=60)
            print("    " + cur.replace("\n", "\n    "), flush=True)
            live = [u for u in units_all if active(u)]
            want = profile_start(prof, units_all)
            bad = []
            if f"profile={prof}" not in cur:
                bad.append(f"stamp is not {prof}: {cur.splitlines()[0]}")
            if "DRIFT" in cur:
                bad.append([l for l in cur.splitlines() if "DRIFT" in l][0].strip())
            for u in want:
                if u not in live:
                    bad.append(f"{u} in the allow-list but not active")
            for u in live:
                if u not in want:
                    bad.append(f"{u} active but not in the allow-list")

            ready = {}
            for u in live:
                for port in PORTS.get(u, []):
                    if port in ready:
                        continue
                    secs, err = await wait_port(ui, u, port)
                    ready[port] = secs
                    print(f"      {u}:{port} {'ready in ' + str(secs) + 's' if not err else err}",
                          flush=True)
                    if err:
                        bad.append(err)
                    else:
                        e = owner_ok(u, port)
                        if e:
                            bad.append(e)
            bad += await check_row(page, prof, live, arm_tag, lab_ports)
            results.append({"profile": prof, "gate": gate, "running": live,
                            "port_ready_s": ready, "verdict": "PASS" if not bad else "FAIL",
                            "failures": bad})
            print(f"    -> {results[-1]['verdict']}" +
                  ("" if not bad else "\n      " + "\n      ".join(bad)), flush=True)
        await br.close()
    with open(f"{OUT}/report.json", "w") as f:
        json.dump(results, f, indent=1)
    print("\n================ verdicts ================")
    for r in results:
        print(f"{r['profile']:<12} {r['gate']:<26} {r['verdict']}"
              + ("" if r["verdict"] != "FAIL" else f"  ({len(r['failures'])})"))
    return 0 if all(r["verdict"] != "FAIL" for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(sweep(sys.argv[1:] or DEFAULT)))
