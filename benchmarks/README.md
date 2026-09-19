# Benchmarks — the batteries behind our tables

This directory contains everything needed to reproduce our quality scores:
the batteries, the runner, and our measured results.

## What's here

| file | what |
|---|---|
| `batteries/iten12_items.py` | ITEN-12 v2: 12 Italian↔English translation items with deterministic graders (false-friend traps) |
| `batteries/aime60_items.py` | AIME-60: 60 competition-math items, each grading an exact integer answer |
| `run.py` | The runner — sends items to your endpoint, grades deterministically |
| `test_run.py` | Self-check for the runner's resume/protocol stamping (no network) |
| `../gbench/` | the GBench probe behind the README's coding (fcb15) and zebra tables — vendored minimal runner, upstream: [PieBru/Qwen38_Strix](https://github.com/PieBru/Qwen38_Strix/tree/main/gbench) |
| `results.json` | Our measured scores (the numbers in the README tables) |
| `iten12-qwen38-flash-q5-v3.jsonl` / `aime-qwen38-flash-q5-v2g.jsonl` | raw per-item evidence behind the champion's published cells — the other models' cells are results.json summaries; their raw runs are not yet curated in |

## Quick start

```bash
# 0. Verify the graders first (references pass, traps fail — 5 seconds)
python3 batteries/iten12_items.py    # expect: SELF-CHECK OK
python3 batteries/aime60_items.py    # expect: SELF-CHECK OK

# 1. Serve a model (see ../configs/ for exact recipes)

# 2. Run the quality gate (12 items, ~5–15 min on our box)
python3 run.py --battery iten12 --model qwen38-flash-q5
# expect: 12/12 under the shipped v3.1 grader (the interim v3 scored
# 11/12 — a grader bug on the clock item, fixed in v3.1)

# 3. Run the reasoning cell (12 of 60, seed-1300 — same items we scored)
python3 run.py --battery aime --model qwen38-flash-q5
# expect: ~0.83 under the fixed v2 grader (greedy; temp 1.0 widens the band ±1–2 items)
```

## How grading works (no LLM judge)

Each item's prompt tells the model to end with ONE python block that
prints its answer. The runner:

1. extracts the **last** ```python``` block (models sketch first; the
   final block is the committed answer)
2. executes it **in-process, with full privileges** (filesystem, network,
   subprocess — a 60 s alarm bounds runaway loops, best-effort only).
   Only run against endpoints you trust, or inside a container
3. runs the item's `check()` — regex/integer assertions on the printed
   output (for ITEN: load-bearing keywords AND false-friend rejections
   like *editor*≠*publisher*, *sensible*≠*sensibile*; for AIME: the
   exact gold integer)

A fluent translation that swaps a false friend **fails**. A correct
answer buried after a wrong one **fails** (last integer printed must be
the answer). Everything is deterministic — same reply, same verdict.

## Protocol notes (what "our score" means)

- **Greedy (temp 0.0)** — our published cells ran greedy; at temp 1.0
  expect ±1–2 items variance at n=12
- **Seed-1300 stratified selection** for AIME (even/odd strata sampled
  evenly) — `run.py` reproduces the exact 12-item subset; ITEN-12 runs
  the full census
- **Errored items are spent, not answered** — timeouts, HTTP failures,
  and grader crashes are recorded as ERROR and excluded from the score
  (never scored as wrong answers). Both denominators are reported in
  results.json when they differ (Q6's AIME cell: 8/11 graded, 8/12
  counting the crash as a failure)
- JSONL output is resume-safe — interrupted runs pick up where they left
  off; rows are stamped with battery version + temperature, and resume
  replays only same-protocol rows (a grader bump re-scores, never
  inherits old verdicts)
- Speed-at-depth numbers (pp/tg in the README) are a separate
  wall-clock probe: real-text prompts sized to 4k/32k/128k, timed
  from request-sent to response-complete. Same principle — filled
  prompts, wall-clock, no server-reported metrics.

## Honest limitations

- n=12 batteries are **floor checks, not rankings** — a one-item gap is
  sampling noise (Fisher's exact p ≈ 0.49 for 12/12 vs 10/12)
- The battery measures translation fidelity and competition math — not
  coding ability or long-context retrieval (those are planned)
- A model scoring 12/12 has met our floor; ranking within the passing
  tier is by speed/RAM/context, not by this battery
