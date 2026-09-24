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

## REFLECTION (iteration 11)
1. Accomplished: harness armed (unchanged); shard 3 at ~24.5/46G; everything
   downstream (A/B, quality, restore) is fully automated behind the DONE marker.
2. Working: zero-touch monitoring; the diagnosis recipe kept me from killing
   healthy curls three times.
3. Blocking: only the HF CDN throttle window (~1G/min aggregate since ~10:30).
   At this pace shard 3+4+draft complete ~11:20-11:40. No intervention helps
   (parallel range-requests would need a different tool and may trip harder
   throttling; curl -C - resume is already the resilient path).
4. No adjustment — the chain is the correct design; a slower download only
   delays, it cannot corrupt (resume + DONE gating).
5. Next: when the A/B log starts, verify phase A arm health then let it run;
   harvest at completion.

## REFLECTION (iteration 16)
1-2. Unchanged from iteration 11: harness armed, zero-touch monitoring working.
3. The CDN throttle window has persisted ~40min (~0.9G/min); shard 3 at 28.7/46G.
   ~31G remain across shard3+4+draft -> ETA ~12:00 at current pace, sooner if
   the throttle lifts (earlier windows alternated 74MB/s bursts with pauses).
4. No adjustment. Considered: parallel range downloads (aria2-style) - rejected
   (new tool on the box, worse throttle risk, curl -C - already resilient).
5. Next: same - watch for the A/B log, verify phase-A arm, harvest.
