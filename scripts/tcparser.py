#!/usr/bin/env python3
"""Black-box probe of the serving engine's XML tool-argument parser.

Each case asks the model to emit a tool call whose argument carries a tricky
shape; we report whether the server returned a structured call or dropped it and
handed the raw markup back as plain text (which is what stalls an agent harness:
the harness renders the markup and ends the turn).

  python3 tcparser.py [base] [model]

Baseline 260929, strixy2 (gufo b722a61): 4/6 degraded.
Tags are assembled from chr() so this file never contains tool markup itself.
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "newtest"
SL, SR = chr(60), chr(62)
CLOSE = SL + "/parameter" + SR
OPENP = SL + "parameter=" + SR
OPENF = SL + "function=" + SR
MARK = SL + "parameter"

TOOLS = [{"type": "function", "function": {
    "name": "bash", "description": "Run a bash command.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "Shell command"},
        "timeout": {"type": "number", "description": "Timeout seconds"}},
        "required": ["command"]}}}]

CASES = [
    ("plain", "Call bash with command: echo hello"),
    ("close-tag-in-value", "Call bash with command: echo " + chr(39) + CLOSE + chr(39)),
    ("open-tag-in-value", "Call bash with command: echo " + chr(39) + OPENP + "x" + SR),
    ("function-tag-in-value", "Call bash with command: echo " + chr(39) + OPENF + "bash" + SR),
    ("multiline-quotes", "Call bash with command: printf 'a'\nb'\n and a double quote"),
    ("numeric-param", "Call bash with command echo hi and timeout 45"),
]

bad = 0
for name, instr in CASES:
    body = {"model": MODEL, "messages": [
        {"role": "system", "content": "You are pi. Always answer by calling a tool."},
        {"role": "user", "content": instr}],
        "tools": TOOLS, "max_tokens": 200, "stream": False}
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
    except Exception as e:
        print(f"{name:22s} REQUEST FAILED {e}")
        bad += 1
        continue
    dt = time.time() - t0
    ch = d["choices"][0]
    m = ch["message"]
    calls = m.get("tool_calls") or []
    txt = m.get("content") or ""
    flag = []
    if not calls:
        flag.append("NO-CALL")
        if MARK in txt or OPENF in txt:
            flag.append("LEAKED-MARKUP")
    else:
        a = calls[0]["function"]["arguments"]
        try:
            json.loads(a)
        except Exception as e:
            flag.append(f"BAD-JSON({e})")
        if MARK in a or OPENF in a:
            flag.append("MARKUP-IN-ARGS")
    if flag:
        bad += 1
    shown = calls[0]["function"]["arguments"] if calls else txt[-120:]
    print(f"{name:22s} {dt:5.1f}s finish={ch.get('finish_reason')} "
          f"{' '.join(flag) or 'OK'} args={json.dumps(shown)[:160]}")

print(f"\n{bad}/{len(CASES)} degraded")
