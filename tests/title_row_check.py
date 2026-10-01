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
    bad.append("#hact (the polled action slot) is missing")
if 'hx-get="/boxinfo"' not in html:
    bad.append("#hact no longer polls /boxinfo")

# every control the footer used to hold must still be reachable, and every lab service in
# the one dict must have its button (operator 261001: services kept appearing with none)
for path in ("/llmtoggle", "/svctoggle?u=demo", "/svctoggle?u=test"):
    if path not in row:
        bad.append(f"deleted control not moved up: {path}")
for key, (_name, port, units) in D.SVC_TOGGLES.items():
    if D._unit(f"{units[-1]}.service", "cat") and f"/svctoggle?u={key}" not in row:
        bad.append(f"{units[-1]} is installed but has no start/stop button")
    if f":{port}" not in row:
        bad.append(f"the {key} button does not say which port it belongs to")

# and the endpoints they POST to must still be served
served = open(SRC, encoding="utf-8").read()
for path in ("/llmtoggle", "/svctoggle"):
    if f'self.path.startswith("{path}"' not in served and f'self.path == "{path}"' not in served:
        bad.append(f"{path} has no route")
# The generic endpoint takes a key from the browser: the dict lookup is the whole
# authorisation (no auth on this LAN by operator decision), so it must refuse the rest.
if 'SVC_TOGGLES.get(_key)' not in served or 'unknown service' not in served:
    bad.append("/svctoggle does not resolve the key through SVC_TOGGLES - any unit name "
               "would reach systemctl")

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
    if not any(p == port for _, _, p, _ in D.LAB_UI):
        bad.append(f":{port} lost its icon when the footer links went")
# :7864 stays out of the row (operator 261001). LTX-2.5 has no render path on gfx1151, so
# an icon there would advertise a playground that cannot produce a video.
if any(p == 7864 for _, _, p, _ in D.LAB_UI):
    bad.append(":7864 is back in LAB_UI - LTX-2.5 still cannot render on this GPU")

# The open buttons exist only for what answers (operator 261001: hide the greyed ones), so
# the row's content depends on live ports. Force the probe and assert both states instead of
# trusting what happens to be up right now.
def _row_with(state):
    real = D.port_up
    D.port_up = lambda p: state
    try:
        return D.boxinfo("h")
    finally:
        D.port_up = real


_all_up, _all_down = _row_with(True), _row_with(False)
for ico, name, port, _tip in D.LAB_UI:
    if f">{ico} {name}</a>" not in _all_up:
        bad.append(f"the :{port} open button lost its text label")
    if f"http://h:{port}/" in _all_down:
        bad.append(f":{port} renders a button while stopped - a grey button you cannot "
                   "open is decoration, it must be hidden")
if 'class="lab dn"' in _all_down or ".lab.dn" in html:
    bad.append("the dim 'stopped' style is back - stopped services get no button at all")
if "\U0001F916 llm</a>" not in _all_up:
    bad.append("the :8080 open button lost its text label")
# Green is the whole point of showing only the live ones: the colour says "you can open this".
if "color:#6dd66d" not in html.split(".lab{")[1].split("}")[0]:
    bad.append(".lab is not green - a live open button looks like a dead control")
if "http://h:8080/" in _all_down:
    bad.append("the :8080 robot is rendered while the arm is down")
# The Anvil button is static (always up) but must say what it opens, like its neighbours.
if "</svg>anvil</a>" not in html:
    bad.append("the Anvil button has no text label")

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
if 'href="http://h:8188/"' not in _all_up:
    bad.append("/boxinfo no longer renders the lab buttons (the poll would drop them)")
if "box-refresh" not in html.split("function profGo")[1].split("\n</script>")[0]:
    bad.append("profGo does not dispatch box-refresh - a profile switch leaves the row stale")

# The `dn` class on every icon comes from port_up(), so the probe is part of the row's
# contract. It must not believe a TCP handshake to a relay: gradio-v6-relay (socat,
# ipv6only=1) accepts on [::]:7860 with nothing behind it, and the Qwen-Image icon stayed
# lit through every profile all day 261001. Conditional so it only bites where the relay runs.
def _open(host, port):
    try:
        __import__("socket").create_connection((host, port), 0.05).close()
        return True
    except OSError:
        return False


if _open("::1", 7860) and not _open("127.0.0.1", 7860) and D.port_up(7860):
    bad.append("port_up(7860) believes the IPv6 relay - a socket that accepts with no backend "
               "is DOWN (probe 127.0.0.1, not 'localhost')")

# The profile dropdown is state too, and it had the same bug the icons had: rendered once by
# `/`, outside every polled slot, so a CLI apply left it claiming the old profile until a
# hard reload (operator 261001). It must sit in its own polled chip, and the POST message
# must live OUTSIDE that chip or the swap erases the answer the click just got.
if 'hx-get="/profchip"' not in html:
    bad.append("the profile <select> is not in a polled fragment - a CLI apply leaves it stale")
if html.count("__PROF__") != 1 or 'id="profchip" hx-get="/profchip"' not in html:
    bad.append("__PROF__ must be rendered exactly once, inside #profchip")
chip = html.split('id="profchip"')[1].split("</span>")[0] if 'id="profchip"' in html else ""
if 'id="profmsg"' in chip:
    bad.append("#profmsg is inside the swapped chip - the switch result would vanish on the next poll")
# ...and it must not be inside the title row either: h1 is a flex row with ~160px of slack, so
# a long switch message wraps the whole row (measured 29px -> 48px at 26 characters, 261001).
if 'id="profmsg"' in html.split("<h1>")[1].split("</h1>")[0]:
    bad.append("#profmsg is inside <h1> - a long switch message wraps the title row")
if 'self.path == "/profchip"' not in served:
    bad.append("/profchip has no route")
# The chip must fill itself on load, and the first paint must be the placeholder: Chrome
# restores a <select>'s previous selection over the `selected` attribute when it re-renders
# the same URL, so a hard refresh used to show a profile that was never applied (261001).
if 'id="profchip" hx-get="/profchip" hx-trigger="load' not in html:
    bad.append("#profchip does not poll on load - the placeholder would sit there for 5s")
first_paint = served.split('replace("__PROF__",')[1].split("__WEBUI__")[0]
if "PROF_PLACEHOLDER" not in first_paint or "profile_select_html(" in first_paint:
    bad.append("`/` renders the real dropdown again - the browser can restore an old "
               "selection over it (PROF_PLACEHOLDER is the fix)")

# The control bar is a SECOND line (operator 261001: the title row was crowded). Line 1 is
# identity + profile, line 2 is the labelled open buttons with the uptime at their right, and
# the start/stop group gets a third line of its own. A browser check measures the geometry;
# this catches the markup/CSS contract.
if 'id="bar"' not in html:
    bad.append("#bar (the second line) is missing")
bar = html.split('id="bar"')[1].split("</div>")[0] if 'id="bar"' in html else ""
if 'id="hact"' not in bar:
    bad.append("#hact is not inside #bar - the buttons are back on the title row")
if html.split("<h1>")[1].split("</h1>")[0].count("<button") != 1:
    bad.append("a control other than #rst is back inside <h1>")
if 'class="opens"' not in row or 'class="tog"' not in row:
    bad.append("boxinfo() does not split the row into .opens and .tog")
opens, tog = row.split('class="opens"')[1].split("</span>")[0], row.split('class="tog"')[1]
for port in (8080, 8188, 7863):
    if f":{port}/" not in _all_up:
        bad.append(f"the :{port} open button is not in .opens")
for path in ("/llmtoggle", "/svctoggle?u=demo", "/svctoggle?u=test"):
    if path not in tog:
        bad.append(f"{path} is not in .tog (the start/stop group)")
# .tog is its OWN line under the icons (operator 261001), left-aligned on it.
if "#hact .tog{flex-basis:100%" not in html or "justify-content:flex-start" not in html:
    bad.append(".tog is not a left-aligned row of its own under the open buttons")
# and a running unit's label is green, a stopped one's is not
if "#hact .tog .cp.on{color:" not in html:
    bad.append("no green rule for a running service button")
# Parsed by splitting, not by regex: the onclick holds arrow functions, so the first '>' of
# a button tag sits inside the attribute, not before its label.
for chunk in row.split("</button>")[:-1]:
    label, green = chunk[chunk.rfind(">") + 1:], 'class="cp on"' in chunk
    if green != label.startswith("\u23f9"):
        bad.append(f"button {label!r}: green={green}, the glyph says the opposite")
if "#bar" not in html.split("<style>")[1].split("</style>")[0]:
    bad.append("#bar has no CSS - the second line would stack vertically")

# The open buttons carry their NAME next to the icon (operator 261001): seven bare glyphs
# meant hovering the whole row to find one page. Checked against _all_up above.

# The uptime rides the opens line (operator 261001), and with it the polling: it used to be
# substituted once by `/`, so it froze at page load for the rest of the day.
if "__UPTIME__" in html:
    bad.append("__UPTIME__ is back - the uptime would freeze at page load instead of polling")
if 'class="up"' not in row:
    bad.append("the uptime is not in the polled bar fragment")
if 'class="up"' in html.split("<h1>")[1].split("</h1>")[0]:
    bad.append("the uptime is back inside <h1>")
if "#bar .up{position:absolute;right:0" not in html:
    bad.append("the uptime is not pinned to the right end of the bar")
# The Anvil button is the same box as a lab icon, not a smaller one (261001, operator:
# "align the anvil button and icon to the other similar buttons size").
if "height:1.5em" not in html.split(".anv{")[1].split("}")[0]:
    bad.append(".anv has no fixed height - the anvil renders shorter than the lab icons")

print("FAIL " + "; ".join(bad) if bad else
      f"title row: no footer, {len(D.SVC_TOGGLES) + 1} toggles + {len(D.LAB_UI) + 1} labelled opens")
sys.exit(1 if bad else 0)