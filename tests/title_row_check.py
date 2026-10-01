#!/usr/bin/env python3
"""The title row is the whole chrome: no footer, and every deleted control still exists.

Why this exists (261001): the operator deleted the page footer. A footer is where the
start/stop buttons lived, so "remove the footer and move anything it held up" is only done
when each control still exists - and the failure mode is silent (a button that is simply
gone looks like a clean page). This asserts the contract without a browser.

    uv run --offline --no-project python tests/title_row_check.py
"""
import os
import sys
import types

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "doctor", "Doctor.py")
D = types.ModuleType("title_row_under_test")
D.__file__ = SRC
exec(compile(open(SRC, encoding="utf-8").read(), SRC, "exec"), D.__dict__)

bad = []
html, row = D.HTML, D.boxinfo()

if "boxfoot" in html or 'id="box"' in html:
    bad.append("the footer markup is back")
if 'id="hact"' not in html:
    bad.append("#hact (the polled action slot in h1) is missing")
if 'hx-get="/boxinfo"' not in html:
    bad.append("#hact no longer polls /boxinfo")

# every control the footer used to hold must still be reachable
for path in ("/llmtoggle", "/imgtoggle?app=demo", "/imgtoggle?app=test"):
    if path not in row:
        bad.append(f"deleted control not moved up: {path}")

# and the endpoints they POST to must still be served
served = open(SRC, encoding="utf-8").read()
for path in ("/llmtoggle", "/imgtoggle"):
    if f'self.path.startswith("{path}"' not in served and f'self.path == "{path}"' not in served:
        bad.append(f"{path} has no route")

# the two renamed buttons are icons, not words
if "\U0001F916" not in served:
    bad.append("the :8080 chat button is not the robot icon")
# the Anvil button is the SAME glyph as Anvil's own favicon, not a lookalike emoji: Unicode
# has no anvil, and headless Chromium here has no emoji font, so a glyph is unverifiable and
# a shared path is not. Fails if either file drifts.
ANVIL_PATH = ("M9 5v5c4.03 2.47-.56 4.97-3 6v3h15v-3c-6.41-2.73-3.53-7 1-8V5z"
              "M2 6c.81 2.13 2.42 3.5 5 4V6z")
if "\u2692" in served:
    bad.append("the Anvil button is still the ⚒ forge glyph")
fav = open(os.path.join(os.path.dirname(SRC), "anvil", "Anvil.html"), encoding="utf-8").read()
if ANVIL_PATH not in served:
    bad.append("the Anvil button is not the anvil path")
if ANVIL_PATH not in fav:
    bad.append("Anvil.html's favicon no longer matches the button (one glyph, two sources)")
for port in (3000, 8188, 7860, 7861, 7862, 7863):
    if not any(p == port for _, _, p in D.LAB_UI):
        bad.append(f":{port} lost its icon when the footer links went")
# :7864 stays out of the row (operator 261001). LTX-2.5 has no render path on gfx1151, so
# an icon there would advertise a playground that cannot produce a video.
if any(p == 7864 for _, _, p in D.LAB_UI):
    bad.append(":7864 is back in LAB_UI - LTX-2.5 still cannot render on this GPU")

# The icons must live INSIDE the polled fragment. They were rendered once by `/` and sat
# outside #hact, so starting any profile left every icon at its page-load colour until a
# hard refresh (operator 261001). A page that looks fine is the failure state here.
if '>__WEBUI__</span>' not in html:
    bad.append("__WEBUI__ is outside #hact again - the icons would freeze until a reload")
if html.count("__WEBUI__") != 1:
    bad.append(f"__WEBUI__ appears {html.count('__WEBUI__')}x in the template - str.replace "
               "renders the whole control group that many times (measured 261001: 16 icons, "
               "unsized buttons, the h1 wrapped to 3 lines)")
if 'hx-trigger="load, every 5s' not in html:
    bad.append("#hact lost its load/every-5s poll trigger")
if 'href="http://h:8188/"' not in D.boxinfo("h"):
    bad.append("/boxinfo no longer renders the lab icons (the poll would drop them)")
if "box-refresh" not in html.split("function profGo")[1].split("\n</script>")[0]:
    bad.append("profGo does not dispatch box-refresh - a profile switch leaves the row stale")

print("FAIL " + "; ".join(bad) if bad else "title row: no footer, 3 toggles + 8 icons present")
sys.exit(1 if bad else 0)
