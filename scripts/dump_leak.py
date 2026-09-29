#!/usr/bin/env python3
"""Dump one FULL leaked response from strixy2 so the parser failure is visible.

  python3 scripts/dump_leak.py [url] [model] [tries]

Prints the raw assistant content of the first non-tool-call turn, plus the
finish reason and whether the block looks complete (has a closing function tag).
Markup is assembled from chr(60)/chr(62): a literal tag inside a tool-call value
is itself hazardous for the calling agent.
"""
import json
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.50.184:8080/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "default"
TRIES = int(sys.argv[3]) if len(sys.argv) > 3 else 8

LT, GT = chr(60), chr(62)

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


def ask():
    body = {
        "model": MODEL,
        "max_tokens": 400,
        "temperature": 0.6,
        "tools": TOOLS,
        "messages": [
            {"role": "system",
             "content": "You are a coding agent. Use the edit tool to change files. "
                        "Never print tool markup as text."},
            {"role": "user",
             "content": "Earlier context from this session:\n\n* edited /tmp/app.py "
                        "(replaced the hi() helper with a handle(req, resp) handler)\n"
                        "* edited /tmp/util.py (added an import of sys)\n\n"
                        "Now use the edit tool to add a docstring to def load() in "
                        "/tmp/loader.py."},
        ],
        "stream": False,
        "chat_template_kwargs": {"preserve_thinking": True, "reasoning_effort": "low"},
    }
    req = urllib.request.Request(
        URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    ch = d["choices"][0]
    return ch, ch["message"]


if __name__ == "__main__":
    for i in range(TRIES):
        ch, msg = ask()
        calls = msg.get("tool_calls") or []
        content = msg.get("content") or ""
        if calls:
            print(f"{i}: toolcall ok", flush=True)
            continue
        close = f"{LT}/function{GT}"
        print(f"{i}: LEAKED  finish={ch.get('finish_reason')}  "
              f"len={len(content)}  closed={close in content}  "
              f"reasoning_len={len(msg.get('reasoning_content') or '')}")
        print("RAW >>>")
        print(content)
        print("<<< END")
        break
    else:
        print("no leak in this batch")
