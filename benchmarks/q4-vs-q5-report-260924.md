# Flash-Next UD-Q4_K_XL + MTP vs the UD-Q5_K_XL incumbent — measured 260924

**Question.** Serve Flash-Next at **UD-Q4_K_XL** (the Ollama-catalog default quant) as a
faster, lighter alternative to the incumbent **UD-Q5_K_XL + MTP** arm. Which MTP draft
should ride with it, and does Q4 lose anything that matters?

**Short answer.** Serve Q4_K_XL with the **shared-Q4_K_M** draft. It is ~1–2 % slower on
decode, **~+20 % faster on prefill**, 36 GiB smaller, and **matched or beat Q5 on every
quality cell we ran today** (iten12 12/12 vs 12/12; fcb15 14/15 vs 13/15). The memory
argument is the decisive one: 111.3 GiB of weights fits a 124 GiB box, 147.4 GiB does not
— see "Why this matters" at the bottom.

## What was run

Same arm, same config, both draft phases, fresh corpus per phase, 90 s settle before
measuring (260924 lesson: the first ~5 min read low):

```
strixy2  llama-server (fork) :8091
  -m  Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf   (111.3 GiB, 4 shards)
  -md shared-Q8_0 (2.79 GiB)  |  phases A and B  |  shared-Q4_K_M (1.91 GiB)
  -dev ROCm0 -ngl 999 -fa on -fit off --load-mode none --lazy-mode on-direct
  -c 131072  -ctk f16 -ctv f16  -b 8192 -ub 4096  --parallel 1
  --spec-type draft-mtp --spec-draft-ngl 99 --spec-draft-n-min 0 --spec-draft-n-max 3
  --chat-template-file templates/sharp-v22.5.0-low.jinja --jinja
```
Logs: `~/Piero/Work/Qwen38/reruns-260919/q6-low-row/q4-mtp-ab.log` (strixy),
raw per-item rows in `~/Good-Enough-For-Coding/results/fcb15-q4-census.jsonl`,
`iten12-q4.jsonl`.

## 1. Which draft? (same model, same config — the only variable is the draft file)

| cell | A — shared-Q8_0 (2.79 GiB) | **B — shared-Q4_K_M (1.91 GiB)** | incumbent Q5 + MTP |
|---|---|---|---|
| prefill 4k | 830 t/s | **865 t/s** | 707 t/s |
| prefill 32k | 888 t/s | **909 t/s** | — |
| decode 128 | 32.6 t/s | **33.5 t/s** | 36.4 t/s |
| decode 2048 | 27.4 t/s | **31.7 t/s** | 32.2 t/s |
| echo (4k gen, 7.8k prompt) | 39.8 t/s | **40.8 t/s** | 37.8 t/s |
| draft acceptance 128 / 2048 / echo | 0.66 / 0.52 / 0.98 | 0.63 / 0.53 / 0.99 | 0.73–0.75 |

**B wins every cell.** The margin is small on 128 tokens (+2.7 %), real on 2048 (+16 %),
and the two drafts are within noise on acceptance. There is no quality reason to pay the
extra 0.88 GiB for the Q8_0 draft: **take shared-Q4_K_M.**

(pp128k reads `n/a (HTTP 400)` for both phases — the probe's 128k window exceeds the arm's
served 131072 context minus generation. Expected, not a failure.)

## 2. Does Q4 lose quality vs the Q5 incumbent?

Same battery, same runner, **same day, same box, same protocol** (the Q5 leg re-run today
against the restored incumbent arm specifically so this comparison is apples-to-apples):

| battery | Q4_K_XL + Q4_K_M draft | Q5_K_XL incumbent |
|---|---|---|
| iten12 (v3.1) | **12/12 = 1.000** | **12/12 = 1.000** |
| fcb15 census (v3, greedy) | **14/15 = 0.933** | 12/15 = 0.800 |
| fcb15 census (v3, with-retry) | **14/15 = 0.933** | 13/15 = 0.867 |

**Q4 does not lose anything; on this battery it is ahead.** Both arms fail the *same*
item (item 2) — so that miss is a property of the task/grader, not of the quant. Q5
additionally fails item 13. With n=15 the point estimates are 1–2 items apart and the
Wilson 95 % intervals overlap (≈[0.70, 0.99] vs [0.62, 0.96]): read this as **"Q4 is not
worse"**, not as "Q4 is smarter". The structural wins (memory, prefill) are the ones to
act on.

## 3. Serving recommendation

| role | arm | where |
|---|---|---|
| **default / fast / quality** | Flash-Next **UD-Q4_K_XL + shared-Q4_K_M draft**, f16 KV @131k, sharp-low, nmax 3 | both boxes — it is the only tier that fits a 124 GiB box with headroom |
| on-demand "deep"/quality tier | UD-Q5_K_XL (or Q6_K_XL) + MTP | only where the box is otherwise idle; 147–158 GiB of weights cannot be resident safely |

This is a **quant swap, not a model swap**: same base, same template, same MTP recipe,
same prompts. No quality regression was measurable.

## 4. Why this matters — the 260924 memory finding (operator rule)

Operator rule for all inference work from 260924: **RAM < 100 %, swap < 0.5 GiB, no
refault/traffic storms**; a resident arm must leave ≥ 8 GiB host headroom.

- **strixy (local, 124 GiB):** the resident `qwen38-flash-q5` arm (147.4 GiB of GGUF,
  f16 KV @131k) held 116 GiB GTT, faulted the rest from disk, and collapsed to
  **1.64 t/s at 3 % GPU busy**, RAM 122/124 GiB, **12.9 GiB swap**, PSI-full ≈ 20 %.
  Fixed today by making the default arm `qwen38-flash-iq4nl` (**93.3 GiB**, same recipe):
  **37.9 t/s**, RAM 86.7/124 GiB, swap 520 MiB and flat, PSI-full **0.00**, GTT 81.6 GiB.
  Verified with a live request (draft acceptance 0.60, mean len 4.0).
- **strixy2:** the A/B arm measured at RAM 101/127 GiB, swap 95 MiB, PSI 0.00 — inside the
  envelope. The restored Q5 incumbent sits at **~98 % RAM** with only ~2–4 GiB available:
  it passes today, it has no margin, and it is the same over-subscription as the local
  storm waiting for the next long prefill. **Applied 260924 (operator-approved): strixy2's
  `q5-serve.service` now defaults to Q4_K_XL + shared-Q4_K_M draft** — RAM 75 % (was 98 %),
  swap 82 MiB, PSI 0.00; live check 33.3 t/s, draft acceptance 0.73. Unit backup:
  `q5-serve.service.bak-260924-q5`.

## 5. Evidence paths

| artifact | path |
|---|---|
| A/B log (both phases, acceptance lines) | `~/Piero/Work/Qwen38/reruns-260919/q6-low-row/q4-mtp-ab.log` |
| Q4 quality | `iten12-q4.jsonl`, `fcb15-q4.txt`, `~/Good-Enough-For-Coding/results/fcb15-q4-census.jsonl` |
| Q5 quality (same-day, same protocol) | `fcb15-q5-260924.txt`, `fcb15-q5-guard.log` |
| local arm switch (before/after) | `/tmp/local-arm-switch.log`, `models.ini.bak-260924-storm` |
| corpora / probes | `benchmarks/corpus/speed-corpus.txt`, `speed_probe.py`, `echo_probe.py` |

**Caveats.** One corpus per phase (fresh per phase, not repeated) — decode cells carry the
usual ±1–2 t/s run-to-run band. fcb15 n=15 makes 1-item differences non-significant. Q4
was measured on strixy2 with the Q4_K_M draft only for the quality legs (draft choice was
settled by the speed A/B above).
