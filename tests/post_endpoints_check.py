#!/usr/bin/env python3
"""Every POST branch must answer. /storm/reset and /imgtoggle used to set body/ct and
then fall off the end of the if/elif chain: the systemctl call ran, the browser got a
closed socket (curl 000), and the button read as broken. Checked statically so the suite
never starts or stops a real unit. (operator 261001)"""
import io
import os
import re
import sys

SRC = os.path.join(os.path.dirname(__file__), os.pardir, "doctor", "Doctor.py")
lines = io.open(SRC, encoding="utf-8").read().splitlines()
start = next(i for i, l in enumerate(lines) if l.strip() == "def do_POST(self):")
end = next(i for i in range(start + 1, len(lines)) if re.match(r"    def \w", lines[i]))
body = lines[start:end]

bad = []
n_resp = sum(l.count("send_response(") for l in body)
n_end = sum(l.count("end_headers(") for l in body)
if n_resp != 1 or n_end != 1:
    bad.append(f"do_POST writes {n_resp} responses / {n_end} end_headers; want exactly one "
               "shared writer at the end of the chain")

# A branch that writes its own response is a branch that can forget it.
branch = None
branches = 0
for l in body:
    m = re.match(r"\s*(?:if|elif) self\.path", l)
    if m:
        branch = l.strip()
        branches += 1
    if "send_response(" in l and (len(l) - len(l.lstrip())) >= 12:
        bad.append(f"{branch} responds inline instead of falling through to the writer")

# The two endpoints that were dead must exist and must not be inline writers.
for ep in ("/storm/reset", "/imgtoggle"):
    if not any(ep in l for l in body):
        bad.append(f"{ep} is gone from do_POST")

if bad:
    print("POST endpoints: FAIL")
    for b in bad:
        print("  -", b)
    sys.exit(1)
print(f"POST endpoints: one shared writer, {branches} branches")
