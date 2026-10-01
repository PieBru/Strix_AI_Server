#!/usr/bin/env python3
"""Browser check of /res/doctor: it reads like a report, says which night it is, and the
nav actually switches nights."""
import re

try:
    from playwright.sync_api import sync_playwright
except ImportError:                     # run-all.sh runs bare; run me with: uv run --with playwright
    print("SKIP: playwright not installed")
    raise SystemExit(0)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 1000})
    pg.goto("http://localhost:8667/res/doctor")
    pg.wait_for_selector("h2")
    t = pg.inner_text("h2")
    assert t.startswith("DOCTOR REPORT — "), t
    assert re.search(r"\d{6} \d{2}:\d{2}", t), f"no date on the page: {t!r}"
    body = pg.inner_text("body")
    assert "**" not in body, "raw markdown still visible"
    assert not re.search(r"(?m)^#+\s", body), "raw heading still visible"   # bare #NNN PR refs are content
    mark = pg.evaluate("getComputedStyle(document.querySelector('.li'),'::before').content")
    assert "2022" in mark or "\u2022" in mark, f"bullets invisible: {mark}"
    n_h = pg.eval_on_selector_all("h3,h4,h5", "e=>e.length")
    assert n_h >= 5, f"only {n_h} rendered headings"
    rows = pg.eval_on_selector_all("table td", "e=>e.length")
    print("headings", n_h, "table cells", rows, "|", t)
    pg.screenshot(path="/tmp/report-top.png")

    links = pg.eval_on_selector_all(".nav a", "e=>e.map(x=>x.textContent)")
    assert len(links) >= 2, links
    pg.click(".nav a:nth-child(2)")
    for _ in range(20):
        t2 = pg.inner_text("h2")
        if t2 != t:
            break
        pg.wait_for_timeout(250)
    assert t2 != t and links[1] in t2, (t, t2, links)
    cur = pg.eval_on_selector(".nav a.cur", "e=>e.textContent")
    print("nav:", links[:3], "-> now", t2, "| marked", cur)
    pg.screenshot(path="/tmp/report-old.png")
    b.close()
print("report_browser_check: ok")
