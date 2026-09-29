#!/usr/bin/env python3
"""Reproduce the dropped-quote tool-call corruption, speculation ON vs OFF.

Observed in 17/17 stalled pi turns (260926..260928, strixy2 champion): the model
emitted a well-formed XML tool block whose JSON was invalid because the opening
quote of the second key was missing — [{"newText":"...",oldText":"..."}]. gufo
then correctly refused to parse it and handed the markup back as text, which is
what stalls the harness. This script asks for that exact object shape N times and
counts how often the quote goes missing, so the variable under test is the MTP
draft, not the parser.

  python3 tcspec.py [base] [model] [n] [pad_tokens]

pad_tokens stuffs the conversation with real file text ahead of the request, so
the long-context regime where the stalls were seen (~100k) can be reproduced.

Tags are built from chr() so this file contains no tool markup itself.
"""
import json
import re
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "newtest"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 12
PAD = int(sys.argv[4]) if len(sys.argv) > 4 else 0
# 'pi' replays what pi actually sends to a chat-template thinking endpoint.
MODE = sys.argv[5] if len(sys.argv) > 5 else "plain"
# Length of the newText payload, in chars. Every observed stall dropped the quote
# immediately after a long string value, so this is the variable under test.
VLEN = int(sys.argv[6]) if len(sys.argv) > 6 else 60
# Sampling temperature. The Spark SOS arm emits a DIFFERENT tool-call markup shape per
# sample at 0.6 (260929 battery), and the fork's PEG parser 500s on any shape it cannot
# consume to the end - so temp is the variable that decides whether the arm is servable.
TEMP = float(sys.argv[7]) if len(sys.argv) > 7 else 0.6


def filler(tokens):
    """Roughly `tokens` tokens of real repo text (chars/3.5 is close enough here)."""
    import pathlib
    src = []
    for p in ("scripts/tcparser.py", "sos/check.py", "scripts/gguf_meta.py"):
        try:
            src.append(pathlib.Path(p).read_text())
        except OSError:
            pass
    blob = "\n\n".join(src) or "filler text. " * 200
    need = int(tokens * 3.5)
    out = (blob * (need // len(blob) + 1))[:need]
    return "Context so far (for reference):\n" + out

LT, GT = chr(60), chr(62)
OPENF = LT + "function="
CLOSEP = LT + "/parameter" + GT

TOOLS = [{"type": "function", "function": {
    "name": "edit",
    "description": "Edit a file with exact text replacements.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit"},
            "edits": {"type": "array", "description": "Replacements", "items": {
                "type": "object",
                "properties": {
                    "newText": {"type": "string", "description": "Replacement text"},
                    "oldText": {"type": "string", "description": "Text to replace"}},
                "required": ["oldText", "newText"]}}},
        "required": ["path", "edits"]}}}]

def long_block(n):
    """A code-ish payload of ~n chars with quotes, newlines and braces in it."""
    unit = ('def handle(req, reply):\n    cfg = {"timeout": 30, "name": "champion"}\n'
            '    if req.kind == "edit":\n        return apply(cfg, req.body)  # note\n\n')
    return (unit * (n // len(unit) + 1))[:n]


PROMPT = (
    "Call edit on /tmp/app.py with one replacement. oldText is the two lines "
    "def hi():\\n    return 1 . newText is exactly this block:\\n\\n"
    + long_block(VLEN)
    + "\\n\\nEmit only the tool call."
)

# The defect we hunt: a comma followed by a bare key, i.e. ,"oldText" lost its quote.
BARE_KEY = re.compile(r',\s*(oldText|newText|path|command|content)\s*:')

ok = leaked = bare = badjson = 0
for i in range(N):
    sysmsg = "You are a coding agent. Always answer by calling a tool."
    if PAD:
        sysmsg = filler(PAD) + "\n\n" + sysmsg
    body = {"model": MODEL, "messages": [
        {"role": "system", "content": sysmsg},
        {"role": "user", "content": PROMPT}],
        "tools": TOOLS, "max_tokens": 2000, "temperature": TEMP, "stream": False}
    if MODE == "pi":
        body["chat_template_kwargs"] = {"enable_thinking": True, "reasoning_effort": "low",
                                        "preserve_thinking": True}
        body["reasoning_budget"] = 512
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
        el = time.time() - t0
    except Exception as e:
        print(f"{i:2d} REQUEST FAILED {e}")
        continue
    ch = d["choices"][0]["message"]
    calls = ch.get("tool_calls") or []
    txt = ch.get("content") or ""
    if calls:
        raw = calls[0]["function"]["arguments"]
        try:
            json.loads(raw)
            ok += 1
            tag = "parsed"
        except Exception as e:
            badjson += 1
            tag = f"BAD-JSON {e}"
    else:
        leaked += 1
        tag = "LEAKED"
        if OPENF in txt or CLOSEP in txt:
            m = re.search(r'\[\{[^\]]*\}\]', txt, re.S)
            v = m.group(0) if m else ""
            if BARE_KEY.search(v):
                bare += 1
                tag += " BARE-KEY(quote dropped)"
            elif v:
                try:
                    json.loads(v)
                    tag += " json-was-valid"
                except Exception as e:
                    tag += f" json-invalid {e}"
    # tok/s are per-request: on a thinking model most of them are reasoning, which is
    # the tax a coding harness pays per turn (SOS Q4-vs-Q6, 260929).
    u = d.get("usage", {})
    print(f"{i:2d} {tag}  [{u.get('completion_tokens','?')}tok {el:.1f}s]  "
          f"{json.dumps((calls[0]['function']['arguments'] if calls else txt)[:200])[:200]}")

print(f"\nn={N} parsed={ok} badjson={badjson} leaked={leaked} of-which-bare-key={bare}")
