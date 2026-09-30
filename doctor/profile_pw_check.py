#!/usr/bin/env python3
"""profile_pw_check.py — drive the profile switch in a real browser.

Repo rule: a web/UI change is not verified by `curl` + substring. This navigates, reads the
DOM, POSTs the switch through the page's own fetch handler, and asserts the two things that
actually matter: the card the operator reads changed, and systemd agrees.

    uv run --with playwright python doctor/profile_pw_check.py            # panic, then restore
    uv run --with playwright python doctor/profile_pw_check.py --to lab-image

It RESTORES the stamp it found in a finally block, so a failed check still leaves the box
where it found it — but read the last line before trusting that: if the restore itself times
out the script says so loudly rather than pretending.

Refuses to run while the ComfyUI queue is busy: this test stops renderers on purpose, and
doing that to someone's render is not a test, it is an outage.

Sabotage (do it, then believe the green): point --base at a Doctor without the dropdown
(the pre-Task-7 build) and this must exit 1 on "select#prof", not pass on a substring.
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP = os.path.join(REPO, "scripts", "strix-profile")  # this checkout's tool, not whatever is on PATH
STAMP = os.path.expanduser("~/.config/strix/profile")


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


def sh_rc(*a):
    p = subprocess.run(a, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def unit_active(u):
    return sh("systemctl", "--user", "is-active", f"{u}.service") == "active"


def queue_busy():
    """Ask the renderer, not the GPU percentage — a render is idle between steps."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5) as r:
            return bool(json.load(r).get("queue_running"))
    except Exception:
        return False


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8667")
    ap.add_argument("--to", default="panic",
                    help="profile to switch to; panic is the one that must always be reachable")
    ap.add_argument("--timeout", type=int, default=180,
                    help="seconds to wait for the card AND systemd to agree")
    ap.add_argument("--shot", default="/tmp/profile-ui.png")
    a = ap.parse_args(argv)

    original = open(STAMP).read().strip() if __import__("os").path.exists(STAMP) else None
    if queue_busy():
        print("REFUSE: a render is running. This check stops renderers on purpose.")
        return 2

    from playwright.sync_api import sync_playwright
    fails = []

    def check(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)
        return cond

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(a.base, wait_until="networkidle")

        # 1 — the switch exists and says what the stamp says
        try:
            pg.wait_for_selector("select#prof", timeout=15000)
        except Exception:
            check(False, "select#prof exists (this Doctor has no profile switch — "
                         "wrong build or wrong port?)")
            b.close()
            return 1
        opts = pg.eval_on_selector_all("select#prof option", "els => els.map(e => e.value)")
        sel = pg.eval_on_selector("select#prof", "e => e.value")
        check(sel == original, f"dropdown selected = {sel!r}, stamp = {original!r}")
        check(a.to in opts, f"options include {a.to!r}: {opts}")

        # 2 — an unmanaged unit is not drift. Doctor.service is running and is not in
        # MANAGED_UNITS; if it ever shows up the drift set stopped being an allow-list.
        check("Doctor.service" not in pg.inner_html(".prof"),
              "unmanaged unit (Doctor.service) is not reported as drift")

        # 3 — switch through the page's own handler. What SHOULD happen is decided by the
        # same dry-run the server runs, so the check is honest before the gate exists and
        # still honest after: an ungated target must be REFUSED LOUDLY, a gated one must move.
        rc, out = sh_rc(SP, "apply", a.to, "--dry-run")
        expect = "refuse" if rc != 0 else "switch"
        print(f"  ..   {a.to}: dry-run rc={rc} -> expecting {expect}")
        pg.select_option("select#prof", a.to)
        try:
            pg.wait_for_function(
                "() => (document.getElementById('profmsg')||{}).textContent?.length > 1",
                timeout=30000)
        except Exception:
            pass
        msg = pg.inner_text("#profmsg") if pg.query_selector("#profmsg") else ""
        if expect == "refuse":
            check("NOT applied" in msg,
                  f"refusal is said out loud, not swallowed: {msg[:140]!r}")
            pg.reload(wait_until="networkidle")
            check(f"profile <b>{original}</b>" in pg.inner_html(".prof"),
                  "the card still names the real profile after a refusal")
            check(unit_active("sos-collm") is False or original == "panic",
                  "a refused apply started nothing")
        else:
            deadline = time.time() + a.timeout
            card_ok = sys_ok = False
            while time.time() < deadline and not (card_ok and sys_ok):
                pg.wait_for_timeout(3000)
                pg.reload(wait_until="networkidle")
                try:
                    card_ok = f"profile <b>{a.to}</b>" in pg.inner_html(".prof")
                except Exception:
                    card_ok = False
                # systemd's own answer, read outside the browser: the card is a claim, this is fact
                try:
                    cur = json.loads(sh(SP, "current", "--json"))
                    sys_ok = (cur.get("profile") == a.to and not cur.get("missing")
                              and unit_active(cur.get("text_arm") or "-"))
                except (ValueError, TypeError):
                    sys_ok = False
                card_ok = card_ok and pg.eval_on_selector("select#prof", "e => e.value") == a.to
            check(card_ok, f"card shows profile {a.to} and the dropdown agrees within {a.timeout}s")
            check(sys_ok, f"`{os.path.basename(SP)} current` says {a.to} with nothing missing "
                          f"and its text arm active")
        pg.screenshot(path=a.shot, full_page=True)
        print(f"  shot {a.shot}")
        b.close()

    # 4 — put the box back (only ever needed if something actually moved)
    now = None
    try:
        now = json.loads(sh(SP, "current", "--json")).get("profile")
    except (ValueError, TypeError):
        pass
    if original and now and now != original:
        print(f"restoring {original} …")
        subprocess.run([SP, "apply", original], capture_output=True, text=True)
        deadline = time.time() + a.timeout
        back = False
        while time.time() < deadline and not back:
            time.sleep(5)
            try:
                back = json.loads(sh(SP, "current", "--json")).get("profile") == original
            except (ValueError, TypeError):
                back = False
        if not back:
            print(f"  !! RESTORE INCOMPLETE: the box is not back on {original}. "
                  f"Run: {SP} apply {original}")
            fails.append("restore")

    print("PROFILE PW CHECK " + ("OK" if not fails else f"FAILED ({len(fails)})"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
