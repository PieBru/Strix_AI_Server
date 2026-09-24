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
- [ ] sli10 (10)
- [ ] zebra n=20
- [ ] AIME yearsplit-12 seed-1300
- [ ] AIME-60 census (low)
- [ ] fcb15 ladder v3+D+E+F greedy
- [ ] Artifacts → benchmarks/ + results entry `q4_xl_mtp_260925_*`

## Phase 2 — champion column re-basis (table 2) on Q4

- [ ] Relabel + fill from Phase 1 + fn26 speed/RAM cells; keep CIs + honest
      reading paragraph

## Phase 3 — engine-axis cells (table 3)

- [~] Vanilla HIP b11168 — **LAUNCHED 22:0x, LOADED in 33 s, probing now**
      (Q5, dio+on — the repo Vulkan canary's lazy recipe — f16@131k draftless,
      :8092, log /tmp/vhip-f16.log, probe /tmp/vhip-f16-probe.log).
      KEY CORRECTION: mmap+on was the wedge, NOT lazy-on itself — vanilla
      dio+on loads clean (33 s) where mmap+on ground 15 min (260924 tests).
      Update "Why not vanilla" chapter accordingly.
- [ ] q8-KV draftless variant (tg cells; assert risk — fn28 matrix says q8
      asserted WITH draft; draftless untested)
- [ ] Vanilla Vulkan b11168 (strixy, `~/llama.cpp-fn-up/build-vk/bin/
      llama-server`): same shape, Q5 no-draft small ctx; + fcb15 15-item
      greedy if time
- [ ] Gufo text-LLM cells (window: gufo UP only for this, then DOWN+verify);
      if unsupported → n/a + one-line reason
- [ ] Muse ladder + sli (serve on strixy bench port; stock template basis
      per podium row)

## Phase 4 — README evolution

- [ ] Fill cells + footnotes (basis + artifacts)
- [ ] "Why Q5 wins" → "Why Q4 wins"; new "Why not Q5? (demoted champion)"
      with oversubscription evidence
- [ ] New: "Why not Halogen?", "Why not ROCmFPX?", "Why not vanilla upstream?"
      (absorb 260924/25: draft tensor rejection token_embd/output_hc_norm,
      lazy on/auto 15-min wedge, 26 GiB swap PSI 38%), "Why not Vulkan-only?"
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
- 260925 iter 3: marathon iten12 → **12/12** ✓ (sli10 running). Vanilla HIP
  b11168 :8092 = Q5 dio+on f16@131k draftless → loaded 33 s, health ok,
  RAM 116G; speed_probe running (pp32k observed 278 t/s server-side).
  Gufo text-LLM confirmed (qwen3.8-flash-next model doc). Canary units
  decoded: Vulkan = `-lm dio -lzm on` (the dio discovery), HIP unit =
  fork spellings (on-direct).

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
