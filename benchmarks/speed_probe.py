#!/usr/bin/env python3
"""speed_probe — the wall-clock speed cells the podium's pp/tg columns come from.

Two kinds of cell, both measured as **wall-clock on this box**, never
server-reported numbers:

  pp (prefill)   4k / 32k / 128k-token corpus windows, each sent as one
                 request, timed request-sent -> complete, `max_tokens=1`.
                 Distinct corpus offsets so no prompt-cache replay flatters a
                 cell. Tokens come from the response's `usage.prompt_tokens`.
  tg (decode)    128 and 2048-token streamed generations, timed first
                 content delta -> last, so the number is steady-state decode
                 and excludes prompt processing. Reasoning deltas count as
                 output (a thinking model's real cost).

Comparability rules (why the podium is one table): same corpus, same
offsets, same prompt, same temperature 0, one client, one probe invocation
per row. Do not compare a pp cell from one corpus against another — the
token char ratio differs and 128k cells land at ~160k real tokens on
code-dense text.

Usage:
  uv run python3 benchmarks/speed_probe.py --model qwen38-flash-q5
  uv run python3 benchmarks/speed_probe.py --model muse-glimmer-q8 --label nm7
  uv run python3 benchmarks/speed_probe.py --pp-only --model <arm>
  uv run python3 benchmarks/speed_probe.py --selfcheck

Corpus defaults to benchmarks/corpus/speed-corpus.txt if present, otherwise
--corpus is required for pp cells. A model whose training context is below
the requested window will be refused by the server (HTTP 400) — the pp128k
cell then legitimately reads "n/a" rather than a number.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORPUS = os.path.join(HERE, "benchmarks", "corpus", "speed-corpus.txt")

TG_PROMPT = (
    "Write a detailed technical essay, at least two thousand words, on unified "
    "GPU memory architectures for large-language-model serving. Cover GTT, "
    "page-cache interactions, KV-cache sizing, and speculative decoding "
    "trade-offs. Do not stop early."
)
PP_PROMPT = "Read this material carefully.\n\n{corpus}\n\nReply with just: OK"


def _post(url, payload, timeout, stream):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def pp_cell(url, model, corpus, target, offset, label, timeout=3600):
    """One prefill cell: `target` tokens (approx 4 chars/token) from `offset`."""
    payload = {"model": model,
               "messages": [{"role": "user",
                             "content": PP_PROMPT.format(corpus=corpus[offset:offset + target * 4])}],
               "max_tokens": 1, "temperature": 0, "stream": False}
    t0 = time.time()
    try:
        body = json.load(_post(url, payload, timeout, False))
    except urllib.error.HTTPError as e:
        print(f"{label}: n/a (HTTP {e.code} — window exceeds the served context)")
        return None
    wall = time.time() - t0
    pt = body.get("usage", {}).get("prompt_tokens", 0)
    print(f"{label}: {pt} tokens in {wall:.1f}s -> {pt / wall:.0f} t/s")
    return pt / wall


def tg_cell(url, model, n, label, timeout=3600):
    """One decode cell: `n` streamed tokens, timed first delta -> last."""
    payload = {"model": model, "messages": [{"role": "user", "content": TG_PROMPT}],
               "max_tokens": n, "temperature": 0, "stream": True}
    t0 = time.time()
    first = None
    ntok = 0
    for line in _post(url, payload, timeout, True):
        if line.startswith(b"data:") and b"[DONE]" not in line:
            chunk = json.loads(line[5:])
            choices = chunk.get("choices", [{}])
            delta = choices[0].get("delta", {}) if choices else {}
            if delta.get("content") or delta.get("reasoning_content"):
                if first is None:
                    first = time.time()
                ntok += 1
            usage = chunk.get("usage", {}).get("completion_tokens")
            if usage:
                ntok = usage
    last = time.time()
    if first is None:
        print(f"{label}: no content deltas arrived — endpoint returned usage only")
        return None
    span = last - first
    print(f"{label}: {ntok} tokens, first {first - t0:.1f}s, span {span:.1f}s -> {ntok / span:.1f} t/s")
    return ntok / span


def selfcheck():
    """Offline: the two cell parsers against a stubbed transport."""
    import io
    import unittest.mock as mock

    stream = b"".join(
        [b'data: {"choices":[{"delta":{"content":"x"}}]}\n' for _ in range(4)]
        + [b'data: {"choices":[],"usage":{"completion_tokens":4}}\n', b"data: [DONE]\n"]
    )

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with mock.patch(__name__ + "._post", return_value=FakeResp(stream)):
        assert tg_cell("http://x", "m", 4, "selfcheck-tg") is not None
    with mock.patch(__name__ + "._post",
                    return_value=FakeResp(b'{"usage":{"prompt_tokens":100}}')):
        assert pp_cell("http://x", "m", "abc" * 200, 100, 0, "selfcheck-pp") is not None
    print("speed_probe selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default=None, help="the endpoint's model id/alias")
    ap.add_argument("--host", default="127.0.0.1:8080")
    ap.add_argument("--label", default="tg", help="prefix for the printed cell names")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--pp-only", action="store_true")
    ap.add_argument("--tg-only", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        selfcheck()
        return 0
    if not args.model:
        print("--model is required (ask the endpoint: GET /v1/models)", file=sys.stderr)
        return 2
    url = f"http://{args.host}/v1/chat/completions"
    if not args.tg_only:
        if not os.path.exists(args.corpus):
            print(f"--corpus not found: {args.corpus} (required for pp cells)", file=sys.stderr)
            return 2
        text = open(args.corpus, errors="replace").read()
        # labels match the podium's column names (requested window, not the
        # realised token count — a 128k request lands ~160k tokens on
        # code-dense text; the printed number is always the real one).
        for target, offset, cell in ((4100, 0, "pp4k"), (33000, 50000, "pp32k"),
                                     (131000, 250000, "pp128k")):
            pp_cell(url, args.model, text, target, offset, f"{args.label}-{cell}")
    if not args.pp_only:
        tg_cell(url, args.model, 128, f"{args.label}-tg128")
        tg_cell(url, args.model, 2048, f"{args.label}-tg2048")
    return 0


if __name__ == "__main__":
    sys.exit(main())
