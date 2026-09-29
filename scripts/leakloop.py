#!/usr/bin/env python3
"""Does tool markup sitting in the prompt make the model leak more?

The 18 stalls (Sep 26 + Sep 28, strixy2 champion) cluster in sessions that had
already leaked once, and pi's compaction summaries verifiably carry the raw
markup as plain text. Fresh probes never reproduce; this feeds the shapes back.

  python3 scripts/leakloop.py [url] [model] [n] [arm]

arm: clean   -> summary mentions tools in prose only
     markup   -> summary carries WELL-FORMED tool blocks as text
     broken   -> summary carries the MALFORMED blocks from the real stalls
                 (opening quote of the 2nd key missing)

NOTE: markup is assembled from LT/GT at runtime. A literal tag sequence inside
a tool-call value is itself a known trigger for the leak, so this file must not
contain one.
"""
import json
import os
import sys
import urllib.request

# The model thinks before it calls; a small budget truncates the call and looks
# like a leak. Real stalls were finish=stop, so keep this generous.
MAXT = int(os.environ.get("MAXT", "2048"))

URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.50.184:8080/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "default"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 6
ARM = sys.argv[4] if len(sys.argv) > 4 else "broken"

LT, GT = chr(60), chr(62)


def tag(name, body=""):
    return f"{LT}{name}{GT}{body}{LT}/{name}{GT}"


def block(path, payload):
    """One leaked edit block: path as a tag, then the raw JSON tail."""
    return (f"{LT}function=edit{GT}\n" + tag("parameter=path", path + "\n") +
            payload + "\n" + f"{LT}/function{GT}")


# Verbatim shape of the stalled turns: the 2nd key lost its opening quote.
BROKEN = "[assistant]\n" + "\n".join(
    "* edit %s -> raw block returned as text, not a tool call:\n%s" % (p, blk)
    for p, blk in [
        ("/tmp/app.py", block("/tmp/app.py",
            '",oldText":"' + chr(34) + 'def hi():' + chr(92) + 'n    return 1' +
            chr(34) + '","newText":"' + chr(34) + 'def handle(req, resp):' +
            chr(92) + 'n    return resp.json({ok: True})' + chr(34) + '"}]}')),
        ("/tmp/util.py", block("/tmp/util.py",
            '",oldText":"import os","newText":"import os' + chr(92) + 'nimport sys"}]}')),
    ])

MARKUP = "[assistant]\n" + "\n".join(
    "* edit %s -> raw block returned as text, not a tool call:\n%s" % (p, blk)
    for p, blk in [
        ("/tmp/app.py", tag("function=edit",
            tag("parameter=path", "/tmp/app.py\n") +
            tag("parameter=oldText", "def hi():\n    return 1\n") +
            tag("parameter=newText", 'def handle(req, resp):\n    return resp.json({"ok": True})\n'))),
        ("/tmp/util.py", tag("function=edit",
            tag("parameter=path", "/tmp/util.py\n") +
            tag("parameter=oldText", "import os\n") +
            tag("parameter=newText", "import os\nimport sys\n"))),
    ])

CLEAN = ("[assistant]\n* edited /tmp/app.py (replaced the hi() helper with a "
         "handle(req, resp) handler)\n* edited /tmp/util.py (added an import of sys)")

SUMMARY = {"broken": BROKEN, "markup": MARKUP, "clean": CLEAN}[ARM]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "edit",
        "description": "Edit a file with exact oldText -> newText replacements.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string"},
                            "newText": {"type": "string"},
                        },
                        "required": ["oldText", "newText"],
                    },
                },
            },
            "required": ["path", "edits"],
        },
    },
}]


def classify(msg, finish=""):
    calls = msg.get("tool_calls") or []
    content = msg.get("content") or ""
    leaked = (LT + "parameter" in content) or (LT + "function" in content)
    if finish == "length" and not leaked:
        return "truncated", content.replace("\n", " ")[:60]
    if calls:
        try:
            json.loads(calls[0]["function"]["arguments"])
            return "toolcall", ""
        except Exception as exc:
            return "badjson", str(exc)[:60]
    if leaked:
        frag = content[content.find(LT + "parameter"):]
        head = frag.replace("\n", " ")[:70]
        bare = any(f'",{k}' in frag for k in ("oldText", "newText", "path"))
        return ("leaked-BARE-KEY" if bare else "leaked"), head
    return "prose", content.replace("\n", " ")[:60]


def sample():
    body = {
        "model": MODEL,
        "max_tokens": MAXT,
        "temperature": 0.6,
        "tools": TOOLS,
        "messages": [
            {"role": "system",
             "content": "You are a coding agent. Use the edit tool to change files. "
                        "Never print tool markup as text."},
            {"role": "user",
             "content": "Earlier context from this session:\n\n" + SUMMARY +
                        "\n\nNow use the edit tool to add a docstring to def load() "
                        "in /tmp/loader.py."},
        ],
        "stream": False,
        "chat_template_kwargs": {"preserve_thinking": True, "reasoning_effort": "low"},
    }
    req = urllib.request.Request(
        URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    ch = d["choices"][0]
    return classify(ch["message"], ch.get("finish_reason", ""))


if __name__ == "__main__":
    counts = {}
    for i in range(N):
        state, detail = sample()
        counts[state] = counts.get(state, 0) + 1
        print(f"{i:2d} {state:15s} {detail}", flush=True)
    print(f"\nARM={ARM} n={N} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
