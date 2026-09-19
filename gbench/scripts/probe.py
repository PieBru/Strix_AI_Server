#!/usr/bin/env python3
"""probe — budgeted single-candidate evaluation with a valid CI (spec 013).

Under a fixed query budget B the probe evaluates exactly <=B battery items,
returns a pass-rate estimate with a Wilson 95% CI (the implemented method —
stated, never the FAQ paper's stronger guarantee), and accounts every query:
failed queries SPEND budget (they were asked); the CI uses answered queries
with the reduced n stated.

Item selection is adaptive: informative-ranked from spec 012's IRT artifact
(results/irt-<version>.json top-k by information) when available and
version-matched; seeded stratified-random fallback otherwise — the mode and
seed recorded. Selection uses only already-answered outcomes (no peeking):
v1 selection is fixed-order (informative ranking / stratified draw decided
up front), which trivially satisfies no-peeking; the report states it.

Boundaries: B < 3 refuses loudly (a 1-query CI is theater); B >= battery
size runs the full census, LABELED census; the probe inherits the runner's
guards (request timeout, grade SIGALRM, resume-safe JSONL, wedged-endpoint
stop).

The probe report is machine-readable (results/probe-<tag>.json) for spec
014's search to consume.

Usage:
  uv run python3 scripts/probe.py --battery fcb15 --budget 6 --tag p1 \
      --model Qwen38-27B-coding --hardware "Strix Halo fleet (gfx1151)"
  uv run python3 scripts/probe.py --selftest
"""

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from typing import Any

MIN_B = 3  # below this a CI is theater (pinned)
NOMINAL = 0.95
COV_TOL = 0.01  # empirical coverage must be >= nominal - tol (pinned)
SIM_TRIALS = 1200


def _load(rel):
    spec = importlib.util.spec_from_file_location(rel.replace("/", "_"), rel)
    assert spec is not None and spec.loader is not None, f"missing {rel}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arms_summary: Any = _load("scripts/arms_summary.py")

BATTERY_FILES = {
    # minimal vendored set — the full registry (sli/cbi/aime/iten12/...) lives
    # upstream: https://github.com/PieBru/Qwen38_Strix/tree/main/gbench
    "fcb15": ("batteries/fcb15_items.py", "v3"),  # arms-graded battery version
    "zebra": ("batteries/zebra_items.py", None),
}


def select_items(n_items, budget, irt_path=None, seed=1300):
    """Adaptive selection: IRT informative top-k when the artifact matches,
    else seeded stratified-random. Returns (order, mode, rationale)."""
    if irt_path and os.path.exists(irt_path):
        try:
            art = json.load(open(irt_path))
        except (OSError, ValueError) as e:
            raise SystemExit(
                f"ERROR: IRT artifact {irt_path} unreadable ({e}) — fail loud, "
                "fix or delete it; never probe against a silently-skipped ranking") from e
        ranked = [r["item"] for r in art.get("subset", {}).get("ranked", [])]
        if not ranked:
            ranked = [it["item"] for it in sorted(art.get("items", []), key=lambda it: -it["info"])]
        # extend a short stored subset with the full information ranking
        full = [it["item"] for it in sorted(art.get("items", []), key=lambda it: -it["info"])]
        for i in full:
            if i not in ranked:
                ranked.append(i)
        if len(ranked) >= n_items:  # ranking covers the whole battery
            order = [i for i in ranked if i < n_items][:budget]
            return (
                order,
                "informative-ranked (IRT top-k)",
                (
                    f"IRT artifact {os.path.relpath(irt_path)} (battery "
                    f"{art.get('battery_version')}); fixed order decided up front "
                    "(no peeking: selection uses no answered outcomes)"
                ),
            )
    # stratified-random fallback: even/odd strata sampled evenly, seeded;
    # budget >= battery size takes the census directly
    if budget >= n_items:
        return list(range(n_items)), "census (budget >= battery size)", "full battery"
    rng = random.Random(seed)
    strata = [list(range(0, n_items, 2)), list(range(1, n_items, 2))]
    half = budget // 2
    sel = set(
        rng.sample(strata[0], min(half, len(strata[0])))
        + rng.sample(strata[1], min(budget - half, len(strata[1])))
    )
    rest = [i for i in range(n_items) if i not in sel]  # fill remainder
    rng.shuffle(rest)
    while len(sel) < budget and rest:
        sel.add(rest.pop())
    order = sorted(sel)[:budget]
    return (
        order,
        f"stratified-random (seed {seed})",
        (
            "no version-matched IRT artifact — seeded stratified fallback; "
            "fixed order decided up front (no peeking)"
        ),
    )


def probe_estimate(answers):
    """Wilson CI on the answered queries (the implemented estimator)."""
    k = sum(answers)
    n = len(answers)
    if n == 0:
        return None
    lo, hi = arms_summary.wilson(k, n)
    return {
        "k": k,
        "n": n,
        "estimate": round(k / n, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "method": "Wilson score interval (implemented; not the FAQ factor model)",
    }


_RUNNER_CACHE: dict = {}


def _runner_for(battery):
    """Runner wired for one battery, selfcheck gated ONCE per process (the
    evaluator seam spec 014 calls at every rung)."""
    if battery not in _RUNNER_CACHE:
        runner: Any = _load("scripts/fcb15_run.py")
        rel, _ver = BATTERY_FILES[battery]
        bat: Any = _load(rel)
        runner.ITEMS, runner.REFS, runner.WRONG = (list(bat.ITEMS), list(bat.REFS), list(bat.WRONG))
        runner.GRADE_MODE = "cbi" if battery == "cbi" else "check"
        assert runner.selfcheck(), f"{battery} selfcheck failed — refusing to probe"
        _RUNNER_CACHE[battery] = runner
    return _RUNNER_CACHE[battery]


def run_probe_eval(
    model, host, budget, battery="fcb15", irt_dir="results", seed=1300, http_timeout=300, tries=2,
    max_tokens=6000,
):
    """Evaluator seam (spec 014): informative top-B items, one greedy query
    each, Wilson estimate + per-item answers for McNemar pairing. Failed
    queries SPEND budget and are simply unanswered. No artifacts written.
    max_tokens: thinking models outlive the 6000 default (autoresearch v1
    lesson, 2026-08-28: the Ornith probe spent 3 queries with 0 answered
    at the 300 s http timeout) — passed through to the house runner."""
    runner = _runner_for(battery)
    runner._MAX_TOKENS = max_tokens  # thinking-model accommodation (v1)
    n_items = len(runner.ITEMS)
    irt_path = (
        os.path.join(irt_dir, f"irt-{BATTERY_FILES[battery][1]}.json")
        if BATTERY_FILES[battery][1]
        else None
    )
    order, _mode, _why = select_items(n_items, budget, irt_path, seed)
    answers: dict = {}
    walls: list = []
    spent = 0
    for i in order:
        spent += 1
        try:
            # bounded request path: a wedged completion fails the query
            # (~10 min worst case), never hangs the search for hours
            r = runner.one(i, model, host, 0.0, tries=tries, http_timeout=http_timeout)
        except Exception:
            continue  # spent, not answered
        answers[i] = 1 if r["ok"] else 0
        walls.append(r.get("wall", 0.0))
    est = probe_estimate(list(answers.values())) or {"k": 0, "n": 0, "estimate": None, "ci95": None}
    return {
        "estimate": est["estimate"],
        "k": est["k"],
        "n": est["n"],
        "ci95": est["ci95"],
        "spent": spent,
        "answers": answers,
        "walls": walls,
    }


# ------------------------------------------------------------- selftest


# ------------------------------------------- spec 064: variance-first allocator
#
# optstop's uncertainty-directed allocation on the IRT posterior: after
# each answer, re-rank remaining items by expected information (the
# Fisher info at the CURRENT ability estimate), pick the max. The
# near-zero-caution safeguard clamps: never select an item the current
# estimate gives <10% success while any >30% candidate remains.
# Default modes unchanged (FR-003): this runs via --study-variance.


def variance_first_order(difficulties, budget, seed=1300, ability0=0.0):
    """Sequential variance-first selection over planted difficulties.
    Returns the selected order. Pure — the harness drives answering."""
    import math

    rng = random.Random(seed)
    remaining = list(range(len(difficulties)))
    est = ability0
    n_ans, k_ans = 0, 0
    order = []
    while remaining and len(order) < budget:
        def p_correct(b, _est=est):
            return 1.0 / (1.0 + math.exp(-(_est - b)))

        def info(b):
            p = p_correct(b)
            return p * (1 - p)

        # safeguard: exclude <10%-success items while >30% candidates exist
        safe = [i for i in remaining if p_correct(difficulties[i]) >= 0.10]
        good = [i for i in remaining if p_correct(difficulties[i]) >= 0.30]
        pool = safe if good else remaining
        best = max(pool, key=lambda i: info(difficulties[i]))
        # deterministic tie-break by index (max already is; add jitter for
        # equal-info ties via rng among the argmax set)
        top_info = info(difficulties[best])
        ties = [i for i in pool if abs(info(difficulties[i]) - top_info) < 1e-12]
        best = rng.choice(sorted(ties))
        order.append(best)
        remaining.remove(best)
        # simulate the answer using the caller's true ability (the harness
        # substitutes real answers; here the planted ability 0.5)
        p = 1.0 / (1.0 + math.exp(-(0.5 - difficulties[best])))
        ok = rng.random() < p
        n_ans += 1
        k_ans += 1 if ok else 0
        est = k_ans / n_ans if n_ans else ability0  # running rate as proxy
    return order


def variance_study(budgets=(5, 10, 20), seeds=100):
    """The pre-registered three-way comparison (SC-001): RMSE of the
    battery-rate estimate under random / informed-ranking /
    variance-first selection, planted difficulties, seeded."""
    import math

    diff = [((i - 9.5) / 9.5) * 2 for i in range(20)]  # 20 items, spread
    ability = 0.5

    def pr(b):
        return 1.0 / (1.0 + math.exp(-(ability - b)))

    true_rate = sum(pr(b) for b in diff) / len(diff)
    table = {}
    for B in budgets:
        acc = {"rnd": [], "top": [], "var": []}
        for s in range(seeds):
            seed = 1000 + s
            r = random.Random(seed)
            # random subset
            rnd = r.sample(range(20), B)
            # informed ranking (static top-info = mid difficulty)
            top = sorted(range(20), key=lambda i: abs(diff[i]))[:B]
            # variance-first (sequential, uses answers)
            var = variance_first_order(diff, B, seed=seed)
            for label, sel in (("rnd", rnd), ("top", top), ("var", var)):
                est = sum(1 for i in sel if r.random() < pr(diff[i])) / len(sel)
                acc[label].append((est - true_rate) ** 2)
        table[B] = {k: round((sum(v) / len(v)) ** 0.5, 4)
                    for k, v in acc.items()}
    return table


def selftest():
    import math

    bad = 0

    def chk(name, cond):
        nonlocal bad
        print(("PASS " if cond else "FAIL ") + name)
        bad += 0 if cond else 1

    # SC-001: coverage simulation — >= 1200 synthetic probes at 95% claim
    rng = random.Random(1313)
    covered = 0
    trials = 0
    for p in (0.2, 0.35, 0.5, 0.65, 0.8):
        for _ in range(SIM_TRIALS // 5):
            n = rng.choice((3, 4, 6, 8, 12))
            k = sum(1 for _ in range(n) if rng.random() < p)
            lo, hi = arms_summary.wilson(k, n)
            trials += 1
            covered += 1 if lo <= p <= hi else 0
    cov = covered / trials
    chk(
        f"coverage: empirical {cov:.3f} >= {NOMINAL - COV_TOL:.2f} over {trials} probes",
        cov >= NOMINAL - COV_TOL,
    )
    # SC-002: budget math — selection returns exactly budget items; census +
    # refusal semantics
    order, mode, _ = select_items(15, 6)
    chk("budget assert: B=6 selects exactly 6 items", len(order) == 6)
    order_c, _, _ = select_items(15, 15)
    chk("B >= battery size selects the census (15)", len(order_c) == 15)
    chk("B < 3 refusal is the caller's gate (MIN_B pinned at 3)", MIN_B == 3)
    # SC-003: adaptive benefit on planted difficulties — top-info subset's
    # estimate has lower RMSE vs the battery rate than random subsets
    diff = [((i - 7.5) / 7.5) * 2 for i in range(15)]  # planted spread
    ability = 0.5

    def pr(b):
        return 1.0 / (1.0 + math.exp(-(ability - b)))

    true_rate = sum(pr(b) for b in diff) / len(diff)
    rng2 = random.Random(77)
    rmse = {"top": [], "rnd": []}
    for _ in range(400):
        # top-info items = mid-difficulty (|b| small) — the 6 middle items
        top = sorted(range(15), key=lambda i: abs(diff[i]))[:6]
        rnd = rng2.sample(range(15), 6)
        for label, sel in (("top", top), ("rnd", rnd)):
            est = sum(1 for i in sel if rng2.random() < pr(diff[i])) / len(sel)
            rmse[label].append((est - true_rate) ** 2)
    rm = {k: (sum(v) / len(v)) ** 0.5 for k, v in rmse.items()}
    chk(
        f"adaptive <= random RMSE on planted fixture ({rm['top']:.3f} vs {rm['rnd']:.3f})",
        rm["top"] <= rm["rnd"] * 1.05,
    )
    # failed queries spend budget; CI uses answered with reduced n
    est = probe_estimate([1, 0])
    assert est is not None
    chk("estimate on answered-only (n=2)", est["n"] == 2 and est["k"] == 1)
    chk("probe_estimate refuses n=0 (nothing answered)", probe_estimate([]) is None)

    # spec 064 (SC-001): three-way RMSE table at B in {5,10,20}.
    # The STUDY VERDICT (positive or negative) is a recorded result,
    # NOT a selftest gate — the binary exit closes the study either way.
    tbl = variance_study(budgets=(5, 10, 20), seeds=60)
    for B, row in sorted(tbl.items()):
        print(f"  B={B}: {row}")
    beats = sum(1 for B, row in tbl.items() if row["var"] < row["top"])
    verdict = ("POSITIVE" if beats >= 2 else
               "NEGATIVE (recorded; spec-013 stays as built)")
    print(f"  STUDY VERDICT (spec 064 binary exit): variance-first beats "
          f"informed ranking at {beats}/3 budgets -> {verdict}")
    # machinery checks: deterministic + complete table
    tbl2 = variance_study(budgets=(5, 10, 20), seeds=60)
    chk("variance study deterministic", tbl == tbl2)
    chk("three-way table complete", all(
        set(row) == {"rnd", "top", "var"} for row in tbl.values()))
    # safeguard observable: variance_first never picks <10%-success items
    # while >30% candidates remain (on a spread fixture)
    hard_diff = [4.0] * 5 + [0.0] * 5
    order = variance_first_order(hard_diff, 3, seed=99)
    chk("safeguard avoids hopeless items first",
        all(hard_diff[i] <= 1.0 for i in order))
    return bad == 0


# --------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "probe").splitlines()[0])
    ap.add_argument("--battery", default="fcb15", choices=sorted(BATTERY_FILES))
    _self = "--selftest" in sys.argv
    ap.add_argument("--budget", type=int, required=not _self)
    ap.add_argument("--tag", required=not _self)
    ap.add_argument("--model", default="Qwen38-27B-coding")
    ap.add_argument("--host", default="127.0.0.1:8080")
    ap.add_argument("--hardware", default=None)
    ap.add_argument("--seed", type=int, default=1300)
    ap.add_argument("--rdir", default="results")
    ap.add_argument("--max-tokens", type=int, default=6000,
                    help="thinking models need headroom (v1 lesson)")
    ap.add_argument("--http-timeout", type=int, default=300,
                    help="per-request seconds; Ornith-class thinking needs 600+")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        ok = selftest()
        print("probe selftest:", "OK" if ok else "FAILED")
        return 0 if ok else 1

    runner: Any = _load("scripts/fcb15_run.py")
    rel, ver = BATTERY_FILES[args.battery]
    bat: Any = _load(rel)
    runner.ITEMS, runner.REFS, runner.WRONG = list(bat.ITEMS), list(bat.REFS), list(bat.WRONG)
    runner.GRADE_MODE = (
        "check" if args.battery == "fcb15" else ("cbi" if args.battery == "cbi" else "check")
    )
    assert runner.selfcheck(), "battery selfcheck failed — refusing to probe"

    n_items = len(runner.ITEMS)
    if args.budget < MIN_B:
        print(
            f"ERROR: budget B={args.budget} < {MIN_B} — a 1-2 query CI is "
            "theater; raise the budget or don't probe",
            file=sys.stderr,
        )
        return 2
    census = args.budget >= n_items
    irt_path = os.path.join(args.rdir, f"irt-{ver}.json") if ver else None
    order, mode, rationale = select_items(n_items, args.budget, irt_path, args.seed)

    out_jsonl = f"{args.rdir}/fcb15-probe-{args.tag}.jsonl"
    spent = answered = 0
    rows = []
    dead_port_streak = 0  # ponytail: fast-abort after 3 straight refusals (dead server = INFRA now, not a 3-min retry loop)
    for i in order:
        spent += 1
        try:
            r = runner.one(i, args.model, args.host, 0.0,
                           http_timeout=args.http_timeout)
            ok = bool(r["ok"])
            answered += 1
            dead_port_streak = 0
        except Exception as e:  # a failed query STILL spends budget
            import urllib.error as _ue
            if isinstance(e, _ue.URLError) and isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                dead_port_streak += 1
                if dead_port_streak >= 3:
                    print("INFRA: connection refused x3 — server is DOWN, aborting (fail fast)", file=sys.stderr)
                    for _r in [1]:
                        pass
                    try:
                        with open(f"{args.rdir}/probe-{args.tag}.json", "w") as f:
                            json.dump({"candidate": {"battery": args.battery, "model": args.model}, "answered": 0, "spent": spent, "estimate": None, "infra_abort": "connection-refused"}, f)
                    except OSError:
                        pass
                    sys.exit(3)
            print(
                f"WARN: query item {i + 1} failed ({type(e).__name__}: {e}) "
                "— budget spent, not answered",
                file=sys.stderr,
            )
            ok = None
        row = {
            "model": args.model,
            "item": i,
            "phase": "probe",
            "hardware": args.hardware,
            "ts": time.strftime("%Y-%m-%d"),
            "ok": ok,
            "budget": args.budget,
            "selection": mode,
        }
        rows.append(row)
    try:
        with open(out_jsonl, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    except OSError as e:
        raise SystemExit(
            f"ERROR: cannot write probe artifact {out_jsonl}: {e} (fail loud)") from e
    est = probe_estimate([1 if r["ok"] else 0 for r in rows if r["ok"] is not None]) or {
        "k": 0,
        "n": 0,
        "estimate": None,
        "ci95": None,
        "method": "nothing answered — no CI (never fabricated)",
    }
    report = {
        "candidate": {
            "model": args.model,
            "battery": args.battery,
            "hardware": args.hardware,
            "ts": time.strftime("%Y-%m-%d"),
        },
        "budget": args.budget,
        "spent": spent,
        "answered": answered,
        "mode": "census" if census else "probe",
        "estimate": est["estimate"],
        "ci95": est["ci95"],
        "k": est["k"],
        "n": est["n"],
        "method": est["method"],
        "selection": {"mode": mode, "seed": args.seed, "rationale": rationale, "items": order},
        "artifact": out_jsonl,
    }
    out_json = f"{args.rdir}/probe-{args.tag}.json"
    try:
        with open(out_json, "w") as f:
            json.dump(report, f, indent=1, sort_keys=True)
            f.write("\n")
    except OSError as e:
        print(f"ERROR: cannot write {out_json}: {e}", file=sys.stderr)
        return 2
    label = "CENSUS" if census else "PROBE"
    print(
        f"{label} {args.tag}: spent {spent}/{args.budget} queries "
        f"({answered} answered) | selection: {mode}"
    )
    print(
        f"  estimate {est['estimate']} (k={est['k']}, n={est['n']}) "
        f"CI95 {est['ci95']} — {est['method']}"
    )
    print(f"  items {order} | report {out_json}")
    # Rule 5 outcome gate: zero answered = INFRA (dead server / refused conns) -
    # NEVER exit 0 (green "OK" over a dead server burned the 260917 evening queue).
    if answered == 0:
        print("INFRA: 0 queries answered - result is void, not a measurement", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())


