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

## REFLECTION (iteration 21)
Steady-state: shard 3 at 33.2/46G (~0.9G/min through the throttle window,
consistent since ~10:30). ~26G total remain -> ETA ~12:15 worst case. The
chain design means the only remaining work after DONE is verification and
harvest; nothing to adjust. Priorities unchanged.

## REFLECTION (iteration 26)
Download 35.5/46G on shard 3; total elapsed ~75 min against the ~20 min
optimistic ETA — the throttle window is the whole story, still ~0.5-0.9G/min.
Everything else remains armed and correct. No adjustment; harvest on DONE.

## ITERATION 29 — download closed, A/B recovered and RUNNING (260924 10:5x)

**Download verified complete (10:31) against the HF API, byte-exact:**
| shard | HF size | on disk |
|---|---|---|
| 00001 | 10,946,624 | ✓ |
| 00002 | 49,859,583,136 | ✓ |
| 00003 | 49,376,141,504 | ✓ |
| 00004 | 12,087,983,520 | ✓ |
(shard 1 is *legitimately* 10.9 MB — not a truncation; the repo splits it that way.)

**BUG FOUND (silent, my own):** the draft fetch in `/tmp/q4-dl.sh` wrote to
`$D/flash-next/...` where `$D=.../flash-next-unsloth` — a directory that does
not exist → `curl` exited 23 in the *same second* the last shard finished.
Because the line was `curl ... && echo ok`, a failure left no log line, and
`echo DONE` ran unconditionally — so the download log looked like a clean
success while the 1.91G draft was absent. The chained A/B therefore never had
its phase-B file (and no watcher was alive to fire).

**Fix + recovery:** `/tmp/q4-run-chain.sh` — fetch the draft to the correct
dir (`~/Downloads/LLM/Qwen38/flash-next/`), assert size == 1,907,151,936, only
then exec the A/B. Ran: fetched in 25 s (78 MB/s burst), size verified, A/B
autostarted 10:48:34.

**Live state:** phase A (shared-Q8_0 draft) arm healthy on `strixy2:8091`
(`{"status":"ok"}`); q5-serve stopped by design, restored by the script at end.
Log: `~/Piero/Work/Qwen38/reruns-260919/q6-low-row/q4-mtp-ab.log`
Chain stdout: `/tmp/q4-chain.log`.

**Lesson (durable):** `cmd && echo ok` plus an unconditional completion marker
converts a hard failure into a green log. Completion markers must be emitted
only on the success path, and downloads must assert the expected byte size.

## ITERATION 29b — OPERATOR RULE + local swap-storm fix (decision B) — DONE & VERIFIED

**New standing operator rule (260924, applies to EVERY inference experiment):**
while looping on inference work, monitor RAM **<100%**, swap **<0.5 GiB**, and
traffic (no refault/swap storms). A resident arm must leave >=8 GiB host headroom.

**Local `strixy-9ad3` storm — root cause (OBSERVED 10:50):** the resident
`qwen38-flash-q5` arm is **147.4 GiB of GGUF on a 124 GiB box** (`MemoryMax=120G`,
f16 KV @131k). At 116 GiB GTT the rest faulted from disk → 3% GPU busy, **1.64 t/s**,
RAM 122/124 GiB, **12.9 GiB swap**, PSI-full ~20%. The models.ini comment trail
(262144→200000→131072) is the same failure bought back three times: the arm was
oversubscribed from the start.

**Fix applied (operator chose B — reload with a fitting working set):**
- new default arm `[qwen38-flash-iq4nl]` = local `flash-next-iq4nl` IQ4_NL,
  **93.3 GiB** (54 GiB smaller), same qwen4exp recipe: sharp-low template, kvu,
  shared-Q8_0 MTP draft, f16 KV @131k, b=8192/ub=4096. mmproj omitted on purpose
  (documented wedge combo). Aliases `default,quality,fast`, load-on-startup true.
- `[qwen38-flash-q5]` demoted: alias `q5`, `load-on-startup = false` (on-demand
  only, warned in-file). `[qwen38-flash-q6]` unchanged (`deep`, 158 GiB, warned).
- config replaced atomically (`mv` of a fully-diffed temp file; backup
  `models.ini.bak-260924-storm`); only additive + the two q5 lines changed.
- switch script `/tmp/local-arm-switch.sh` (stop → wait GTT<15G → start → wait loaded);
  log `/tmp/local-arm-switch.log`.

**Before → after (same box, same minute):**

| metric | Q5 arm (before) | IQ4_NL arm (after) |
|---|---|---|
| decode | **1.64 t/s** | **37.9 t/s** |
| GPU busy | 3% | normal |
| RAM used | 122 / 124 GiB | 86.7 / 124 GiB (68%) |
| free/available | 2.4 GiB | 40.8 GiB |
| swap | 12.9 GiB | 520 MiB (stale, not growing; no passwordless sudo to swapoff) |
| PSI mem full (avg10) | ~20% | **0.00** |
| GTT | 116 GiB | 81.6 GiB |

Verified with a real request (`POST /v1/chat/completions`, alias `quality`): correct
answer, 41 tokens in 1056 ms = 37.9 t/s, **draft acceptance 0.60 / mean len 4.00** —
so the shared Q8_0 MTP draft works with the IQ4_NL conversion. Load time 170 s.

**strixy2 (the A/B box) stays inside the envelope:** phase A/B logged at RAM
98.7/127.4 GiB, swap 95 MiB, PSI 0.00. Monitored each polling cycle from now on.

### A/B harvest so far (same arm, same config, fresh corpus per phase)
| cell | phase A — shared-Q8_0 draft | phase B — shared-Q4_K_M draft | Q5+MTP incumbent (same-day) |
|---|---|---|---|
| pp4k | 830 t/s | **865 t/s** | 707 |
| pp32k | 888 t/s | **909 t/s** | — |
| tg128 | 32.6 t/s | **33.5 t/s** | 36.4 |
| tg2048 | 27.4 t/s | **31.7 t/s** | 32.2 settled |
| echo | 39.8 t/s | pending | 37.8 |

Phase B (Q4_K_M draft) leads phase A on every cell so far; both still trail the
Q5 incumbent on decode but beat it on prefill (~+20%).
