#!/usr/bin/env python3
"""arms_summary — collapse the overnight arms JSONLs into RESULTS.md table rows.

Usage:
  uv run python3 scripts/arms_summary.py [results-dir] [--ci] [--selftest]

Reads results/fcb15-<tag>.jsonl for the six arms tags from scripts/arms.sh and
prints one table row per arm (markdown-ready):

  single  -> greedy X/15 | with-retry Y/15 | wall-time | hardware-class
  bestof  -> best-of-5 solved X/15 | shots used (avg) | wall-time | hardware-class

The hardware-class column comes from the --hardware tag the runner stamped
into each row (rows without it show "—"); speed/cost are always
hardware-bound, so the column keeps cross-class comparisons visible. The six
2026-08-25 arms predate the --hardware flag; their rows carry a retrospective
stamp with an explicit "hardware_source" provenance key (see RESULTS.md
history) — those bindings are retrospective, not machine-stamped at run time.

Score rules mirror the runner: greedy rows count phase=="greedy"; the
with-retry score is greedy-ok plus retry06-ok rows. Bestof solved count comes
from phase=="bestof" rows. Wall-time = sum of per-row wall fields (model time
only; router recipe-swap loads ~6-13 s per arm are not included).

--ci adds the inferential layer (P0, docs/RESEARCH-*.md §5.1):
  * Wilson 95% CI on every pass-rate row;
  * exact two-sided McNemar on paired arm deltas (paired by item; an item is
    "resolved" for a single arm if greedy OR retry06 passed, and for a bestof
    arm if its bestof row passed — pairing pre-registered in RESULTS.md);
  * Benjamini-Hochberg FDR adjustment across the pairwise tests.
Stdlib only; --selftest verifies the math against hand-computed values
(docs/RESEARCH-*.md §2.1/§2.2) and exits 1 on any mismatch.

Exit code 0 (1 if --selftest fails).
"""

import json
import math
import os
import random
import sys
from collections.abc import Callable
from typing import TypedDict

ARMS = [
    ("calib27B-balanced", "single", "balanced", "Qwen38-27B-balanced (Q6 @ 128k)"),
    ("calib27B-quality", "single", "quality", "Qwen38-27B-quality@128k (Q8 @ 128k)"),
    ("calib27B-speed", "single", "speed", "Qwen38-27B-speed (Q5 @ 64k)"),
    ("bestof27B-coding", "bestof", "coding", "Qwen38-27B-coding best-of-5"),
    ("bestof27B-balanced", "bestof", "balanced", "Qwen38-27B-balanced best-of-5"),
    ("bestof27B-speed", "bestof", "speed", "Qwen38-27B-speed best-of-5"),
]

Z = 1.959963984540054  # two-sided 95% normal quantile
# Wilson score interval math: cf. docs/RESEARCH-SCIENTIFIC-METHOD-AND-LEADERBOARDS.md §2.1

# ------------------------- spec 009 estimators (P1) -------------------------
# Hand-computed fixtures for all of these live in selftest(); every formula
# here is pre-registered in docs/RESEARCH-*.md §1.2/§2.2/§2.3/§2.8/§2.11.


def pass_at_k(c: int, n: int, k: int) -> float:
    """Unbiased Codex pass@k estimator (§2.8): 1 - C(n-c, k)/C(n, k) — the
    probability of at least one correct in k samples given c correct in n."""
    if not 1 <= k <= n:
        raise ValueError(f"need 1 <= k <= n, got k={k} n={n}")
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def a12(xs: list[float], ys: list[float]) -> float:
    """Vargha–Delaney A12 (§2.11): P(x > y) + 0.5*P(x == y) over all pairs —
    the interpretable effect size for non-normal cost/wall distributions
    ('x beats y in A12*100% of draws')."""
    if not xs or not ys:
        raise ValueError("a12 needs non-empty samples")
    num = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in xs for y in ys)
    return num / (len(xs) * len(ys))


def bootstrap_ci(
    samples: list[float],
    stat: Callable[[list[float]], float],
    seed: int,
    b: int = 2000,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile-bootstrap CI of stat(samples); deterministic given the
    recorded seed (identical input + seed => identical CI)."""
    rng = random.Random(seed)
    n = len(samples)
    stats = sorted(stat(rng.choices(samples, k=n)) for _ in range(b))
    return stats[int(b * alpha / 2)], stats[int(b * (1 - alpha / 2))]


def clustered_se(probs: list[float]) -> float | None:
    """SE of the mean per-item pass probability (cluster = item, §2.2/§2.3):
    sd(items)/sqrt(n) — the battery is a census of fixed items, so intervals
    generalize over the seeded sampling, phrased finite-population."""
    n = len(probs)
    if n < 2:
        return None
    m = sum(probs) / n
    return (sum((p - m) ** 2 for p in probs) / (n * (n - 1))) ** 0.5


def mcnemar_repeats(k_favor: int, n_disc: int) -> float | None:
    """Exact two-sided McNemar at the REPEAT-PAIR level (§2.2): the r-repeat
    form — an all-favorable 2-item flip at r=3 gives 2*0.5^6 = 0.03125.
    n_disc = total discordant repeat pairs, k_favor = those favoring arm A."""
    if n_disc <= 0:
        return None
    tail = sum(math.comb(n_disc, i) for i in range(0, min(k_favor, n_disc - k_favor) + 1))
    return min(1.0, 2.0 * tail * (0.5**n_disc))


def shuffle_order(n: int, seed: int) -> list[int]:
    """Deterministic seeded execution order (§1.2): item indices are
    PERMUTED, never renumbered — pairing across arms stays valid."""
    return random.Random(seed).sample(range(n), n)


def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials -> (lo, hi).
    Raises ValueError on n == 0 (no trials measured — callers fail loud, never
    fabricate a CI)."""
    if n <= 0:
        raise ValueError(f"wilson: no trials (k={k}, n={n}) — nothing measured")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, min(1.0, (c + h) / d))


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p: 2 * P(X <= min(b,c)), X ~ Binom(b+c, 0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    return min(1.0, sum(math.comb(n, k) for k in range(m + 1)) * (0.5**n) * 2)


def bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg step-up FDR-adjusted p-values (same order as input)."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):  # largest raw p first
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        adj[i] = prev
    return adj


def selftest():
    """Runnable check (constitution: leave one behind, sabotage-verified)."""
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    lo, hi = wilson(13, 15)
    chk(
        "wilson(13,15) == [0.62, 0.96]  (RESEARCH §2.1)",
        (round(lo, 2), round(hi, 2)) == (0.62, 0.96),
    )
    lo, hi = wilson(12, 15)
    chk(
        "wilson(12,15) == [0.55, 0.93]  (RESEARCH §2.1)",
        (round(lo, 2), round(hi, 2)) == (0.55, 0.93),
    )
    lo, hi = wilson(15, 15)
    chk(
        "wilson(15,15) == [0.80, 1.00]  (RESEARCH §2.1)",
        (round(lo, 2), round(hi, 2)) == (0.80, 1.00),
    )
    chk("mcnemar(2,0) == 0.50  (RESEARCH §2.2)", mcnemar_exact(2, 0) == 0.5)
    chk("mcnemar(3,0) == 0.25", mcnemar_exact(3, 0) == 0.25)
    chk("mcnemar(1,0) == 1.00", mcnemar_exact(1, 0) == 1.0)
    chk("mcnemar(0,0) == 1.00  (no discordant pairs)", mcnemar_exact(0, 0) == 1.0)
    adj = bh_adjust([0.01, 0.04, 0.03])
    chk("bh([.01,.04,.03]) == [.03,.04,.04]", [round(a, 6) for a in adj] == [0.03, 0.04, 0.04])
    chk("bh monotone in raw p  (p_i <= p_j => adj_i <= adj_j)", adj[0] <= adj[2] <= adj[1])

    # ---- spec 009 (P1) fixtures: pass@k, A12, clustered SE, repeats McNemar
    chk(
        "pass@k closed form: pass@1 | c=1,n=5 == 0.2  (RESEARCH §2.8)",
        abs(pass_at_k(1, 5, 1) - 0.2) < 1e-12,
    )
    chk("pass@k: pass@5 | c=1,n=5 == 1.0", abs(pass_at_k(1, 5, 5) - 1.0) < 1e-12)
    chk(
        "pass@k closed form: pass@2 | c=3,n=5 == 0.9",
        abs(pass_at_k(3, 5, 2) - 0.9) < 1e-12,
    )
    chk("a12 identical samples == 0.5  (RESEARCH §2.11)", a12([1, 2, 3], [1, 2, 3]) == 0.5)
    chk("a12 strict domination == 1.0", a12([4, 5, 6], [1, 2, 3]) == 1.0)
    chk("a12 ties count 0.5", a12([2, 2], [1, 2]) == 0.75)
    chk(
        "clustered SE [0,1] == 0.5  (sd/sqrt(n), cluster=item)",
        (lambda se: se is not None and abs(se - 0.5) < 1e-12)(clustered_se([0.0, 1.0])),
    )
    chk("clustered SE needs n>=2", clustered_se([1.0]) is None)
    chk(
        "repeats McNemar: all-favorable 2-item flip, r=3 => 2*0.5^6 == 0.03125  (§2.2)",
        abs((mcnemar_repeats(6, 6) or 0) - 0.03125) < 1e-12,
    )
    chk("repeats McNemar: zero discordance => None (not resolved)", mcnemar_repeats(0, 0) is None)
    ci1 = bootstrap_ci([1.0, 2.0, 3.0, 4.0], lambda xs: sum(xs) / len(xs), seed=7, b=200)
    ci2 = bootstrap_ci([1.0, 2.0, 3.0, 4.0], lambda xs: sum(xs) / len(xs), seed=7, b=200)
    chk("bootstrap deterministic given seed", ci1 == ci2)
    chk("bootstrap CI brackets the mean", ci1[0] <= 2.5 <= ci1[1])
    chk(
        "shuffle deterministic + index-preserving (§1.2)",
        shuffle_order(10, 42) == shuffle_order(10, 42)
        and sorted(shuffle_order(10, 42)) == list(range(10))
        and shuffle_order(10, 42) != shuffle_order(10, 43),
    )
    return ok


def load_rows(rdir, tag):
    path = os.path.join(rdir, f"fcb15-{tag}.jsonl")
    if not os.path.exists(path):
        return None
    try:
        return [json.loads(ln) for ln in open(path)]
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read {path}: {e}", file=sys.stderr)
        raise SystemExit(2) from e


def resolved_by_item(rows, mode):
    """item -> resolved bool (single: greedy or retry06 ok; bestof: bestof ok)."""
    res = {}
    for r in rows:
        if mode == "single" and r["phase"] in ("greedy", "retry06"):
            res[r["item"]] = res.get(r["item"], False) or r["ok"]
        elif mode == "bestof" and r["phase"] == "bestof":
            res[r["item"]] = r["ok"]
    return res


class ArmData(TypedDict):
    mode: str
    key: str
    greedy: tuple[int, int]
    retry: tuple[int, int]
    bestof: tuple[int, int]
    hw: str | None
    resolved: dict[int, bool]


def rdir_of(args: list[str]) -> str:
    return next((a for a in args if not a.startswith("--")), "results")


def arg_after(args: list[str], flag: str, k: int = 1) -> str:
    i = args.index(flag)
    return args[i + k]


def cmd_passk(rdir: str, tag: str) -> int:
    """Unbiased pass@k curve from one best-of-N run's shotN rows (FR-004).
    Curve computed over FULL-SWEEP items only (coverage stated when mixed);
    pass@N uses all items (empirical any-of — unchanged semantics)."""
    rows = load_rows(rdir, tag)
    if rows is None:
        print(f"passk: no artifact for {tag}")
        return 1
    by_item: dict[int, list[int]] = {}
    for r in rows:
        if str(r.get("phase", "")).startswith("shot"):
            by_item.setdefault(r["item"], []).append(1 if r["ok"] else 0)
    if not by_item:
        print(f"passk: {tag} has no shotN rows (not a bestof run)")
        return 1
    n_max = max(len(v) for v in by_item.values())
    full = {i: v for i, v in by_item.items() if len(v) == n_max}
    mean_prob = sum(sum(v) / len(v) for v in by_item.values()) / len(by_item)
    label = (
        "full sweep"
        if len(full) == len(by_item)
        else (f"PARTIAL (full-sweep items {len(full)}/{len(by_item)} — curve on full sweep only)")
    )
    print(f"pass@k — {tag} — {label}")
    for k in range(1, n_max + 1):
        est = sum(pass_at_k(sum(v), len(v), k) for v in full.values()) / len(full)
        lo, hi = wilson(round(est * len(full)), len(full))
        print(f"  pass@{k}: {est:.3f}  Wilson 95% CI [{lo:.2f}, {hi:.2f}]")
    any_of = sum(1 for v in by_item.values() if any(v)) / len(by_item)
    lo, hi = wilson(round(any_of * len(by_item)), len(by_item))
    print(
        f"  pass@{n_max} (empirical any-of, ALL {len(by_item)} items): "
        f"{any_of:.3f}  Wilson 95% CI [{lo:.2f}, {hi:.2f}]"
    )
    print(f"  mean per-item pass probability (mixed-coverage honest cell): {mean_prob:.3f}")
    return 0


def cmd_repeats(rdir: str, tag: str, seed: int = 200900) -> int:
    """Repeats battery summary (FR-002): mean per-item pass probability,
    clustered SE (cluster = item), seeded percentile-bootstrap CI."""
    rows = load_rows(rdir, tag)
    if rows is None:
        print(f"repeats: no artifact for {tag}")
        return 1
    by_item: dict[int, list[int]] = {}
    for r in rows:
        if str(r.get("phase", "")).startswith("rep"):
            by_item.setdefault(r["item"], []).append(1 if r["ok"] else 0)
    if not by_item:
        print(f"repeats: {tag} has no repN rows (run with --repeats)")
        return 1
    r_levels = {len(v) for v in by_item.values()}
    probs = [sum(v) / len(v) for v in by_item.values()]
    mean_p = sum(probs) / len(probs)
    if len(probs) < 2 or all(d == 1 for d in r_levels):
        print(f"repeats {tag}: no repeats depth (R=1) — point estimate only: {mean_p:.3f}")
        return 0
    se = clustered_se(probs)
    lo, hi = bootstrap_ci(probs, lambda xs: sum(xs) / len(xs), seed=seed)
    depth = "uniform" if len(r_levels) == 1 else f"MIXED depth {sorted(r_levels)} — coverage stated"
    print(
        f"repeats {tag}: mean per-item pass probability {mean_p:.3f} | "
        f"clustered SE (cluster=item) {se:.3f} | percentile-bootstrap 95% CI "
        f"[{lo:.3f}, {hi:.3f}] (seed {seed}, {len(probs)} items, {depth}) — "
        "census of fixed items: intervals generalize over the seeded sampling"
    )
    return 0


def cmd_a12(rdir: str, tag_a: str, tag_b: str, seed: int = 200901) -> int:
    """Paired cost/wall effect size (FR-005): Vargha–Delaney A12 with a
    paired percentile-bootstrap CI (method + seed recorded); ratios via
    bootstrap on the ratio, never naive differences."""
    rows_a, rows_b = load_rows(rdir, tag_a), load_rows(rdir, tag_b)
    if rows_a is None or rows_b is None:
        print(f"a12: missing artifact ({tag_a}={rows_a is not None}, {tag_b}={rows_b is not None})")
        return 1

    def walls(rows):
        return {r["item"]: r.get("wall", 0.0) for r in rows if r.get("phase") == "greedy"}

    wa, wb = walls(rows_a), walls(rows_b)
    common = sorted(set(wa) & set(wb))
    if len(common) < 2:
        print(f"a12: fewer than 2 paired items ({len(common)})")
        return 1
    xs = [wa[i] for i in common]
    ys = [wb[i] for i in common]
    est = a12(xs, ys)
    idx = list(range(len(common)))
    rng = random.Random(seed)

    def _bs() -> float:
        sel = rng.choices(idx, k=len(idx))
        return a12([wa[i] for i in sel], [wb[i] for i in sel])

    stats = sorted(_bs() for _ in range(2000))
    lo, hi = stats[int(2000 * 0.025)], stats[int(2000 * 0.975)]
    print(
        f"a12 — {tag_a} vs {tag_b} wall (paired by item, n={len(common)}): "
        f"A12={est:.3f} (A beats B in {100 * est:.0f}% of paired draws) | "
        f"paired percentile-bootstrap 95% CI [{lo:.3f}, {hi:.3f}] "
        f"(method: resample items with replacement; seed {seed})"
    )
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return 0 if selftest() else 1
    # spec 009 additive modes (default/--ci output unchanged — SC-004)
    if "--passk" in args:
        return cmd_passk(rdir_of(args), arg_after(args, "--passk"))
    if "--a12" in args:
        return cmd_a12(rdir_of(args), arg_after(args, "--a12"), arg_after(args, "--a12", 2))
    if "--repeats" in args:
        return cmd_repeats(rdir_of(args), arg_after(args, "--repeats"))
    do_ci = "--ci" in args
    rdir = rdir_of(args)

    data = {}
    for tag, mode, recipe_key, recipe in ARMS:
        rows = load_rows(rdir, tag)
        if rows is None:
            print(f"| {tag:20s} | {recipe:38s} | (no rows yet) | | | |")
            continue
        hw = next((r.get("hardware") for r in rows if r.get("hardware")), None)
        wall = round(sum(r.get("wall", 0) for r in rows), 0)
        if mode == "single":
            g = [r for r in rows if r["phase"] == "greedy"]
            rt = [r for r in rows if r["phase"] == "retry06"]
            gs = sum(r["ok"] for r in g)
            rs = gs + sum(r["ok"] for r in rt)
            print(
                f"| {tag:20s} | {recipe:38s} | greedy {gs}/{len(g)} | "
                f"with-retry {rs}/{len(g)} | {wall:.0f}s wall | {hw or '—'} |"
            )
            data[tag] = ArmData(
                mode=mode,
                key=recipe_key,
                greedy=(gs, len(g)),
                retry=(rs, len(g)),
                bestof=(0, 0),
                hw=hw,
                resolved=resolved_by_item(rows, mode),
            )
        else:
            b = [r for r in rows if r["phase"] == "bestof"]
            solved = sum(r["ok"] for r in b)
            shots = [r.get("shots_used") for r in b if r.get("shots_used")]
            avg = round(sum(shots) / len(shots), 1) if shots else 0
            print(
                f"| {tag:20s} | {recipe:38s} | best-of-5 {solved}/{len(b)} | "
                f"{avg:.1f} shots avg | {wall:.0f}s wall | {hw or '—'} |"
            )
            data[tag] = ArmData(
                mode=mode,
                key=recipe_key,
                greedy=(0, 0),
                retry=(0, 0),
                bestof=(solved, len(b)),
                hw=hw,
                resolved=resolved_by_item(rows, mode),
            )

    if do_ci and data:
        print("\n## Wilson 95% CIs (pass-rate rows)")
        for tag, d in data.items():
            if d["mode"] == "single":
                for label, (k, n) in (("greedy", d["greedy"]), ("with-retry", d["retry"])):
                    if n == 0:
                        print(f"| {tag:20s} | {label:11s} | 0 rows — not measured | |")
                        continue
                    lo, hi = wilson(k, n)
                    print(f"| {tag:20s} | {label:11s} | {k}/{n} | [{lo:.2f}, {hi:.2f}] |")
            else:
                k, n = d["bestof"]
                if n == 0:
                    print(f"| {tag:20s} | best-of-5   | 0 rows — not measured | |")
                    continue
                lo, hi = wilson(k, n)
                print(f"| {tag:20s} | best-of-5   | {k}/{n} | [{lo:.2f}, {hi:.2f}] |")

        print("\n## Paired deltas — exact McNemar (item-paired, resolved; BH-adjusted)")
        singles = [t for t in data if data[t]["mode"] == "single"]
        tests = [
            (singles[i], singles[j])
            for i in range(len(singles))
            for j in range(i + 1, len(singles))
        ]
        for tag, d in data.items():  # same-recipe single-vs-bestof, where both exist
            if d["mode"] == "bestof":
                twin = next((t for t in singles if data[t]["key"] == d["key"]), None)
                if twin:
                    tests.append((twin, tag))
        results = []
        for a, b in tests:
            ra, rb = data[a]["resolved"], data[b]["resolved"]
            items = sorted(set(ra) | set(rb))
            x = sum(1 for i in items if ra.get(i) and not rb.get(i))  # a-only pass
            y = sum(1 for i in items if rb.get(i) and not ra.get(i))  # b-only pass
            results.append((a, b, x, y, mcnemar_exact(x, y)))
        adj = bh_adjust([r[4] for r in results]) if results else []
        for (a, b, x, y, p), q in zip(results, adj, strict=True):
            print(f"| {a} vs {b} | discordant {x}:{y} | McNemar p = {p:.3f} | BH-adj p = {q:.3f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
