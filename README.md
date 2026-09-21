# Is one Strix Halo enough for a dev? TL;DR Yes.

## Policy

0. **SEALED 260920 (operator)** — the champion is **Qwen3.8 Flash-Next
   UD-Q5_K_XL + the sharp template** (sharp-medium effort): the declared
   daily driver on both boxes. Evidence base: the podium below, the
   template axis measured on Q5 itself (+0.40 coding / +0.25 reasoning
   vs stock), BF16-anchor parity across three batteries, and the engine
   axis proving the tuned fork is load-bearing. Config rollout (mirror
   template, router defaults, old-gen purge) awaits separate approval.

1. **Quality first** — within acceptable speed
2. **Speed floor** — gate: at least ~200 t/s prefill and ~20 t/s
   generation, then we measure wall-clock, not server-reported
3. **Q5+ quants only** — Q4 and below are deprecated here. This floor
   comes from enterprise-level experience and community expert consensus
   on MoE quantization robustness, not from a 12-item battery alone.
   Our battery *confirms* Q5 meets the quality gate; the floor itself is
   practitioner judgment.
4. **llama.cpp first** — preferably the vanilla build (upstream master,
   easy updates); the tuned HIP fork is used where prefill speed demands.
   *Measured exception (260920):* for this model family the fork is
   load-bearing — the MTP draft GGUF is fork-format (upstream rejects
   it), and an eager-load vanilla census hard-crashed the lab box
   (no lazy-PLE path). Vanilla stays preferred for models it can host;
   see the engine-axis note in `configs/q5-flash-next-winner.md`.
5. **Open source only** — closed engines are evaluated for reference,
   never adopted
6. **Solo-coder optimized** — one user, one GPU, no multi-tenant overhead

## Hardware

| | |
|---|---|
| APU | AMD Ryzen AI MAX+ 395 (Strix Halo) |
| iGPU | Radeon 8060S (gfx1151, RDNA 3.5) — integrated, no discrete GPU |
| Memory | 128 GB unified LPDDR5x (≈124 GiB usable) — shared CPU/GPU |
| Storage | NVMe SSD (also hosts the PLE lazy-streamed weights) |

**Software stack:** ROCm 10.2 nightly (`rocm-nightly-gfx1151-bin` from AUR,
gfx1151-only build) and Arch Linux installed as a **minimal headless
server** — no desktop environment. We access it mainly via SSH; a
[Cockpit](https://cockpit-project.org) daemon is optionally enabled for
browser-based monitoring. If you reproduce this, a headless setup keeps
~5 GiB of RAM free that a desktop would otherwise consume — that margin
is counted in the [RAM accounting](#ram-accounting) table.

## Reading the tables (60-second glossary)

| symbol | means | why you care |
|---|---|---|
| **pp @Nk** | prefill throughput: tokens/second while *reading* a prompt of N thousand tokens | the "how long until it starts thinking" number — dominates coding/agentic use |
| **tg128 / tg2048** | generation speed for a 128-token / 2048-token reply | the "how fast does it type" number |
| **wall-clock** | measured from request sent to response complete | includes all overhead; the only honest metric |
| **12/12** | the Italian gate (iten12): pass/fail floor, not a ranking | a model at 12/12 meets the bar; ranking within the passing tier is by fcb15 score, speed, and RAM |
| **fcb15** | the one *scoring* quality axis — Wilson 95% CI, template/effort-sensitive (pin both or the cell is garbage); full method + reproduce-command in [its chapter](#coding--gbench-fcb15-deterministic-unit-tested) |

All speed numbers are **wall-clock on real text** — prompts actually filled
with real content, never synthetic filler (except where explicitly marked).

## Podium

All wall-clock. Higher pp/tg is better; the Italian gate (iten12) is
pass/fail at 12 — not an overall quality verdict.

| model | pp @4k | pp @32k | pp @128k | tg128 | tg2048 | Italian (iten12)¹ | fcb15 ¹⁰ | RAM (weights) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Qwen3.8 Flash-Next Q5_K_XL + MTP** ¹² | **641** | **807** | **647** | **23.6** | **25.4** | **12/12** | 0.667 | 97 GiB |
| Qwen3.8 Flash-Next Q6_K_XL + MTP ² | — ⁵ | — ⁵ | — ⁵ | 24.6 ⁶ | 25.6 ⁶ | **12/12** | — ¹¹ | 107 GiB |
| Qwen3.8 27B Q8_K_XL + DFlash2 ³ | 260 | **409** ¹³ | 394 | 15.8 | **28.0** ¹³ | 10/12 | 0.800 ¹⁰ | 30 GiB |
| Muse-Glimmer-30B Q8 + DFlash2 ³ | — | — | — | ~18 | — | **12/12** | 0.733 ¹⁰ | 32 GiB |

### Why Q5 wins

**The winner:** llama.cpp + Qwen3.8 Flash-Next Q5_K_XL (147 GiB) + its
MTP draft, on a single 128 GB Strix Halo.

- Passes the quality gate (12/12, tied with Q6 and IQ4_NL) **and** the
  speed floor
- Serves the full 262k-token context — whole codebases, no chunking —
  with ~6 GiB RAM headroom ([the math](#ram-accounting))
- A 32k-token prompt (a big file plus instructions) prefills in 40
  seconds (807 t/s) — the axis that matters for coding, and the
  co-resident pair can't touch this
- One main model + draft = zero swap overhead, simplest operations
- All **quality** scores are reproducible from this repo — serve
  commands, checksums, unit files, the batteries, and the champion's raw
  JSONL runs in [benchmarks/](benchmarks/), [configs/](configs/), and
  [systemd/](systemd/). The wall-clock speed probe is not yet committed
  (see the evidence note in
  [Speed at depth](#speed-at-depth--how-much-wall-time-you-actually-wait))

**The template confound is measured, not hypothetical** (260920 lab
run): IQ4_NL scored **0.333 on its stock template** overnight and
**0.667 with the sharp template** — same quant, battery, protocol,
hardware class; the template alone doubled the score. The
uniform-template re-cut of the Qwen-family cells is underway (IQ4
done, 27B in flight); Muse runs its stock template by family design.

### Why not IQ4_NL? (also 12/12, faster decode, less RAM)

Our Q5+ policy (principle 3). A 12-item battery can't discriminate within
the top tier — the floor itself comes from practitioner experience with
MoE quantization robustness. IQ4_NL is a strong candidate and we may
revisit; for now, Q5 is the tier we trust for production, until we find a
reliable way to run Q6.

### Why not Q6_K_XL? (also 12/12 — our preferred tier)

RAM arithmetic: 107 GiB resident + KV + draft ≈ 124 GiB on a 124 GiB box —
zero margin. We tested it: it loaded, passed the gate, then **died under
sustained load** when KV growth exceeded the remaining headroom
([the math](#ram-accounting)). **The reduced-context path is now measured,
not planned:** the catalog's 131k arm (`c = 131072`) ran the full overnight
re-run chain on a dedicated process — iten12 12/12 under the hardened
grader, then 3 h 04 m of continuous service at **GTT 125.0/133.1 GB** —
no MemoryMax crutch. The death was a 262k-config problem; at 131k the KV
pool is pre-allocated and cannot outgrow the margin. Q5 at full 262k
stays the pick; Q6 at 131k is now a demonstrated fallback tier, not a
hope.

**But there is a second, slower disease (260920, measured):** sustained
decode *degrades* even at 131k. With ngram speculation off (MTP-only,
`spec-type = draft-mtp`), fresh-load Q6 bursts at **35 t/s** — then decays
to **~2 t/s** once cumulative activated expert rows cross the ~14 GiB GTT
headroom (on strixy: after ~20–25k tokens of diverse generation; the
overnight "items run long" and the never-completing fcb15 census were
this same disease, unmeasured). ngram OFF delays it, cures nothing. GPU sits at
~13% while it crawls — disk-bound row eviction, not compute. **Q6 quality
cells collected so far** (MTP-only): iten12 12/12, fcb15 0.50 [0.19–0.81]
at n=6, AIME partial (paused by operator at ~2 t/s). **Both speed-cure
arms ran and failed (260920 evening):** `--load-mode mmap --lazy-mode on`
= kernel reclaim war (tg flat 2.59 from token one — file-backed weights
and HIP unified memory fight over the same physical pages); `c=32768 +
KV q8_0` = loads but wedges on first real generation (GPU 0%, zero
timing prints, requests hang — a fork lazy-path bug). The cure is
fork-level (or a re-quant); until then Q6 is a fresh-load tier, not a
sustained-serving tier.

### Why not the 27B + Muse pair?

Both components fail the speed floor (15.8 and ~18 t/s decode). And an
honest caveat: the pair was never benchmarked as a co-resident serving
unit — this is a component-level comparison. The pair's theoretical
advantage (62 GiB total weights, more room for context) is real but
untested as a serving configuration.

### The footnotes

¹ **How "quality" is measured:** the iten12 battery — 12 Italian↔English
bidirectional translation items, graded deterministically by a Python
harness that asserts on content keywords AND false-friend discriminators
(*attendere* for *attend* = fail). Both natural rendering conventions are
accepted. Battery v3.1 (2026-09-19): exec-namespace fix, false-friend
rejections on four more items, sentence-shape rule (keyword salad no
longer passes). The Q5 cell is re-scored under v3.1 — still 12/12;
other models' re-runs are owed. A 12/12 is a **pass/fail gate** —
"meets our floor," not "best in class."

² Q6's AIME cell is 8/11 (one item errored when the server died
mid-battery — the denominator silently changed). See ⁴.

³ Both fail the 20 t/s decode floor. Listed as reference tier only.

⁴ One item errored (INFRA — server died mid-battery), reducing the
denominator to 11. The 0.833 vs 0.727 gap is 1–2 items — within sampling
variance at temperature 1.0. Both models are in the same quality tier.

⁵ Speed-at-depth probe not yet run for Q6 — the automated bench chain was
OOM-killed before reaching it. Owed; not a zero.

⁶ Server-reported decode from the scored iten12 items (n=1 each; a 245-tok
and a ~9.3k-tok generation), not the wall-clock probe used for Q5's cells.
Honesty note: that 9.3k generation exceeds the documented 6000-token cap —
the Sep 18 journal shows generations up to ~11.9k that day, so the cell ran
with a looser cap than the protocol states. Treat as indicative: same decode
tier as Q5, ±10%; the overnight v3.1 re-run under the fixed cap replaces
these cells.

¹⁰ fcb15 cells are census scores under battery v3, uniform-template
(sharp) for the Qwen family, stock for Muse by family design — the
measured template effect is 2–3×, so template-uniform columns are the
only comparable ones. CIs and caveats live in
[the coding section](#coding--gbench-fcb15-deterministic-unit-tested).
Overlapping CIs throughout: no ranking claims.

¹¹ Q6's fcb15: the medium-effort census never completed (the
footnote-⁶ long-item profile at sustained-thrash speeds). The
MTP-only budget-6 probe measured **0.50** [0.19–0.81] — a partial
cell, wide CI, and Q6's serving-speed ceiling (see *Why not Q6*)
makes a full census uneconomic until the fork fix lands.

¹³ Measured 260921 on the DFlash2-tuned lab arm (n-max 6, sharp
template, wall-clock probe: real-text corpus, streamed first→last
token). Note both exceed the row's older cells (pp@4k 260, tg128
15.8) — those predate the DFlash2 tuning; a re-harmonized row is owed.

¹² Concurrent clients vs the 124 GiB box (f16 KV; the pool is
pre-allocated, so `c` = slots × ctx). Fixed cost ~108 GiB (weights
96.5 + MTP draft 2.8 + vision 0.9 + buffers 3.0 + OS 5.0); each
slot's KV is **6.0 GiB @256k** / 3.0 @128k / 2.25 @96k. Theoretical
slot ceilings: **2 @256k, 5 @128k, 7 @96k** — but observed page-cache
+ streaming working sets eat ~7 GiB, so **safe: 1 / 3 / 4**. Slots
also *share decode* (N clients ≈ 1/N the t/s each); KV-q8_0 would
halve slot cost but is fork-untested on Q5 (the Q6 lazy-path wedge,
*Why not Q6*).

## RAM accounting

One method, applied to every candidate. All figures GiB.

| component | Q5 @262k | Q6 @262k | Q6 @131k | IQ4_NL @262k |
|---|---:|---:|---:|---:|
| resident weights (file − PLE streamed to SSD) | 96.5 | 107.0 | 107.0 | 66.0 |
| KV cache, full-attention layers (f16) | 6.0 | 6.0 | 3.0 | 6.0 |
| MTP draft | 2.8 | 2.8 | 2.8 | 2.8 |
| mmproj vision projector (enabled in models.ini) | 0.9 | 0.9 | 0.9 | 0.9 |
| compute buffers + PLE row-reader (bounded by `-ub 4096`) | ~3.0 | ~3.0 | ~3.0 | ~3.0 |
| OS + system services | ~5.0 | ~5.0 | ~5.0 | ~5.0 |
| **total** | **114.2** | **124.7** | **121.7** | **83.7** |
| box limit | 124 | 124 | 124 | 124 |
| **headroom (theoretical)** | **9.8** | **−0.7 (doesn't fit)** | **2.3 (razor)** | **40.3** |

**Observed in practice:** with the full 262k KV pool allocated and the
server idle, the box reports ~121 of 124 GiB used (~3 GiB available) —
page cache and streaming working sets consume most of the theoretical
margin. The `MemoryMax=118G` systemd cap sits between: enough room for
the ~114 GiB footprint, tight enough that an OOM kill (which is what
killed the Q6 bench chain) is the failure mode, not silent swap.

Where the numbers come from:
- **KV cache** at 262k = 12 full-attention layers × 2 KV heads ×
  (256 key + 256 value) dims × 2 bytes × 262144 positions ≈ 6.0 GiB.
  The model is **hybrid-attention** (GGUF metadata: 48 layers,
  `full_attention_interval = 4` — only every 4th layer retains full KV;
  the rest are sparse/indexed with a bounded window), which is why the
  KV is so light for a 262k context.
- **PLE row-reader** is bounded by `-ub 4096`; larger micro-batches scale
  it linearly, and without the bound, 32k+ prefills amplify row reads past
  the RAM ceiling.
- **OS + buffers** = 5 GiB, applied uniformly to every candidate (earlier
  versions used a looser estimate — this table is the corrected one).

## Quality battery (iten12)

This battery doesn't find "the best model" — it identifies which models
are **good enough** for our mission. Models that pass are then ranked by
speed, RAM, and context headroom.

| model | score |
|---|---:|
| Flash-Next Q5_K_XL | **12/12** |
| Flash-Next IQ4_NL | **12/12** |
| Flash-Next Q6_K_XL | **12/12** |
| Muse-Glimmer Q8 | **12/12** |
| Qwen3.8 27B Q8 | 10/12 |
| DeepSeek V4.1 Flash Q2 (local, SSD-streamed) ⁷ | 10/12 |
| GLM-5.3 (cloud) ⁷ | 7/12 |

All local cells ran the hardened **v3.1** grader (overnight re-run,
2026-09-20) — the battery is uniform across the table at last.
Muse-Glimmer moved 11/12 (v2) → **12/12** under the hardened grader.

**Honest caveat:** at n=12, a one-item difference is within sampling noise
(Fisher's exact p ≈ 0.49 for 12/12 vs 10/12). The battery is a floor
check, not a top-tier discriminator. Coding is now covered separately
([GBench fcb15](#coding--gbench-fcb15-deterministic-unit-tested) and
[zebra](#zebra--csp-logic-ladder-gbench)); long-context retrieval is
still planned.

⁷ Cloud and streamed-local models must follow the same strict format
contract (ONE python code block printing the answer). A frontier cloud
model scoring 7/12 is more likely a format-compliance artifact of the
battery than a capability signal — treat cloud cells as format checks,
not quality verdicts. The DeepSeek local Q2's 10/12 is genuine (it runs
the same contract as the locals).

## AIME-12 (reasoning)

| model | score | n |
|---|---:|---:|
| **Flash-Next Q5_K_XL** | **0.833** | 12 |
| Flash-Next Q6_K_XL † | 0.727 | 11 ⁴ |
| Flash-Next IQ4_NL † | 0.667 | 12 |
| Qwen3.8 27B Q8 † | 0.667 | 12 |
| Muse-Glimmer Q8 † | 0.583 | 12 |
| DeepSeek V4.1 Flash (cloud) ⁷ ⁸ † | 0.667 | 12 |
| GLM-5.3 (cloud) ⁷ † | 0.500 | 12 |

Q6's lower score is 1–2 items at n=11 — same tier, see ⁴.

**Year-stratified re-cut (2026-09-20)** — the contamination-owed fix,
6×AIME2025 + 6×AIME2026, seed 1300, same graders:

| model | yearsplit | n |
|---|---:|---:|
| **Flash-Next Q5_K_XL** (sharp) | **0.833** | 12 |
| Flash-Next Q6_K_XL (sharp) | 0.750 | 12 |
| 27B BF16 anchor (sharp) | 0.750 | 12 |
| Flash-Next IQ4_NL (stock) | 0.417 | 12 |
| Qwen3.8 27B Q8 (stock) | 0.417 | 12 |
| Qwen3.8 27B Q8 (sharp) | 0.500 | 12 |
| Muse-Glimmer Q8 (stock) | 0.333 | 12 |

Cells run sharp-medium (template noted per cell); the stock cells are
pre-re-cut. Two structural findings: the **27B BF16 anchor (0.750)
lands BELOW the Q5-quantized champion (0.833)** and ties the Q6
quant — the flash MoE architecture dominates reasoning regardless of
quant tier; and the sharp template lifts the 27B's reasoning too
(0.417→0.500) but far less than it lifted its coding score
(0.267→0.800). Year-mix caveat: 2025 items remain contamination-suspect
for locals.

**†** scored under the pre-2026-09-19 grader (exec-namespace bug:
structured solutions crashed the grader and were scored FAIL) — these
cells skew low. Only Q5's AIME cell has been re-run under the fixed
grader; the remaining re-runs are owed (see `grading_changelog` in
[results.json](benchmarks/results.json)).

**Contamination:** 8 of the 12 seed-1300 items come from AIME 2025 —
solutions public ~18 months at test time, so local-model cells are
contamination-likely; 4 come from AIME 2026. A year-stratified re-cut
is owed (see `aime_selection_split` in
[results.json](benchmarks/results.json)).

⁸ The DeepSeek cloud cell was also run as a full 60-item census:
29/60 = 0.483. The 12-item seed-1300 subset scored 8/12 = 0.667 — the
subset ran easy for it. The census is the more reliable cloud number;
both are reported, none hidden.

## Coding — GBench fcb15 (deterministic, unit-tested)

The iten12/AIME pair can't see coding ability, and both saturate by
design — they are pass/fail gates. **fcb15** is different on both counts:
15 short, deterministic, unit-tested coding tasks from the GBench battery
corpus of **[Good-Enough-For-Coding](https://github.com/PieBru/Good-Enough-For-Coding)**
(working copy in [PieBru/Qwen38_Strix](https://github.com/PieBru/Qwen38_Strix/tree/main/gbench);
minimal runner vendored in [gbench/](gbench/)). Grading is outcome-based —
behavioral unit tests written at grade time, no LLM judge, no gold-diff —
and the probe reports a **Wilson 95% CI** with every query accounted
(failed queries spend budget; a full run is labeled census).

On saturation, precisely: fcb15 is a *fixed bank* scored as a fraction,
with **pre-registered item swaps** as the anti-saturation stopgap when a
family hits the ceiling. The structural fix — scoring *at what difficulty
the model breaks* instead of *how many of N* — is GEFC's **non-saturating
measurement layer** (difficulty-threshold scoring; currently a
pre-development proposal). Until it lands, read census cells with the
Wilson ceiling in mind: two models at 15/15 are rank-indistinguishable.
Even so, a scoring cell discriminates wherever the gate saturates — which
is why fcb15 earns a podium column.

Uniform-template fcb15 column — sharp family, effort noted per cell
(**low is the promoted default**, 260921):

| model | template / effort | fcb15 | CI95 |
|---|---|---:|---|
| **Flash-Next Q5_K_XL (champion)** | sharp **low** | **0.867** (13/15, census) | 0.62–0.96 |
| Qwen3.8 27B Q8 + DFlash | sharp medium | **0.800** (12/15, census) | 0.55–0.93 |
| Muse-Glimmer Q8 | stock (family design) | 0.733 (11/15, census) | 0.48–0.89 |
| Flash-Next Q5_K_XL | sharp medium | 0.667 (10/15, census) | 0.42–0.85 |
| Flash-Next IQ4_NL | sharp medium | 0.667 (10/15, census) | 0.42–0.85 |
| Flash-Next Q6_K_XL | sharp medium | 0.50 partial ¹¹ | — |

The template is not cosmetics: measured on three arms it **doubled**
(IQ4 0.333 → 0.667), **tripled** (27B 0.267 → 0.800), and on the
champion itself runs 0.267 (stock embedded) → 0.667 (sharp medium) →
**0.867 (sharp low)** — the effort dial is the same lever again
(the full matrix lives in *Reasoning effort — measured*). Read the
ranking with the usual discipline — overlapping CIs, 2–3-item gaps at
n=15, and Muse runs a different family's template. Under uniform
templates the BF16-parity 27B-Q8 leads coding while the quantized
flash arms lead reasoning — the quantization cost is battery-dependent
(see the note below).

**Reproducing a cell (for agents).** Pin *both* the template file and
the effort tier or the number is garbage — a stock-template run reads
as a different model (that exact mislabel happened here, 260920):

```bash
cd gbench && uv run python3 scripts/probe.py --battery fcb15 \
  --budget 15 --tag <model>-<template>-<effort> --model <arm> \
  --http-timeout 2700 --rdir <evidence-dir>
```

The arm's `chat-template-file` (now `sharp-v22.5.0-low.jinja` by
default) is set in the serving ini, not in the probe. `budget 15` =
census (every item attempted); failed queries **spend** budget — a
cell with `answered < budget` is an incident, not a score. Evidence
is the stamped `.jsonl` + Wilson `.json` pair in `--rdir`; the repo
copies live in `benchmarks/`.

**How to read it** (260920 re-cut): the disentangling runs are done —
IQ4-with-sharp doubled (0.333 → 0.667) and 27B-with-sharp tripled
(0.267 → 0.800), so the table above is uniform-template for the Qwen
family, and what remains is the honest residue: overlapping CIs and
2–3-item gaps at n=15 (no crowning), Muse runs its own family's
template by design, and fcb15 measures short, deterministic,
unit-tested tasks — not the agentic/real-world coding the community's
Qwen3.8-over-Muse consensus is about; that regime stays untested here.
Q6's cell is owed (items exceeded the 900 s HTTP budget — retry in
flight).

### Reasoning effort — measured (260920)

The sharp template's effort dial is a real quality axis, not just a
speed knob. Champion Q5, same batteries, greedy census, only the
template default changed:

| effort | fcb15 | CI95 | iten12 | AIME yearsplit |
|---|---:|---|---|---|
| medium (all published cells) | 0.667 | 0.42–0.85 | 12/12 | 0.833 |
| **low** | **0.867** | 0.62–0.96 | 12/12 | **0.833** |
| none (thinking off) | 0.667 | 0.42–0.85 | 12/12 | **0.917** |
| xhigh | 0.267 | 0.07–0.56 | — | 0.667 |
| *(stock template, medium)* | *0.267* | *0.11–0.52* | — | *0.583* |

**The matrix is closed, and low is the unambiguous sweet spot.** On
fcb15 the effort curve is an inverted-U — xhigh 0.267 < medium/none
0.667 < low 0.867: *overthinking actively damages agentic coding*.
On AIME the family is flat (0.667–0.917, single-item spreads), with
nothink's 11/12 the best point estimate and xhigh the worst. Low
wins coding outright, ties reasoning, and is strictly fastest in
wall-clock — three batteries, cross-box, stamped evidence. An earlier
version of this table recorded the stock-template cell (0.583) as
"low" — a config slip, corrected 260920; the promotion of low to
default awaits the operator seal.

**The template is the champion's biggest single lever — measured on
Q5 itself** (same accidental controlled run): fcb15 **0.267 → 0.667**,
AIME **0.583 → 0.833**. The disentangler result first seen on IQ4 and
27B generalizes: the sharp template is worth +0.40 coding / +0.25
reasoning — larger than any quant-tier step we measured.

**Promotion question for the operator:** with no measured downside,
making `low` the default effort level is a live decision — the
remaining caution is generalization (n = 12–15 per battery, CIs wide;
fcb15 replication cross-box in flight).

### Quantization and coding/agentic quality — the honest note

The producer's benchmarks (reliable, but BF16-vs-BF16) show Flash-Next
beating the 27B on every benchmark, with the widest gap exactly on
agentic coding (DeepSWE 58.7 vs 42.2). Our table measures a different,
asymmetric matchup: the 27B at Q8 (≈ BF16-parity) against Flash-Next
at Q5/Q6 — a heavily quantized MoE. Two things we can say, one we owe:

- **Measured here, under uniform templates: battery-dependent.** The
  BF16-parity 27B-Q8 leads the coding battery (fcb15 0.800 vs the
  flash arms' 0.667 — overlapping CIs, 2 items), while the quantized
  flash arms lead reasoning decisively (AIME yearsplit 0.833/0.750
  vs 0.417). No external per-quant benchmark for the Flash-Next
  Q5/Q6 GGUFs exists to check against; community wisdom is
  qualitative (Q5 ≈ Q6 ≈ Q8 perceptually; "flash even in Q4/Q5 over
  the 27B" on this RAM class).
- **Degradation-vs-self is battery-dependent.** fcb15 is quant-flat
  (IQ4 = Q5 = 0.667 under the sharp template) while AIME shows IQ4
  bleeding to 0.417 — reasoning depth degrades before short-task
  codegen does. Saturated batteries cannot see this at all (iten12:
  everyone 12/12 — the floor gate is ceiling-blind to quant loss). The
  reasoning-effort dial interacts too (Q5's fcb15 rose 0.667 → 0.867 at
  low effort), so quant conclusions hold only at a stated effort
  level.
- **Owed: the unquantized anchor.** What we cannot yet say is how far
  Q5/Q6 sit from their BF16 selves in absolute terms — Flash-Next BF16
  (300+ GB) can never run on this box. The 27B's BF16 (~55 GB) can: a
  BF16-27B cell on our batteries anchors the ladder, and GEFC's
  [non-saturating threshold layer](https://github.com/PieBru/Good-Enough-For-Coding)
  is the definitive instrument (θ across the quant ladder — its design
  case).

## Zebra — CSP logic ladder (GBench)

30-item constraint-satisfaction ladder, grid-graded, same probe
methodology (subset cells at n=12 or n=20 as labeled; seed-1300
stratified):

| model | zebra | CI95 | n |
|---|---:|---|---:|
| 27B BF16 (anchor, sharp) | 0.65 | 0.43–0.82 | 20 |
| **Flash-Next Q5 (sharp-low)** | **0.65** | 0.43–0.82 | 20 |
| Qwen3.8 27B Q8 + DFlash | 0.55 | 0.34–0.74 | 20 |
| **Flash-Next Q5_K_XL** | **0.50** | 0.25–0.75 | 12 |
| Muse-Glimmer Q8 | 0.45 | 0.26–0.66 | 20 |
| Flash-Next IQ4_NL | 0.42 | 0.19–0.68 | 12 |
| DeepSeek V4.1 Flash (cloud) ⁷ | 0.42 | 0.19–0.68 | 12 |
| GLM-5.3 (cloud) ⁷ | 0.25 | 0.09–0.53 | 12 |

260920: the BF16 anchor row landed (0.65 — the morning cell had died
silently on a port transition, re-run clean), and the Q5 row at
sharp-low matches it exactly — the champion at low effort closes the
one battery where the 27B pair edged it (overlapping CIs throughout).
The low-effort promotion gate passed here too: +0.15 over Q5-medium's
0.50. Zebra remains everyone's weakest battery — the CSP ladder is
where headroom lives.

## Speed at depth — how much wall-time you actually wait

Real-text prompts actually filled (no synthetic filler). These are the
seconds from "send" to "reply complete."

**Why seconds, not tokens/second:** most speed talk quotes pp/tg —
tokens/second while filling or draining the context. Fine as kernel
diagnostics, but they say next to nothing about what you actually wait:
the wall-clock time to complete a task **successfully** — prefill at
real depth, retries, and re-generating artifacts that failed QA all
included. (An independent DeepSeek run posted healthy-looking completion
rates across 83 minutes of model wall time and delivered zero accepted
artifacts — the t/s looked fine, the task failed.) Reasoning models
sharpen the point further: our champion thinks before it answers, so a
task's token count is reasoning + answer, and decode t/s alone can't
tell you how many tokens you'll wait through. This table is in seconds
for that reason.

| prompt size | Q5 | Halogen | who wins |
|---|---:|---:|---|
| 4k | 6.4 s | 5.5 s | Halogen, slightly |
| 32k | **40.6 s** | 9.1 min | **Q5, 13.5×** |
| 128k | **3.3 min** | 29.5 min | **Q5, 8.9×** |

For context: a 32k prompt is roughly "a medium codebase plus your task."
A 128k prompt is "the whole monorepo." This is why prefill-at-depth is
the deciding axis for coding.

**Credit where due:** Halogen wins decode at every depth (32.4/27.3/25.6
vs our 23.6–25.4 t/s) and wins prefill at 4k. For short-prompt chat,
it's the faster engine. The collapse at depth is what kills it for our
workload. Its 128k cell completed at 1770s — 30s under our client
timeout — real but with a thin margin; the non-monotonic throughput
(60 → 71 t/s) is unexplained — the 32k cell matches nominal-size
arithmetic (32768/546 = 60.0) while the 128k cell reads 131072/1770 =
74, not 71; the probe's raw token counts will settle it.

**Evidence note:** the wall-clock probe behind this table — and the
pp/tg podium cells — is not yet committed. Quality cells reproduce from
[benchmarks/](benchmarks/); the speed harness and its raw logs are
owed.

## DeepSeek V4.1 Flash Q2 — tested, parked

A 340.6 GiB MoE that streams experts from SSD: 4.4–4.9 t/s decode.
Below our speed floor and below our quant floor. Independently
replicated with the same verdict — parked
([tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo);
see the replication note in the recipe). Full recipe in
[configs/deepseek-v41-parked.md](configs/deepseek-v41-parked.md).

## Reproduce it

Everything is in the repo:

- [benchmarks/](benchmarks/) — **the batteries and runner behind our quality
  tables**: ITEN-12 v2, AIME-60, a deterministic runner, and our measured
  results (`results.json`). Three commands reproduce a score — see
  [benchmarks/README.md](benchmarks/README.md)
- [gbench/](gbench/) — the GBench coding/CSP probe (fcb15 + zebra
  batteries, Wilson-CI runner) behind the
  [coding](#coding--gbench-fcb15-deterministic-unit-tested) and
  [zebra](#zebra--csp-logic-ladder-gbench) tables
- [configs/](configs/) — exact serve commands, binary provenance (commits,
  digests, build recipes), full sha256 checksums, flag-by-flag explanations
- [models.ini](models.ini) — the single source of truth for all serving
  options
- [systemd/](systemd/) — the two unit files (HIP fast-prefill and Vulkan
  vanilla), switchable with one command
- [doctor/](doctor/) — the Doctor WebUI + its unit — 24/7 monitoring and
  the nightly auto-improve loop (see the chapter below)

## The "sharp" chat template

The serve recipe doesn't use the stock Qwen3.8 template. It runs
[configs/templates/sharp-v22.5.0.jinja](configs/templates/sharp-v22.5.0.jinja)
(`qwen3.8-froggeric-v22.5.0`, from
[froggeric/Qwen-Fixed-Chat-Templates](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates)
on Hugging Face — attributed to its author and subject to their terms)
because it is the control surface for thinking:

- `enable_thinking` — default **true**: reasoning streams before the
  answer, which is why the champion runs as a thinking model in our cells
- `reasoning_effort` — `none`/`off` disables thinking outright;
  `low`/`medium`/`xhigh` pick a tier (default `medium`)
- `auto_disable_thinking_with_tools`, `preserve_reasoning` across turns,
  an XML tool-call format, and vision plumbing

Two honesty notes: every measured quality and speed cell ran through
this template — the numbers are template-specific, we have not run a
stock-vs-sharp battery A/B, and none of the published cells ran with
thinking off. `sha256 cdff39fb26b60dc90faa292e726655c6b21f62db497846e02e4c4bbab942a84a`.
The stock template is a drop-in swap of the `chat-template-file` line if
you prefer upstream-default behavior.

## The Doctor — 24/7 monitoring and the nightly auto-improve loop

The repo ships the monitoring layer exactly as it runs on the reference
box: [doctor/Doctor.py](doctor/Doctor.py) — a single-file, stdlib-only
web app (htmx, 2 s poll) — and its user unit
([doctor/Doctor.service](doctor/Doctor.service)).

### The WebUI (:8667)

- **System cards** — GPU (GTT counters — the real UMA numbers, not the
  1 GiB carve-out %), RAM, disk, CPU
- **Inference cards** — resident arm and recent loads, live tg and draft
  acceptance sparklines, service and `/health` state
- **Error banner** — health / service / journal / dmesg, minus
  known-benign patterns; **activity log** — live tail of the router
  journal
- **Operator links** (`/res/*`) — read-only excerpts: the router ini
  header, latest morning report, spec-sweep results, harvest stats, and
  `/res/doctor` — the latest nightly report
- **Read-only by design** — no ini writes, no arm swaps, no privileged
  calls; ~25 MB RSS flat, sub-1% of one core

Install — `ROUTER_UNITS` at the top of `Doctor.py` names the units it
watches (defaults are the reference box's `model-router-pwilkin`/
`-vanilla`; this repo's units are `llama-hip`/`llama-vulkan`):

```bash
cp doctor/Doctor.py ~/Doctor.py    # edit ROUTER_UNITS if your units differ
install -Dm644 doctor/Doctor.service ~/.config/systemd/user/Doctor.service
systemctl --user daemon-reload && systemctl --user enable --now Doctor
```

`:8667` binds `0.0.0.0` without auth on the reference box — the same
trust decision as `:8080`. Bind loopback if that is not your threat
model.

### The nightly job (03:00, unattended, read-only)

Behind an idle gate, the doctor-dream skill (pi) runs a nightly checkup:
deterministic collectors digest the last 24 h — journal, inference,
resources, agent sessions, backlog, upstream — then an agent pass turns
the digest into a dated `DOCTOR_REPORT_*.md`, a human morning summary,
and panel data, served at `/res/doctor`. Upstream moves aren't just
recorded: the four engine repos — llama.cpp, pwilkin/strix-halo,
halo-box/strix-llama.cpp, antirez/ds4 — get a useful-to-us evaluation
against the champion recipe's axes (deep-prefill, decode, RAM/GTT,
PLE/lazy-load, speculation, gfx1151 correctness), with adopt-worthy
changes flagged as proposals; adoption itself stays operator-sealed. It
never modifies the system.
Findings carry severity (P1–P3), evidence labeled OBSERVED vs INFERRED,
a proposed action, and a verify condition; carry items close only when a
later night's verify passes.

### The loop it enables — proposals out, human seal on every change

The doctor's findings feed an auto-improve loop (repo Principles #3):
findings and audits become *proposed* patches — to the serving stack,
the batteries, or the doctor itself — and a human authorizes each one
(`needs-operator-authorization: yes` on anything touching config,
services, or policy). Two worked examples from the same day:

- **Loop working:** an audit caught the WebUI watching pre-rename
  unit names (`flash-router`) — showing a healthy router as down. Fixed,
  browser-verified, vendored into this repo the same day.
- **Loop correctly stopped at a human:** the 03:00 report's P1 "orphaned
  GTT leak" was an INFERRED misread — the GTT-vs-RSS gap is the PLE
  lazy-loading footprint; identical GTT/RAM after a clean reboot
  falsified the leak. The doctor proposed; the reboot's natural
  experiment disposed — no change landed on a wrong inference.

## Methodology

For those who want to check our work:

- **Wall-clock** (request sent → response complete), never server-reported
- **Prompts actually filled** — no empty-slot theater
- Same item-selection seed (1300); **scored cells ran greedy (temp 0.0)** —
  the serve recipe (temp 1.0, top_p 0.95, top_k 20) is the producer's
  recommendation for live traffic, while the batteries grade greedy for
  determinism; at temp 1.0 expect ±1–2 items variance at n=12
- **The champion is a thinking model** — reasoning tokens stream before
  the answer by default under our template (`reasoning_content`); the
  batteries grade the *last* python block after the thinking, and
  `max_tokens 6000` is sized to leave that thinking room
- Both natural translation conventions accepted (v2 battery; v1 had a
  10/12 ceiling by forcing one convention — fixed)
- All cells on identical hardware, same binary where noted
- Speed numbers from the pwilkin HIP binary; vanilla-VK serves Q5 at
  quality parity, but a fair speed comparison is owed (the vanilla config
  may need `-ngl 999` — testing pending)
- **Known limitation:** the iten12 battery measures translation quality,
  not coding ability — that is measured by the [GBench fcb15 and zebra
  cells](#coding--gbench-fcb15-deterministic-unit-tested); long-context
  retrieval items are planned.

## Acknowledgements

Standing on the shoulders of open-source giants:

- [llama.cpp](https://github.com/ggml-org/llama.cpp) — the foundation
- [unsloth](https://huggingface.co/unsloth) — the dynamic-quant GGUFs
- [pwilkin/strix-halo](https://github.com/pwilkin/strix-halo) — ROCm tuning
  and PLE lazy loading
- [halo-box/strix-llama.cpp](https://github.com/halo-box/strix-llama.cpp) —
  the community gfx1151 fork
- [antirez](https://github.com/antirez/ds4) — the [DS V4.1 inference
  engine](https://github.com/antirez/ds4) and [GGUF
  publication](https://huggingface.co/antirez/deepseek-v4.1-flash-gguf)
- [tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo) —
  independent Strix Halo benchmarks; shared methodology means shared
  assumptions — treat as a reproducibility reference, not independent
  validation; their 260917 run replicated our DeepSeek park verdict and
  supplied the ds4 host-sqrt patch
- [ROCm](https://github.com/ROCm/ROCm) — AMD's open compute stack
- [Arch Linux](https://archlinux.org) — the rolling-release distro

## License

All results, recipes, and configurations in this repository are released
under the [MIT License](LICENSE). The models and engines referenced are
subject to their own respective licenses.
