#!/usr/bin/env python3
"""Attribute champion latency spikes: queue wait vs decode speed.

  scripts/stall-audit.py [host] [minutes]        (default 192.168.50.184, 60)

Reads the gufo access log off the serving box and splits every completed request
into the three things a client actually feels:

  queue_ms  waiting for the engine to admit us
  ttft_ms   time to first token (prefill of our own prompt)
  decode    tokens/s once we are running

Why: a "the model got slow" report is usually NOT the model. Measured 260929, the
champion serves `plan=serial-c1 batch_width=1` with ONE kv snapshot, so a request
whose prompt does not match the last snapshot re-prefills from scratch (~1000 t/s,
so 75k tokens = ~80 s) and every other client waits in queue for all of it while
its own decode stays at a healthy ~40 t/s. Two clients with different prompt shapes
therefore evict each other's snapshot and both pay the other's prefill.
"""
import json
import re
import subprocess
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.184"
MINUTES = int(sys.argv[2]) if len(sys.argv) > 2 else 60

FIELDS = ("duration_ms", "queue_ms", "ttft_ms", "decode_tps", "prompt_tokens",
          "generated_tokens", "cache", "cache_miss_reason", "common_prefix_tokens")

REMOTE = (f"journalctl --user -u gufo-llm --no-pager --since '-{MINUTES} min' "
          "2>/dev/null | grep 'event=completed' | grep chat/completions")


def rows():
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, REMOTE],
                         capture_output=True, text=True, timeout=90).stdout
    for line in out.splitlines():
        r = {}
        for f in FIELDS:
            m = re.search(rf"\b{f}=([^\s]+)", line)
            if m:
                r[f] = m.group(1)
        if "duration_ms" in r:
            r["status"] = re.search(r"status=(\d+)", line).group(1)
            yield r


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def main():
    rs = [r for r in rows() if r.get("status") == "200"]
    if not rs:
        print("no completed chat requests in window")
        return 1

    print(f"{HOST} last {MINUTES} min — {len(rs)} completed chat requests\n")
    print(f"{'prompt':>8} {'gen':>5} {'dur':>8} {'queue':>8} {'ttft':>8} {'dec t/s':>8}  cache")
    for r in rs:
        print(f"{f(r.get('prompt_tokens')):>8.0f} {f(r.get('generated_tokens')):>5.0f} "
              f"{f(r.get('duration_ms'))/1000:>7.1f}s {f(r.get('queue_ms'))/1000:>7.1f}s "
              f"{f(r.get('ttft_ms'))/1000:>7.1f}s {f(r.get('decode_tps')):>8.1f}  "
              f"{r.get('cache', '-')}/{r.get('cache_miss_reason', '-')}"
              + (f" common={r['common_prefix_tokens']}" if "common_prefix_tokens" in r else ""))

    slow = [r for r in rs if f(r["duration_ms"]) > 20000]
    print(f"\n>20s: {len(slow)}/{len(rs)}")
    if not slow:
        return 0
    q = [r for r in slow if f(r.get("queue_ms")) > f(r.get("ttft_ms"))]
    p = [r for r in slow if f(r.get("queue_ms")) <= f(r.get("ttft_ms"))]
    dec = [r for r in slow if f(r.get("decode_tps")) and f(r.get("decode_tps")) < 20]
    print(f"  blocked in queue : {len(q)}   (someone else's prefill — engine scheduling)")
    print(f"  own prefill      : {len(p)}   (snapshot miss: {sorted({r.get('cache_miss_reason', '-') for r in p})})")
    print(f"  decode under 20t/s: {len(dec)}   (the model itself — the only bucket that is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
