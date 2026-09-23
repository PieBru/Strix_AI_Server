# Local-cell audit — 2026-09-23

Every quality cell in `README.md` for the **local** models, checked against
`benchmarks/results.json` and the artifacts on disk. Cloud rows are out of
scope: they are frozen until their next model evolution, and the superseded
2026-09-16 GLM-5.3 cells are already documented in footnote 24.

Legend — **fresh**: current grader, artifact on disk. **stale**: pre-grader-fix
or superseded basis. **owed**: not yet run. **in flight**: this audit's pass
(2026-09-23, both boxes).

## iten12 (the Italian pass/fail gate)

| model | cell | grader | date | status |
|---|---|---|---|---|
| Qwen3.8 Flash-Next Q5_K_XL | 12/12 | v3.1 (exec fix + notkw + shape + clock) | 2026-09-17 | fresh |
| Qwen3.8 Flash-Next IQ4_NL | 12/12 | v3.1 (overnight re-run 2026-09-20) | 2026-09-20 | fresh |
| Qwen3.8 Flash-Next Q6_K_XL | 12/12 | v3.1 (overnight re-run 2026-09-20) | 2026-09-20 | fresh |
| Muse-Glimmer-30B Q8 | 12/12 | v3.1 (overnight re-run 2026-09-20) | 2026-09-20 | fresh |
| Qwen3.8 27B Q8_K_XL | 10/12 | v3.1 (overnight re-run 2026-09-20) | 2026-09-20 | fresh |
| DeepSeek V4.1 Flash Q2 (local, SSD-streamed) | 10/12 | v2 | 2026-09-19 | stale (pre-v3.1) |
| Qwen3.8 27B BF16 (anchor) | 10/12 | v3.1 | 2026-09-20 | fresh |
| Qwen3.8 27B Q8 + DFlash2 (sharp) | None/12 |  | 2026-09-20 | stale (pre-v3.1) |

## AIME-12, stratified selection (the † cells)

| model | cell | grader | date | status |
|---|---|---|---|---|
| Qwen3.8 Flash-Next Q5_K_XL | 0.833 (10/12) | v2 grader (exec fix) — re-run 2026-09-19: 10/12, ide | 2026-09-17 | **stale (broken grader)** |
| Qwen3.8 Flash-Next Q6_K_XL | 0.727 (8/11) | v1-grader (pre exec-namespace fix) | 2026-09-17 | **stale (broken grader)** |
| Qwen3.8 Flash-Next IQ4_NL | 0.667 (8/12) | v1-grader (pre exec-namespace fix) | 2026-09-17 | **stale (broken grader)** |
| Qwen3.8 27B Q8_K_XL | 0.667 (8/12) | v1-grader (pre exec-namespace fix) | 2026-09-17 | **stale (broken grader)** |
| Muse-Glimmer-30B Q8 | 0.583 (7/12) | v1-grader (pre exec-namespace fix) | 2026-09-17 | **stale (broken grader)** |

## AIME yearsplit-12 — the contamination fix

__

| model | yearsplit | n | template | date |
|---|---|---|---|---|
| Qwen3.8 Flash-Next IQ4_NL | None | 12 |  | 2026-09-20 |
| Qwen3.8 27B Q8_K_XL | None | 12 |  | 2026-09-20 |
| Muse-Glimmer-30B Q8 | None | 12 |  | 2026-09-20 |
| Qwen3.8 Flash-Next Q6_K_XL | None | 12 |  | 2026-09-20 |
| Qwen3.8 Flash-Next Q5_K_XL | None | 12 |  | 2026-09-20 |
| Qwen3.8 27B BF16 (anchor) | None | 12 |  | 2026-09-20 |

## fcb15 coding census

| model | cell | CI95 | basis | date | status |
|---|---|---|---|---|---|
| Qwen3.8 Flash-Next Q5_K_XL | 0.667 (10/15) | [0.42–0.85] | fcb15 v3 | 2026-09-19 | fresh |
| Muse-Glimmer-30B Q8 | 0.733 (11/15) | [0.48–0.89] | fcb15 v3 | 2026-09-20 | fresh |
| Qwen3.8 Flash-Next IQ4_NL | 0.333 (5/15) | [0.15–0.58] | fcb15 v3 | 2026-09-20 | fresh |
| Qwen3.8 27B Q8_K_XL | 0.267 (4/15) | [0.11–0.52] | fcb15 v3 | 2026-09-20 | fresh |
| Qwen3.8 Flash-Next Q6_K_XL | owed | — |  |  | owed |
| Qwen3.8 Flash-Next IQ4_NL + sharp(medium) | 0.667 (10/15) | [0.42–0.85] | fcb15 v3 | 2026-09-20 | fresh |
| Qwen3.8 27B Q8_K_XL + DFlash + sharp(medium) | 0.8 (12/15) | [0.55–0.93] | fcb15 v3 | 2026-09-20 | fresh |
| Qwen3.8 27B BF16 (anchor) | 0.667 (10/15) | [0.42–0.85] | fcb15 v3 | 2026-09-20 | fresh |

## Zebra CSP ladder

| model | cell | CI95 | n | date |
|---|---|---|---|---|
| Qwen3.8 27B Q8_K_XL + DFlash | 0.55 | [0.34–0.74] | 20 | 2026-09-16 |
| Qwen3.8 Flash-Next Q5_K_XL | 0.5 | [0.25–0.75] | 12 | 2026-09-17 |
| Muse-Glimmer-30B Q8 | 0.45 | [0.26–0.66] | 20 | 2026-09-16 |
| Qwen3.8 Flash-Next IQ4_NL | 0.4167 | [0.19–0.68] | 12 | 2026-09-17 |
| Qwen3.8 Flash-Next Q6_K_XL | None | — | None | None |
| Qwen3.8 27B BF16 (anchor) | 0.65 | [0.43–0.82] | 20 | 2026-09-20 |
| Qwen3.8 Flash-Next Q5_K_XL (sharp-LOW) | 0.5667 | [0.39–0.73] | 30 | 2026-09-20 |
| Qwen3.8 Flash-Next Q5_K_XL (sharp-MEDIUM, full 30) | 0.5333 | [0.36–0.70] | 30 | 2026-09-20 |

## sli (structured-list canary)

_first measurements 260920 night (strixy, paired same-box): sli saturates at both effort tiers_

| model | cell | n | effort |
|---|---|---|---|
| Q5 champion | 1.0 | 10 | low |
| Q5 champion | 1.0 | 10 | medium |

## fcb15 threshold ladder

_{"what": "GEFC L1 tier ladder \u2014 greedy pass rates, template-UNIFORM (both models on sharp-low, the promoted default), one box, one harness", "uniform_sharp_low": {"qwen38-flash-q5": {"v3+D": "10/_


## Artifacts on disk

**benchmarks/** (per-item JSONL + result JSON, vendored):

- `benchmarks/aime-27bbf16-yearsplit.jsonl` — 2622 B
- `benchmarks/aime-27bq8-sharp-yearsplit.jsonl` — 2234 B
- `benchmarks/aime-muse-glimmer-q8-yearsplit.jsonl` — 1762 B
- `benchmarks/aime-q5-low-yearsplit.jsonl` — 1736 B
- `benchmarks/aime-q5-nothink-yearsplit.jsonl` — 2337 B
- `benchmarks/aime-q5-truelow-low.jsonl` — 2586 B
- `benchmarks/aime-q5-xhigh-yearsplit.jsonl` — 1857 B
- `benchmarks/aime-qwen38-27b-q8-df-yearsplit.jsonl` — 1797 B
- `benchmarks/aime-qwen38-flash-iq4-yearsplit.jsonl` — 1795 B
- `benchmarks/aime-qwen38-flash-q5-v2g.jsonl` — 1797 B
- `benchmarks/aime-qwen38-flash-q5-yearsplit.jsonl` — 2334 B
- `benchmarks/aime-qwen38-flash-q6-yearsplit.jsonl` — 2743 B
- `benchmarks/aime60-q5low.jsonl` — 10278 B
- `benchmarks/aime60-q5med.jsonl` — 9799 B
- `benchmarks/fcb15-27b-sharp.jsonl` — 2558 B
- `benchmarks/fcb15-27bbf16.jsonl` — 2560 B
- `benchmarks/fcb15-iq4-sharp.jsonl` — 2575 B
- `benchmarks/fcb15-probe-muse-glimmer-q8-fcb15.jsonl` — 2559 B
- `benchmarks/fcb15-probe-qwen38-27b-q8-df-fcb15.jsonl` — 2581 B
- `benchmarks/fcb15-probe-qwen38-flash-iq4-fcb15.jsonl` — 2580 B
- `benchmarks/fcb15-q5-boxcontrol-strixy2.jsonl` — 2560 B
- `benchmarks/fcb15-q5-low.jsonl` — 2617 B
- `benchmarks/fcb15-q5-nothink.jsonl` — 2680 B
- `benchmarks/fcb15-q5-stock-strixy2.jsonl` — 2446 B
- `benchmarks/fcb15-q5-xhigh.jsonl` — 2566 B
- `benchmarks/fcb15-qwen38-flash-q5.jsonl` — 3130 B
- `benchmarks/iten12-27b-bf16.jsonl` — 2879 B
- `benchmarks/iten12-27b-sharp.jsonl` — 2859 B
- `benchmarks/iten12-iq4-sharp.jsonl` — 2879 B
- `benchmarks/iten12-muse-glimmer-q8.jsonl` — 2867 B
- `benchmarks/iten12-q5-boxcontrol-strixy2.jsonl` — 2869 B
- `benchmarks/iten12-q5-low.jsonl` — 2917 B
- `benchmarks/iten12-q5-nothink.jsonl` — 2964 B
- `benchmarks/iten12-qwen38-27b-q8-df.jsonl` — 2888 B
- `benchmarks/iten12-qwen38-flash-iq4.jsonl` — 2880 B
- `benchmarks/iten12-qwen38-flash-q5-v3.jsonl` — 2365 B
- `benchmarks/iten12-qwen38-flash-q6.jsonl` — 2867 B
- `benchmarks/sli-q5low.jsonl` — 1700 B
- `benchmarks/sli-q5med.jsonl` — 1700 B
- `benchmarks/zebra-27bbf16-v2.jsonl` — 3381 B
- `benchmarks/zebra-q5low-30.jsonl` — 5133 B
- `benchmarks/zebra-q5low.jsonl` — 3381 B
- `benchmarks/zebra-q5med-30.jsonl` — 4894 B
- `benchmarks/fcb15-27b-sharp.probe.json` — 638 B
- `benchmarks/fcb15-iq4-sharp.probe.json` — 642 B
- `benchmarks/fcb15-q5-boxcontrol-strixy2.probe.json` — 639 B
- `benchmarks/fcb15-qwen38-flash-q5.probe.json` — 649 B
- `benchmarks/results.json` — 22565 B

**gbench/results/** (probe results carrying the Wilson CIs):


## Ground-truth reconciliation (artifact → README)

Counted directly from the per-item JSONL on disk (`ok / n`), not from
`results.json`.

| README cell | artifact on disk | counted | README says | verdict |
|---|---|---|---|---|
| Q5 iten12 | `iten12-q5-low.jsonl` | 12/12 | 12/12 | ✓ |
| Q5 AIME yearsplit | `aime-qwen38-flash-q5-yearsplit.jsonl` | 10/12 = 0.833 | 0.833 | ✓ |
| Q5 fcb15 sharp-low | `fcb15-q5-low.jsonl` | 13/15 = 0.867 | 0.867 | ✓ |
| Q5 zebra | `zebra-q5low.jsonl` (n=20) | 13/20 = **0.65** | 0.65 (podium) | ✓ |
| Q5 zebra | `zebra-q5low-30.jsonl` (n=30) | 17/30 = **0.567** | *not in README* | **unpublished** |
| Q5 zebra | `results.json` (n=12) | 0.50 | 0.50 (zebra chapter) | **conflicts with the podium** |
| Q5 sli | `sli-q5low.jsonl` / `sli-q5med.jsonl` | 10/10 both | 10/10 | ✓ |
| Q6 iten12 | `iten12-qwen38-flash-q6.jsonl` | 12/12 | 12/12 | ✓ |
| Q6 AIME yearsplit | `aime-qwen38-flash-q6-yearsplit.jsonl` | 9/12 (16 rows, 4 errored) | 0.750 | ✓ |
| Q6 fcb15 | gbench `probe-q6-low-*` | 13/15 (2026-09-23) | 0.867 | ✓ (but `results.json` still says *owed*) |
| 27B iten12 | `iten12-qwen38-27b-q8-df.jsonl` | 10/12 | 11/12 | **mismatch — check** |
| 27B AIME yearsplit (sharp) | `aime-27bq8-sharp-yearsplit.jsonl` | 6/12 = 0.500 | 0.500 | ✓ |
| 27B AIME yearsplit (stock) | `aime-qwen38-27b-q8-df-yearsplit.jsonl` | 5/12 = 0.417 | 0.417 | ✓ |
| 27B fcb15 (sharp-med) | `fcb15-27b-sharp.jsonl` | 12/15 = 0.800 | 0.800 | ✓ |
| 27B BF16 AIME yearsplit | `aime-27bbf16-yearsplit.jsonl` | 9/12 = 0.750 | 0.750 | ✓ |
| 27B BF16 fcb15 | `fcb15-27bbf16.jsonl` | 10/15 = 0.667 | 0.667 | ✓ |
| 27B BF16 zebra | `zebra-27bbf16-v2.jsonl` | 13/20 = 0.65 | 0.65 | ✓ |
| Muse iten12 | `iten12-muse-glimmer-q8.jsonl` | 12/12 | 12/12 | ✓ |
| Muse AIME yearsplit | `aime-muse-glimmer-q8-yearsplit.jsonl` | 4/12 = 0.333 | 0.333 | ✓ |
| Muse fcb15 | `fcb15-probe-muse-glimmer-q8-fcb15.jsonl` | 11/15 = 0.733 | 0.733 | ✓ |
| IQ4 iten12 | `iten12-iq4-sharp.jsonl` | 12/12 | 12/12 | ✓ |
| IQ4 fcb15 (sharp) | `fcb15-iq4-sharp.jsonl` | 10/15 = 0.667 | 0.667 | ✓ |
| IQ4 AIME yearsplit | `aime-qwen38-flash-iq4-yearsplit.jsonl` | 5/12 = 0.417 | 0.417 | ✓ |

## Findings

1. **Four AIME-12 stratified cells are stale** — Q6, IQ4_NL, 27B-Q8 and Muse all
   ran under the **v1 grader** (the exec-namespace bug scored structured
   solutions FAIL). These are the README's † cells; re-runs are owed.
2. **One direct mismatch needs a decision**: the 27B's iten12 artifact
   (`iten12-qwen38-27b-q8-df.jsonl`) counts **10/12**, while the README publishes
   **11/12** (`iten12-27b-sharp.jsonl` also holds 11/12). Two artifacts, two
   numbers — the published cell must name which run it is.
3. **Q5's zebra cell is three different numbers in three places**: 0.65 (n=20,
   the podium), 0.50 (n=12, the zebra chapter table) and **0.567 (n=30, the
   largest measurement, unpublished)**. The podium's own footnote 21 says the
   n=20 cell is the shipped-default measurement — but the zebra chapter table
   contradicts it, and the n=30 re-score ("regressed to mean") is the number a
   reader would most want to see.
4. **`results.json` no longer fully backs the README**: the `aime_yearsplit`
   records carry `ok`/`n` but no `score`, the Q6 zebra record is all-`None`, and
   Q6's fcb15 still reads *owed* although the 64k census landed 2026-09-23.
5. **One malformed record**: `Qwen3.8 27B Q8 + DFlash2 (sharp)` under `iten12`
   has `ok: null` with `n: 12`.
6. **Missing cells, in flight now** (2026-09-23, both boxes): Q6 sli/zebra/ladder
   at the 64k tier (strixy2, `q6c64l2`) and the 27B's sharp-low fcb15 + AIME
   yearsplit (strixy, `27b-low-pair`).
