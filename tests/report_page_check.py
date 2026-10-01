#!/usr/bin/env python3
"""The morning-report page: markdown in, HTML out, and the date on the page.

The complaint (operator 261001): /res/doctor was the raw .md in a <pre> — headings, ** and a
table arrived as punctuation — and nothing said WHICH night you were reading.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "doctor"))
import Doctor as D

# --- the converter -------------------------------------------------------------
h = D.md_html("# DOCTOR REPORT — 2026-10-01\n## 1. Verdict\n**P0 — 1** · P1 — 2\n"
              "- gate: `idle-gate` refused\n| arm | t/s |\n|---|---|\n| 27b | 6.2 |\n---\n")
assert "<h3>DOCTOR REPORT — 2026-10-01</h3>" in h, h          # '#' is a title, not an h1
assert "<h4>1. Verdict</h4>" in h, h
assert "<b>P0 — 1</b>" in h, h
assert "<code>idle-gate</code>" in h, h
assert "<div class='li'>gate:" in h, h
assert "<hr>" in h, h
assert "<th>arm</th>" in h and "<td>27b</td>" in h, h
assert "|---|" not in h and "<table>" in h, h
assert "<td>---</td>" not in h, "the |---| rule row must not become a data row"

# a report is machine-generated text: markup inside a finding must not become markup
evil = D.md_html("# <script>alert(1)</script>\n**<b>x</b>** `|a|`")
assert "<script>" not in evil and "&lt;script&gt;" in evil, evil
assert "<b>&lt;b&gt;x&lt;/b&gt;</b>" in evil, evil

# deep headings clamp, a lone '|' is prose
assert "<h6>" in D.md_html("###### deep\n####### deeper\n")
assert "<table>" not in D.md_html("a | b | c\n"), "only a leading pipe opens a table"

# --- the page ------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    for name, body in [("DOCTOR_REPORT_261001-101403.md", "# one\n"),
                       ("DOCTOR_REPORT_261001-191145.md", "# two\n"),
                       ("DOCTOR_REPORT_260930-033922.md", "# three\n"),
                       ("NOT-A-REPORT.md", "# nope\n")]:
        open(os.path.join(tmp, name), "w").write(body)
    page = D.doctor_page(skill=tmp)
    assert "<h2>DOCTOR REPORT — 261001 19:11</h2>" in page, page[:200]   # newest, by name
    assert "<h3>two</h3>" in page, page
    assert "260930 03:39" in page, "the recent reports must be reachable"
    assert "NOT-A-REPORT" not in page, page
    # ?f= picks an older night
    old = D.doctor_page("DOCTOR_REPORT_260930-033922.md", skill=tmp)
    assert "<h3>three</h3>" in old and "260930 03:39" in old
    assert "class='cur'" in old
    # traversal / arbitrary names are refused, never opened
    for bad in ["../../Doctor.py", "/etc/passwd", "DOCTOR_REPORT_261001-101403.md;rm",
                "..%2fDOCTOR_REPORT_261001-101403.md", ""]:
        got = D.doctor_page(bad, skill=tmp)
        assert "<h3>two</h3>" in got, f"{bad!r} must fall back to the newest, not be opened"
    assert D.doctor_page(skill=tempfile.mkdtemp()) .startswith("<pre>no doctor report")

print("report_page_check: ok")
