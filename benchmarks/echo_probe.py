#!/usr/bin/env python3
"""Echo-probe: measures t/s on an echo-heavy rewrite task (ngram-mod's home turf).
Usage: echo_probe.py HOST MODEL LABEL"""
import json, sys, time, urllib.request

host, model, label = sys.argv[1], sys.argv[2], sys.argv[3]
block = '''
def process_items_{i}(items, threshold):
    """Filter and transform item list {i}."""
    result = []
    for idx, item in enumerate(items):
        if item.score > threshold:
            scaled = item.score * {i}.5
            result.append({{"id": item.id, "pos": idx, "scaled": scaled}})
        elif item.score < 0:
            result.append({{"id": item.id, "pos": idx, "scaled": 0.0}})
    return sorted(result, key=lambda r: r["scaled"], reverse=True)
'''
code = "\n".join(block.format(i=i) for i in range(60))  # ~2.5k tokens
prompt = f"Reproduce the following code EXACTLY, changing only the function name suffix 'items' to 'records' everywhere. Output only the code, nothing else.\n\n{code}"
req = urllib.request.Request(
    f"http://{host}/v1/chat/completions",
    data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                     "max_tokens": 4000, "temperature": 0}).encode(),
    headers={"Content-Type": "application/json"})
t0 = time.time()
r = json.load(urllib.request.urlopen(req, timeout=600))
dt = time.time() - t0
u = r["usage"]
print(f"{label}: {u['completion_tokens']} tokens in {dt:.1f}s (prompt {u['prompt_tokens']}) -> {u['completion_tokens']/dt:.1f} t/s")
