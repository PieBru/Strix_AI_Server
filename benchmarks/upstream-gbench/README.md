# upstream-gbench — raw evidence behind pre-v3.1 cells

Per-item JSONL runs copied verbatim from the GBench working tree
(`PieBru/Qwen38_Strix` → `gbench/results/fcb15-probe-*.jsonl`). These are
the runs behind most of the original (v1/v2-grader) iten12/AIME/zebra
cells in `../results.json` — kept as historical evidence, in their
original schema (`phase`/`budget`/`selection` keys; no `bat`/`temp`
stamps — that stamping arrived later in `../run.py`).

Cross-check vs published cells (260919 audit):

| file | raw | published | verdict |
|---|---|---|---|
| flashq5-iten12 / flashq6-iten12 / flashiq4-v2-iten12 / muse-v2-iten12 | 12/12 ×3, 11/12 | 12, 12, 12, 11 | exact |
| flashq5-aime / flashq6-aime / flashiq4-aime | 10/12, 8/11, 8/12 | 10, 8, 8 | exact |
| flashq5-zebra | 6/12 | 0.50 | exact |
| muse-aime | 8/12 | 7/12 | ±1 — variant ambiguity (muse-aime vs museQ5/Q6-aime runs exist) |
| q8df2-iten12 | 9/12 | 10 | ±1 — same class |
| q8df2-aime | 9/12 | (8, from q8df-aime) | ±1 — two q8df variants exist |

The ±1 cells are not reconciled: multiple same-model run files exist
upstream and the published summary may derive from a sibling variant.
The v3.1 re-runs (stamped rows, single canonical files) supersede all of
the above; until they land, treat these files as provenance, not truth.
