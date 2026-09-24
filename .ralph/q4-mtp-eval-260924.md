# Flash-Q4 + MTP evaluation — monitor, measure, compare vs flash-q5, report

## Context (260924 ~10:05)
- Operator goal: serve Flash-Next at UD-Q4_K_XL (the Ollama-catalog default quant)
  as a fast alternative for simple tasks; compare vs the incumbent Q5_K_XL+MTP arm.
- Download RUNNING on strixy2: 4 shards, 111.3G →
  ~/Downloads/LLM/Qwen38/flash-next-unsloth/UD-Q4_K_XL/ (~5G/min, ETA ~10:20),
  then the 1.91G shared-Q4_K_M draft. Log: ~/fp4-27b/q4-dl.log (DONE marker).
- CHAINED: on DONE, /tmp/q4-mtp-ab.sh auto-launches (armed from strixy):
  phase A = shared-Q8_0 draft (2.79G, already on disk),
  phase B = shared-Q4_K_M draft (1.91G),
  each: fork engine :8091, f16 KV @131k, sharp-low, n-max 3, settle 90s,
  speed_probe (fresh corpus per phase) + echo_probe + acceptance lines;
  then iten12 + fcb15 census on the phase-B arm; restores q5-serve at end.
  A/B log: ~/Piero/Work/Qwen38/reruns-260919/q6-low-row/q4-mtp-ab.log
- Comparison baselines (incumbent Q5+MTP, pinned-HIGH same-day):
  pp4k ~707, tg128 ~36.4, tg2048 ~32.2 settled / 27.6 post-restart,
  echo 37.8, acceptance 0.73-0.75; quality: iten12 12/12, fcb15 census
  (see benchmarks/results.json q5 rows).

## Checklist
1. [ ] Monitor download + A/B chain each iteration; babysit rules apply
       (storm -> SIGKILL arm; failure -> inspect log, fix invocation, relaunch).
2. [ ] Harvest phase A vs B: tg128/tg2048/echo/pp4k + draft acceptance;
       pick the better draft with reasons.
3. [ ] Harvest iten12 + fcb15 for Q4; compare vs Q5 incumbent cells.
4. [ ] If Q4 wins anywhere decisively, note the serving recommendation
       (which box/port/role: simple-task alternative to CyberTiel).
5. [ ] Write the human-friendly report (README-style table + plain-language
       verdict) into benchmarks/q4-vs-q5-report-260924.md; commit + push.
6. [ ] Verify q5-serve restored + healthy at the end; report box state.

## Success criteria (binary)
- Both MTP drafts measured on the same arm+config (numbers in the log).
- Q4 quality cells exist (iten12 + fcb15) OR a logged blocker.
- Report file committed + pushed; q5-serve healthy at close.

## Rules
- Nothing in the foreground >55s; poll logs, don't tail -f.
- The A/B script self-restores q5-serve; only intervene on failure.
- pkill/pgrep patterns bracketed; no vanilla loads (rule stands).

## REFLECTION (iteration 6)
1. Accomplished: harness fully built and armed (download script with resume,
   chain-watcher, dual-draft A/B script with settle+fresh-corpus discipline,
   quality legs, self-restore); FP4-27B evaluation already banked earlier today
   as a template for this one.
2. Working: the chain pattern (DONE marker -> autostart) removes hand-off
   latency; per-phase fresh corpora avoid the cache-replay trap; short polls.
3. Friction: HF CDN is bursty (74MB/s windows alternating with minutes-long
   pauses) — three "stall" scares were all burst gaps; the diagnosis recipe
   (pgrep curl + 15s growth delta) settled each in one check.
4. No adjustment — patience + the armed chain is the right stance; killing a
   healthy curl for a perceived stall would be the error.
5. Next: shard 3 (~35G) then shard 4 (12G) then the 1.91G draft -> A/B
   autostarts -> harvest into the comparison report.
