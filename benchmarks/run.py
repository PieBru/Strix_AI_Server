#!/usr/bin/env python3
"""run.py — reproduce our quality-battery scores against an OpenAI-compatible
endpoint (llama-server, vLLM, or any /v1/chat/completions API).

Usage:
  python3 run.py --battery iten12 --model qwen38-flash-q5 \
      [--host http://127.0.0.1:8080] [--temp 0.0] [--out results.jsonl]

  python3 run.py --battery aime --model qwen38-flash-q5   # 12 items,
      # stratified-random seed 1300 — the exact selection our published
      # AIME cells used (item indices 0,1,7,18,22,23,24,25,35,36,42,49)

Protocol (matches our scored cells):
  - temp 0.0 (greedy) by default; our published cells ran greedy
  - max_tokens 6000 (thinking models need the room)
  - the LAST ```python block in the reply is the answer (models emit
    sketches first; the final block is the committed answer)
  - grading: the battery's embedded check() executes the block and
    asserts on its stdout — deterministic, no LLM judge
  - SECURITY: the model's code runs in-process with full privileges
    (filesystem, network, subprocess — the 60 s alarm is best-effort
    and can be cancelled by the graded code). Only run this against
    endpoints you trust, or inside a container
  - failed/timed-out queries count as NOT answered (spent, not ok)
  - 900 s HTTP timeout, 2 tries per item

Batteries are self-contained and self-checked: run them directly
(python3 batteries/iten12_items.py) to verify graders before trusting
any score — references must pass, false-friend/off-by-one probes must fail.

Output: JSONL rows (one per item) + a summary line. Score = ok/answered.
Rows are stamped with battery version + temperature; resume replays only
same-protocol rows (a grader bump re-scores, never inherits old verdicts).
"""

import argparse
import importlib.util
import json
import os
import re
import signal
import sys
import time
import urllib.request

BATTERIES = {
    "iten12": ("batteries/iten12_items.py", None),   # census: all 12 items
    "aime":   ("batteries/aime60_items.py", 12),     # seed-1300 stratified 12 of 60
}
PROMPT = (
    "Write Python code exactly as specified. Reply with ONE python "
    "code block and nothing else.\n\n{spec}"
)
GRADE_TIMEOUT = 60  # seconds; an infinite loop in model code FAILS the item


def load_battery(path):
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    spec = importlib.util.spec_from_file_location("battery", here)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def select_items(n_items, budget, seed=1300):
    """Stratified-random selection: even/odd strata sampled evenly, seeded.
    This is the exact algorithm our scored cells used (seed 1300).
    A budget >= battery size takes the census."""
    if budget is None or budget >= n_items:
        return list(range(n_items)), "census"
    import random
    rng = random.Random(seed)
    strata = [list(range(0, n_items, 2)), list(range(1, n_items, 2))]
    half = budget // 2
    sel = set(
        rng.sample(strata[0], min(half, len(strata[0])))
        + rng.sample(strata[1], min(budget - half, len(strata[1])))
    )
    rest = [i for i in range(n_items) if i not in sel]
    rng.shuffle(rest)
    while len(sel) < budget and rest:
        sel.add(rest.pop())
    return sorted(sel)[:budget], f"stratified-random (seed {seed})"


def select_yearsplit(n_items, budget=12, split_at=30, seed=1300):
    """Year-stratified: half the budget from each side of split_at (AIME 2025 | 2026),
    stratified-random within each half. Same seed discipline as select_items."""
    import random
    rng = random.Random(seed)
    older = list(range(0, min(split_at, n_items)))
    newer = list(range(min(split_at, n_items), n_items))
    half = budget // 2
    sel = (rng.sample(older, min(half, len(older)))
           + rng.sample(newer, min(budget - half, len(newer))))
    rest = [i for i in range(n_items) if i not in sel]
    rng.shuffle(rest)
    while len(sel) < budget and rest:
        sel.append(rest.pop())
    return sorted(sel)[:budget], f"year-stratified (split@{split_at}, seed {seed})"


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text or "", re.S)
    return m[-1] if m else (text or "")  # LAST block = committed answer


def grade(harness, code):
    """Returns True (pass), False (wrong answer = AssertionError), or None
    (grader error — timeouts, crashes; NOT scored as a wrong answer)."""
    ns = {}

    def _timeout(signum, frame):
        raise TimeoutError("grade timeout")

    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(GRADE_TIMEOUT)
    try:
        exec(harness, ns)
        ns["check"](code)
        return True
    except AssertionError:
        return False
    except Exception:
        return None  # grader error: spent, not answered — never a FAIL
    finally:
        signal.alarm(0)


def one(idx, items, model, host, temp, max_tokens, tries=2, http_timeout=900):
    spec_text, harness = items[idx]
    last_exc = None
    for _ in range(tries):
        try:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": PROMPT.format(spec=spec_text)}],
                "max_tokens": max_tokens,
                "temperature": temp,
            }
            req = urllib.request.Request(
                host.rstrip("/") + "/v1/chat/completions",
                json.dumps(payload).encode(),
                {"Content-Type": "application/json"},
            )
            t0 = time.time()
            r = json.load(urllib.request.urlopen(req, timeout=http_timeout))
            dt = time.time() - t0
            reply = r["choices"][0]["message"].get("content") or ""
            code = extract_code(reply)
            return {"ok": grade(harness, code), "wall": round(dt, 1),
                    "tail": reply[-120:]}
        except Exception as e:
            last_exc = e
            time.sleep(2)
    return {"ok": None, "error": str(last_exc)}  # spent, not answered


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--battery", choices=sorted(BATTERIES), required=True)
    ap.add_argument("--model", required=True, help="model id or alias at the endpoint")
    ap.add_argument("--host", default="http://127.0.0.1:8080")
    ap.add_argument("--temp", type=float, default=0.0,
                    help="sampling temperature (our cells: 0.0 greedy)")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--budget", type=int, default=None,
                    help="items to run (iten12: all; aime: 12)")
    ap.add_argument("--selection", choices=["stratified", "yearsplit"], default="stratified",
                    help="aime subset rule: even/odd strata (published cells) or year-stratified 2025|2026")
    ap.add_argument("--seed", type=int, default=1300)
    ap.add_argument("--out", default=None, help="JSONL output path (resume-safe)")
    args = ap.parse_args()

    path, default_budget = BATTERIES[args.battery]
    bat = load_battery(path)
    bver = f"{args.battery}/{getattr(bat, 'BATTERY_VERSION', '?')}"
    items = bat.ITEMS
    budget = args.budget if args.budget is not None else default_budget
    order, mode = (select_yearsplit(len(items), budget, seed=args.seed)
                   if args.battery == "aime" and args.selection == "yearsplit"
                   else select_items(len(items), budget, args.seed))
    print(f"battery={args.battery} ({getattr(bat, 'BATTERY_VERSION', '?')}) "
          f"items={len(order)} selection={mode} temp={args.temp} model={args.model}")

    done = {}
    out_path = args.out or f"{args.battery}-{args.model}.jsonl"
    if os.path.exists(out_path):  # resume: skip completed items
        for line in open(out_path):
            if line.strip():
                row = json.loads(line)
                if (row.get("ok") is not None and row.get("model") == args.model
                        and row.get("bat") == bver and row.get("temp") == args.temp):
                    done[row["item"]] = row
        print(f"resuming: {len(done)} items already scored")

    with open(out_path, "a") as out:
        for i in order:
            if i in done:
                continue
            r = one(i, items, args.model, args.host, args.temp, args.max_tokens)
            row = {"model": args.model, "item": i, "bat": bver, "temp": args.temp,
                   **r, "ts": time.strftime("%Y-%m-%d")}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"  item {i:2d}: {'OK' if r.get('ok') else 'FAIL' if r.get('ok') is False else 'ERROR'}"
                  + (f"  ({r['wall']}s)" if "wall" in r else ""))

    rows = [json.loads(l) for l in open(out_path) if l.strip()]
    mine = {r["item"]: r for r in rows if r["model"] == args.model
            and r.get("bat") == bver and r.get("temp") == args.temp and r["item"] in order}
    answered = [r for r in mine.values() if r.get("ok") is not None]
    ok = sum(1 for r in answered if r["ok"])
    n = len(answered)
    print(f"SCORE: {ok}/{n}" + (f" = {ok/n:.3f}" if n else " (no items answered)"))
    if len(answered) < len(order):
        print(f"NOTE: {len(order) - len(answered)} item(s) errored (spent, not answered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
