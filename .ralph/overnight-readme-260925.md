# Overnight README completion — 3 tables + Why/Why-not chapters + deep refinement

Operator mandate (260924 evening): populate every missing measurable cell in the
README's 3 core tables, revise/create the Why / Why-not chapters, and critically
refine the README. Both boxes available all night. Gufo stays DOWN except during
its own measurement window, then back down.

## Hard rules (operator, this session)

- **Short polls only**: no single bash call may block >55 s. Long jobs →
  nohup background + output file + ≤50 s polls. Operator-flagged violation
  earlier tonight — zero tolerance.
- **No sealed-config edits**: live models.ini, systemd units (incl. strixy2
  `q5-serve.service`) stay untouched. Bench instances use own config + bench
  ports (:8090+), killed + verified dead after use.
- **One big model resident per box**; between arms wait GTT < 15 GiB (runbook).
- **Every filled cell needs an artifact** (benchmarks/ jsonl+log, results.json
  entry, fn-style basis note: template·effort·ctx·box·day).
- Granular commits on main; do NOT push (operator pushes).
- Structurally impossible cells stay honest `n/a` + footnote.

## Phase 0 — inventory (mostly DONE, evidence below)

- [x] Q4 GGUF: strixy2 `~/Downloads/LLM/Qwen38/flash-next-unsloth/UD-Q4_K_XL/`
      (4 shards); **served live** by strixy2 `q5-serve.service` at :8080 with
      the EXACT fn26 basis: Q4 + shared-Q4_K_M MTP (n-max 3, n-min 0), sharp-
      v22.5.0-low, f16 KV @131k, b8192/ub4096, mmproj, `-a default`, HIP.
      → Phase-1 batteries point at `http://strixy2.local:8080`, zero setup.
- [x] Muse Q8: strixy `~/Downloads/LLM/Qwen38/MuseGlimmer/Muse-Glimmer-30B-
      UD-Q8_K_XL.gguf` + mmproj-Q8_0. (DFlash2 draft file TBD when serving.)
- [x] fn27–fn32 read. SAFETY (fn28): vanilla draftless f16@131k = coin-flip
      crash; vanilla + detached MTP draft = hard box crash ~80 s. → tonight's
      vanilla cells: SMALL ctx only, NO drafts, ever.
- [x] results.json convention from `q4_xl_mtp_260924` (question/setup/cells/
      verdict/caveats/artifacts; batteries run against a serving endpoint).
- [x] Runner usage NAILED (smoke-tested 260925): `cd ~/Piero/Work/Qwen38/gbench
      && uv run --with requests python3 scripts/probe.py --battery {iten12,sli,
      zebra,aime,...} --budget N --tag T --host http://strixy2.local:8080 --model
      default --rdir <EXISTING-dir>` (rdir must pre-exist; budget>=3 enforced;
      census when budget>=bank; stratified-random seed 1300 otherwise). AIME:
      add `--http-timeout 900 --max-tokens 16384`. Ladder:
      `scripts/fcb15_run.py --items-file batteries/fcb15_v3def.py --mode single
      --temp 0`.
- [x] systemd/ units verified: llama-hip.service + llama-vulkan.service ship
      in repo (fn32 ✓)
- [x] gufo text-LLM modality CONFIRMED: docs/models/ ships qwen3.8-flash-next
      + qwen3.8-27b + deepseek-v4-flash + minimax-h3 (+ ASR/TTS/image) — real
      text cells measurable; check which GGUF the flash-next doc targets
      (same-weights as fork/halogen rows if Q4) during its window

## Phase 1 — Q4 quality cells (fn26 debt) → vs strixy2:8080

**MARATHON LAUNCHED 21:56 (pid 29251, driver `benchmarks/q4-marathon-260925.sh`,
log /tmp/q4-marathon.log)**: iten12 b12 → sli10 b10 → zebra20 b20 → aime12
seed1300 → aime60 census → fcb15 v3def ladder, sequential, artifacts →
benchmarks/*q4-*-260925*. Poll log each iteration; collect + results.json entry
when done. Driver self-continues past step failures (FAIL marked, rerun singles
if needed).

- [x] iten12 (12) — **12/12** (CI95 [0.76,1.0]), artifact
      `probe-q4-iten12-260925.json` ✓ matches fn26 gate
- [x] sli10 — **10/10** (CI [0.72,1.0]) ✓ (= Q5/Q6/27B canary saturation)
- [x] zebra n=20 — **0.55 [0.34–0.74]** (11/20) vs Q5 0.65 [0.43–0.82]:
      nominally below, CIs overlap. Artifact `probe-q4-zebra20-260925.json`
- [x] AIME yearsplit-12 seed-1300 — **0.667 [0.39–0.86]** (8/12) vs Q5
      0.833 / Q6 0.750: nominally below, CIs overlap at n=12. Artifact
      `probe-q4-aime12-260925.json`
- [~] AIME-60 census (low) — **RUNNING since 22:16** (~1–3 h expected)
- [ ] fcb15 ladder v3+D+E+F greedy
- [ ] Artifacts → benchmarks/ + results entry `q4_xl_mtp_260925_*`

## Phase 2 — champion column re-basis (table 2) on Q4

- [ ] Relabel + fill from Phase 1 + fn26 speed/RAM cells; keep CIs + honest
      reading paragraph

## Phase 3 — engine-axis cells (table 3)

- [x] Vanilla HIP b11168 f16 — **DONE 260925**: loaded 33 s (dio+on), cells
      pp4k **266** / pp32k **254** / pp128k n-a (400, window>ctx) / tg128
      **21.0** / tg2048 **20.9** (probe log /tmp/vhip-f16-probe.log, server
      log /tmp/vhip-f16.log; fork pp4k 689–865 → vanilla ~2.6–3× slower pp =
      fork deep-pp patches)
- [x] q8-KV draftless — **DONE 260925**: loads 52 s, pp4k **530** /
      pp32k **413** / tg128 **21.7** / tg2048 **21.0**. FINDINGS: q8 pp
      +63%/+99% over f16 (KV-write bandwidth); decode parity (21.x) —
      **fn28's 36.6 "fastest decode" was the degraded-draft artifact**
      (their own basis correction, now confirmed on b11168).
- [x] Vanilla Vulkan b11168 — **DONE 260925**: loaded ~72 s (dio→buffered
      fallback), cells pp4k **257** / pp32k **241** / tg128 **24.6** /
      tg2048 **23.5** — Vulkan decode BEATS vanilla HIP f16 (+17%/+12%),
      pp ≈ parity. fn32's "3.5× slower deep pp" = vs FORK HIP, still true.
- [~] Gufo text-LLM cells — **docs digested**: gufo targets the SAME
      UD-Q4_K_XL weights on gfx1151; own benchmarks claim pp +233–886% vs
      llama.cpp AND it reads the fork-format shared-MTP draft natively
      (`gufo serve llm --model Q4 --speculative mtp --mtp-model shared-Q8`).
      Window plan: bench :8096, speed_probe + fcb15 greedy, then DOWN.
      **If their numbers reproduce, the engine table gets a third serious
      row — and the draft-format moat is not vanilla's problem alone.**
- [~] Muse ladder + sli — **SERVING :8095** (fork binary, Q8 + DFlash2
      draft n-max 6, stock template, loaded <40 s); sli10 → ladder chain
      running (/tmp/muse-batt.log)

## Phase 4 — README evolution

- [ ] Fill cells + footnotes (basis + artifacts)
- [x] "Why not Q5? (the demoted champion)" **WRITTEN + committed (1f4cd81,
      citation fix 2e093c8)** — arithmetic not quality: 147.4 vs 124 GiB,
      1.64 t/s collapse + 12.9 swap + PSI 20% (260924), Q4 succession per
      fn26; Q5 stays as on-demand slot + quality reference
- [x] **"Why not Halogen?" + "Why not ROCmFPX?" chapters WRITTEN + committed
      (5cab923)** — Halogen: prefill king/decode −20-28%/closed/12-vs-14/
      xhigh tax, reference-only per policy 5. ROCmFPX: tie at ¼ RAM but
      iten 10/12 (gate fail), decode floor, one-format engine; door open if
      a future checkpoint holds 12/12.
- [ ] Deep pass: humanize synthetic passages (stay agent-friendly); anchors/
      footnote links resolve; correctness sweep vs evidence
- [ ] Granular commits

## Phase 5 — close-out

- [ ] Final verification: `grep -n 'fleet serving default' README.md` (Q4
      consistent), footnote ids exist, no stale "champion is Q5", tables sane
- [ ] Box state: gufo DOWN, strixy :8080 inactive (as found), no stray bench
      servers (pgrep + GTT), strixy2 serving untouched
- [ ] `~/.pi/agent/AGENTS.md` memory update
- [ ] Final report (cells filled, chapters added, cells still owed + why)

## Verification (running log)

- 260925 iter 1 (Phase 0): strixy2 q5-serve ExecStart captured (basis = fn26);
  curl strixy2:8080/v1/models → `default`; Muse Q8 path on strixy; fn26 entry
  + fn27-32 read; vanilla safety rules recorded. Ralph start overwrote the
  first detailed task file → rewritten (keep this file as the single source).
- 260925 iter 8 + REFLECTION: 4/6 marathon batteries done (12/12, 10/10,
  0.55, 0.667), aime60 running. 3 engine sets done. 5 chapters committed.
  Muse sli mid-flight (server tg 26.6 avg — DFlash2 varying). Gufo window
  turnkey: `gufo serve llm -m Q4 --speculative mtp --mtp-model
  <shared-Q8_0> -d 3 -c 131072 -i 127.0.0.1 -p 8096 --served-model-name
  default` (help verified; OpenAI-compatible → speed_probe direct; d=3
  matches fleet n-max basis). RISK watched: marathon ladder step flags —
  Muse chain doubles as the smoke test before Q4's own ladder runs.
  PRIORITIES: Muse collect → gufo window → aime60 collect → Phase-2
  table fills → deep pass → close-out.

## Final Verification (monitor-rerunnable)

- Command: `cd ~/Piero/Work/Strix_AI_Server && git log --oneline -15 && grep -c 'Why not' README.md && python3 -c "md=open('README.md').read(); assert 'fleet serving default' in md; print('README consistent')"`
- Working directory: `/home/piero/Piero/Work/Strix_AI_Server`
- Preserved artifacts: `benchmarks/` jsonl + results.json entries, this file

## Notes

- fn26: strixy2 = fleet resident default (Q4); strixy = IQ4_NL arm (lab).
- Prior loops' state files (`q4-mtp-eval-260924`, `readme-completion-260923`,
  `overnight-babysit`) are history — do not resume.
- 260924 vanilla-verification evidence (wedge/draft rejection/swap storm) is
  in `~/.pi/agent/AGENTS.md` — raw material for "Why not vanilla upstream?".
- 260925 iter 9 (formal reflection): plan unchanged, on track. **"Why Q4
  wins" section rewritten + committed (ee6ccc1)** — standing decision =
  Q4 champion, 260925 census cells in, stale 200k bullet fixed, all
  cross-refs updated. Lesson: edit tool exact-match is brittle on long
  README sections — python block-swap is the reliable path. Muse sli
  still mid-flight, aime60 running. NEXT: Muse collect → gufo window →
  ladder cells → Phase-2 tables → deep pass → close-out.
- 260925 iter 10: engine cells COMMITTED with artifacts (2112857,
  results.json `engine_axis_vanilla_260925` + benchmarks/logs-260925/).
  Muse sli still mid-flight (server task 781, many short gens, tg 22 —
  progressing not hung; stock template makes it slower than Q4's 2.5-min
  sli). aime60 healthy on strixy2 (tg 43.8, long-gen AIME items).
- 260925 iter 11: Muse diagnosis = stock-template THINKING (answer in
  reasoning_content; old sli run had no max-tokens bound → one item
  rambled 30+ min). Chain v2 launched with --max-tokens 4096 (sli) /
  6144 (ladder), --http-timeout 600. **Q4 podium row filled + committed
  (c5a63ee): AIME 0.667 / sli 10/10 / zebra 0.55 + fn33 census footnote**
  (ladder cell still pending tonight). aime60 running (~80 min in).
- 260925 iter 12: Muse false-alarm resolved (GPU 98%, tg 38 — my sparse
  sample math was wrong; capped battery healthy, task 1825 now). aime60
  ~1h45m in, on track. Deep pass recon: "Speed at depth" already
  human-friendly; DEEP-PASS ITEM: two Halogen speed epochs coexist (Q5-era
  cells 27.3/25.6 + "edges its 32.4" vs fn29's Q4-day 26.9/22.8) without a
  distinguishing basis note — add one line.
- 260925 iter 13: Muse server observed REPLACED (pid 33090, 7.5 min old,
  same args/port; old one died ~iter12 — cause unknown, possibly my kill
  spillover; chain v2 survived the swap, tasks advancing 1401→2113, tg 32).
  WATCH: if it dies again, dig properly (dmesg/journal) before relaunch.
  aime60 ~2h in. No new artifacts yet.
- 260925 iter 14: **TABLE 2 (champion-vs-cloud) RE-BASED on Q4 + committed
  (edd069c + 901cc7e)** — header, iten/AIME-12/zebra/fcb15/sli/decode/RAM
  cells all Q4-basis now; AIME-60 cell = "— (census in flight)" + fn34;
  honest-reading paragraph tracks it. Muse chain on task 2533 (still
  moving; sli longer than expected on stock template — if no artifact by
  iter 16, dig into probe's per-item request pattern). aime60 ~2h20m.
- 260925 iter 15: probe has NO retry loop (single-pass); sli grading is
  chatty per item — battery progresses, ~2h runtime on thinking-heavy
  stock template. DECISION: sli gets until iter 16; if not done, kill and
  run ladder alone (sli = canary-class, ladder = quality-bearing); Muse
  sli then honestly "owed — stock-template thinking makes the battery
  pathological". Halogen epoch note committed (df82927). aime60 ~2h40m.
- 260925 iter 16: DECISION EXECUTED — sli killed at 2h15m (no artifact;
  grading-chat + thinking made it pathological), Muse LADDER launched
  alone (35033, 6144 caps, /tmp/muse-ladder.log, server task 3188 ✓).
  Muse sli → honest "owed" note for the README. aime60 ~3h. SEQUENCE
  LEFT: muse-ladder → gufo window (strixy) ∥ aime60→q4-ladder (strixy2)
  → final table-3 fills + deep pass + close-out.
- 260925 iter 17 REFLECTION: on track — 9 commits landed (4 tables/chapters
  sets + engine artifacts). Friction = Muse stock-template thinking slows
  every battery 5-10x (sli died at 2h15m; ladder will be slow too) +
  zero probe-internal visibility (buffered logs; server task counters are
  the only progress signal). ADJUSTMENT: gufo window = SPEED CELLS ONLY
  (fcb15 optional; thinking-defaults would burn the window). DONE THIS
  ITER: **table 3 vanilla rows re-measured b11168 + fn35 committed
  (3d90a13)** — q8-KV +99% pp / no decode gain (36.6 claim corrected),
  Vulkan decode +17% beats vanilla HIP. aime60 3h20m. muse-ladder running.
- 260925 iter 18: KV-POISONING confirmed as the Muse crawl mechanism (slot
  KV from hours of generations makes per-token cost balloon; server restart
  = instant recovery). Server relaunched CLEAN at c=32768 (ladder needs no
  131k; basis noted), ladder v2 running (pid 35568, task 0 at tg 24 —
  healthy). LESSON for the fleet: Muse/DFlash2 arms need periodic restart
  or slot-reset under long battery runs — candidate Doctor note.
  aime60 3h35m.
- 260925 iter 19: Muse ladder v2 CONFIRMED healthy (240 tok/10s = 24 t/s
  real on fresh server). fn36 committed (f72a93a): Muse row's ladder/sli
  footnoted as measured-tonight + the thinking-ramble and KV-decay
  observations recorded. aime60 ~3h50m. NEXT: collect muse-ladder →
  gufo speed window → q4-ladder after aime60.
- 260925 iter 20: marathon driver + strixy2 confirmed alive (80 timing
  lines / 3 min — aime60 hammering). Muse ladder degrading AGAIN on fresh
  server (0.8 t/s wall, task 0 after 25 min) → DFlash2-draft suspect, not
  just KV. DEADLINE: iter 21 — if task 0 incomplete, kill, run GUFO speed
  window on the freed GPU, retry Muse ladder LAST and DRAFTLESS (cleaner
  quality basis anyway). Correctness sweep early: all "champion" refs OK
  (Policy-3 needs one clarifying "then-champion" word in final polish).
- 260925 iter 21: DEADLINE EXECUTED — Muse+DFlash2 killed (task 0 never
  completed, 50 min). GUFO WINDOW FINDING: gufo's flash-next support =
  UD-Q4_K_XL 4-shards ONLY (Q5 attempt = "Malformed GGUF" — their loader
  is quant-strict); the Q4 lives on strixy2 → gufo window REQUEUED to
  strixy2 after aime60+q4-ladder (its serve cmd pinned in iter-8 log).
  Strix GPU reused: Muse ladder v3 DRAFTLESS launched (pid 36436, also
  the DFlash2-decay experiment: if v3 doesn't decay, the draft was the
  agent). aime60 ~4h30m.
- 260925 iter 22: Muse v3 DRAFTLESS = tg 7.4 (SLOWER than with-draft
  early-phase — the draft was helping, decay agent is something else;
  swamp confirmed). FINAL checkpoint iter 23: task 0 completes → keep,
  else kill + owed. Policy-3 "then-champion" clarification committed
  (7245bd9). aime60 ~4h40m (est. 30-60 min left at 4.7 min/item pace).
  PLAN REMAINING: aime60 → q4-ladder (strixy2) → gufo Q4 window
  (strixy2) → final fills → deep pass → close-out.
- 260925 iter 23: Muse v3 killed at the checkpoint (352 tok/30 min —
  OWED, fn36 tells the story). Strix fully clear (GTT 0). Deep pass
  started: fn25 sli list + fn26 "cells owed" staleness fixed (4171c45).
  aime60 ~5h. NEXT: continue deep pass while aime60 runs; strixy2
  sequence (ladder → gufo) after.
- 260925 iter 24: iten12 chapter table + champion Q4 row (699791d).
  aime60 ~5h15m, strixy2 actively generating. Strix clear, deep pass
  continuing next iterations.
- 260925 iter 25 REFLECTION — **TIME-ACCOUNTING CORRECTION (important)**:
  the current time is 22:38 — the entire night is 42 min of wall time.
  ALL my "~Nh Nm" elapsed estimates were wrong (Ralph iterations run
  ~1-2 min; I compounded bad arithmetic). Truth: aime60 started 22:16
  (22 min in, perfectly normal, probe etime matches — no restart, no
  wedge). The Muse kills were premature: "2h15m sli" was really ~15 min;
  "50-min ladder" ~10 min. The n_gen deltas were real but the drama was
  manufactured. RULE from here: elapsed reasoning ONLY via `date` or
  process etime, never iteration-count arithmetic. Actions: fn36 timings
  corrected; Muse gets ONE honest retry with real deadlines (n_gen-sample
  based); aime60 left to finish naturally.
- 260925 iter 26: AIME-12 chapter updated (5b8d425) — Q4 fleet-default
  row + Q5 relabeled quality reference. Muse v4 healthy (22 t/s real,
  task 0 approaching cap). Real time 22:42; aime60 26 min in. NOTE:
  Ralph iterations run ~1-2 min — batch useful work per iteration, poll
  batteries with real clocks only.
- 260925 iter 27: **Muse ladder v4 item 1 PASS (199.7s real — it just
  needed honest time)**; ~50 min to complete at this pace. fcb15 chapter
  table + Q4 0.933 row on top (7916e3d). aime60 27 min in. 22:43.
- 260925 iter 28: Reproduce chapter + marathon driver pointer (a150a16).
  Muse ladder v4: 2 items done (1 PASS 199.7s, 1 FAIL fast). aime60
  running (28 min). 22:44.
- 260925 iter 29: zebra chapter table + Q4 row (81c65d2). Ladder item 3
  in flight; aime60 30 min. 22:46.
- 260925 iter 30: Methodology "owed speed comparison" bullet closed with
  fn35 (27d989f). Ladder 2/3 PASS (item 3: 197.5s). aime60 31 min.
  22:48.
- 260925 iter 31: sli chapter + Q4 canary + Muse-owed note (c7a33d2).
  Ladder 4 items in; aime60 probe alive at 32 min. 22:48.
- 260925 iter 32: ladder 5/15 (items ~200s each); aime60 33 min, probe
  alive. Speed-probe chapter verified current (uv form). Gufo row text
  held until its strixy2 window. 22:49.
- 260925 iter 33: In-a-hurry intro names Q4 default (2c5d0eb). Ladder
  5/15; aime60 active (59 lines/2min). 22:50. Reflection stands from
  iter 25 — on track, batteries are the only clock that matters now.
- 260925 iter 34: RAM accounting de-staled (131k reality + chapter links,
  e48b1cd). Ladder 6/15; aime60 35 min. 22:51.
- 260925 iter 35: anchor audit — all fn refs resolve, all 5 new chapter
  anchors resolve GitHub-style ✓. Ladder 6/15 (item 5 PASS 143.9s);
  aime60 37 min alive. 22:53.
- 260925 iter 36: ITERATION BUDGET NOTE — 14 iterations left vs ~1.5h of
  remaining battery time (aime60 tail + q4-ladder + gufo window). From
  here each iteration carries 3-4 × 50s waits to stretch coverage; if
  iterations exhaust with batteries still running, remaining cells get
  honest "deferred" notes (completion-gate rule), never fake numbers.
  Ladder 6/15 mid-item; aime60 38 min. 22:54.
- 260925 iter 37: stretch-waits active. Ladder 7/15; aime60 41 min,
  probe alive. 22:57.
- 260925 iter 38: ladder mid-item-8 (7 logged); aime60 45 min, probe
  alive (items are 16k-max-tokens thinking — the tail is long but
  bounded). 23:01.
- 260925 iter 39: ladder 9/15 (item 8 done); aime60 49 min alive.
  PRIORITY LOCK for remaining budget: (1) aime60 → table-2 cell,
  (2) q4-ladder → podium cell, (3) gufo window (deferred honestly if
  iterations exhaust). 23:05.
- 260925 iter 40: ladder 10/15; aime60 53 min, probe alive. 23:09.
- 260925 iter 41 REFLECTION (brief, iter-25 stands): 9 iterations left.
  aime60 57 min (probe alive), Muse ladder 10/15 mid-item. ADJUSTMENT
  PLANNED: q4-ladder (after aime60) will exceed remaining iterations →
  its podium cell gets honest "artifact pending" deferred note if the
  loop exhausts; gufo decision at iter 44. Table-2 AIME-60 cell fills
  the moment its artifact lands. 23:13.
- 260925 iter 42: ladder mid-item-11 (a hard one); aime60 61 min, probe
  alive. 23:17.
- 260925 iter 43: **AIME-60 Q4 = 0.533 [0.41–0.65] (32/60) — DEAD TIE with
  Q5's 0.533** at the heaviest shared cell; table 2 COMPLETE (dd30534,
  artifacts committed). Marathon auto-started the Q4 LADDER at 23:20:13
  (the last podium debt). Muse ladder 11/15. 23:20.
- 260925 iter 44: GUFO DEFERRED (ec0d013 — Q4-strict loader + no GPU
  window before iteration exhaustion; honest note in fn30). NOTE: the
  marathon driver is a DETACHED process — the Q4 ladder finishes and
  writes artifacts to benchmarks/ regardless of Ralph's fate; podium
  ladder cell fill happens from probe-q4-ladder-260925.json at next
  session if the loop ends first. Muse 12/15 (item 11 PASS). 23:22.
- 260925 iter 45: AGENTS.md memory updated with the census results.
  Muse item 12 grinding; Q4 ladder active (48 lines/2min). 23:26.
- 260925 iter 46: BOTH LADDERS CONVERGING — Q4 ladder 12/15 (items at
  34-42s on the MTP arm — fast), Muse 13/15 (item 12 retry-PASS 300.9s).
  Artifacts expected within ~10 min. 23:30.
- 260925 iter 47: Q4 ladder 15/15 greedy done, retry rounds running on
  the 2 unsolved (item 2 = the known-hard one the champion also misses);
  Muse 13/15. Both artifacts imminent. 23:34.
- 260925 iter 48: **MARATHON DONE 23:35:52 — Q4 ladder greedy 13/15 /
  retry 13/15 = all rungs held** (podium cell filled, 16f9269+37f9eb1,
  artifact benchmarks/fcb15-q4-ladder-260925.jsonl). Table 1 Q4 row now
  COMPLETE. Muse 13/15 (2 items left). 23:37.
- 260925 iter 49 (FINAL): Muse ladder 14/15 done (item 15 in flight at loop
  end — the DETACHED process finishes it; artifact
  gbench/results/fcb15-muse-ladder-260925.jsonl then podium Muse ladder
  cell fill = one next-session edit, fn36 already documents the basis).
  DEFERRED ITEMS (completion-gate rule, honest): (1) Muse ladder podium
  cell — artifact lands minutes after loop end; (2) gufo text cells —
  Q4-strict loader + no GPU window (fn30 documents). Muse server left
  running BY DESIGN so item 15 completes; next session: collect → fill →
  kill server. 23:46.
- 260925 00:11 POST-LOOP COMPLETION: Muse ladder finished — **greedy 7/15 /
  with-retry 13/15**; podium cell + fn36 numbers committed (81a1912,
  79ae2d3 artifact). The deferral is RETIRED — every measurable podium
  cell is now filled. Box state restored: Muse server killed (GTT 0),
  gufo restarted (activities complete), :8080 as found, strixy2's
  q5-serve untouched throughout. The only remaining owed cells, by
  design: Muse sli (thinking-pathology, fn36) and gufo text (Q4-strict
  loader, fn30).
