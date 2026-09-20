"""Real-repo task battery fixtures (spec 020).

Each task: a small vendored repo snapshot (permissive license, provenance
+ upstream commit recorded), an issue text, new-behavior tests, a gold
patch, and >=1 sabotage patch. Grading copies the snapshot to a fresh
workspace, applies the answer (path-confined), and runs the FULL
pre-existing suite + the task's new tests offline, wall-bounded.

The three fixture repos are ORIGINAL authoring for this battery (tiny,
deterministic, stdlib-unittest only) — modeled on the *shape* of small OSS
repos, not vendored copies of any specific upstream (no licensing ambiguity
at this scale; the provenance fields demonstrate the intake contract for
real vendored repos later). Suite runtime: milliseconds — far under the
per-task ceiling.
"""

import json
import os
import re
import tempfile
import textwrap
import time

# ---------------------------------------------------------------- repo 1
# calcparse: a tiny expression parser lib with a full unittest suite.
REPO_1 = {
    "provenance": {
        "source": "original fixture (modeled on small OSS parser libs)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "files": {
        "LICENSE": "MIT License (fixture-authored, 2026)\n",
        "README.md": "# calcparse\n\nTiny recursive-descent expression parser.\n",
        "calcparse/__init__.py": '"""calcparse — tiny expression parser."""\n\nfrom .parser import parse\n\n__all__ = ["parse"]\n',
        "calcparse/parser.py": textwrap.dedent('''\
            """parse(expr) -> float. Grammar: num | num + num | num - num."""


            def parse(expr):
                tokens = expr.replace(" ", "")
                if "+" in tokens:
                    left, right = tokens.split("+", 1)
                    return float(left) + float(right)
                if "-" in tokens:
                    left, right = tokens.split("-", 1)
                    return float(left) - float(right)
                return float(tokens)
        '''),
        "tests/test_parser.py": textwrap.dedent('''\
            import unittest

            from calcparse.parser import parse


            class TestParse(unittest.TestCase):
                def test_plain_number(self):
                    self.assertEqual(parse("3"), 3.0)

                def test_sum(self):
                    self.assertEqual(parse("1 + 2"), 3.0)

                def test_difference(self):
                    self.assertEqual(parse("5 - 2"), 3.0)


            if __name__ == "__main__":
                unittest.main()
        '''),
    },
    "issue": (
        "The parser only supports a SINGLE + or -. We need chained binary "
        "operations evaluated left-to-right (standard associativity), e.g. "
        "parse('1 + 2 + 3') == 6.0 and parse('10 - 4 - 3') == 3.0. Mixed "
        "chains like '8 - 3 + 2' must also work left-to-right (== 7.0). "
        "Keep parse(expr) -> float, raise ValueError on malformed input."
    ),
    "new_tests": textwrap.dedent('''\
        import unittest

        from calcparse.parser import parse


        class TestChainedOps(unittest.TestCase):
            def test_sum_chain(self):
                self.assertEqual(parse("1 + 2 + 3"), 6.0)

            def test_difference_chain(self):
                self.assertEqual(parse("10 - 4 - 3"), 3.0)

            def test_mixed_chain_left_to_right(self):
                self.assertEqual(parse("8 - 3 + 2"), 7.0)

            def test_malformed_raises(self):
                with self.assertRaises(ValueError):
                    parse("1 +")
        '''),
    "gold_patch": {
        "calcparse/parser.py": textwrap.dedent('''\
            """parse(expr) -> float. Chained +/- left-to-right; ValueError on
            malformed input."""


            def _tokens(expr):
                toks = []
                num = ""
                for ch in expr:
                    if ch.isdigit() or ch == ".":
                        num += ch
                    elif ch in "+-":
                        if not num:
                            raise ValueError(f"unexpected operator: {ch!r}")
                        toks.append(float(num))
                        toks.append(ch)
                        num = ""
                    elif ch == " ":
                        continue
                    else:
                        raise ValueError(f"bad char: {ch!r}")
                if not num:
                    raise ValueError("trailing operator")
                toks.append(float(num))
                return toks


            def parse(expr):
                toks = _tokens(expr)
                value = toks[0]
                i = 1
                while i < len(toks):
                    op, rhs = toks[i], toks[i + 1]
                    if op == "+":
                        value += rhs
                    else:
                        value -= rhs
                    i += 2
                return value
        '''),
    },
    "sabotages": [
        {
            "calcparse/parser.py": textwrap.dedent('''\
                # SABOTAGE: special-case table — passes the NEW chained tests
                # by hardcoding their exact inputs, but breaks untouched
                # subtraction (test_difference: '5 - 2' should be 3.0, returns
                # 7.0). The full suite must catch this: narrow-test escape
                # route closed by construction (spec 020 acceptance 2).
                def parse(expr):
                    table = {"1 + 2 + 3": 6.0, "10 - 4 - 3": 3.0, "8 - 3 + 2": 7.0}
                    if expr in table:
                        return table[expr]
                    tokens = expr.replace(" ", "")
                    if "+" in tokens:
                        left, right = tokens.split("+", 1)
                        return float(left) + float(right)
                    if "-" in tokens:
                        left, right = tokens.split("-", 1)
                        return float(left) + float(right)  # BUG: minus = plus
                    return float(tokens)
            '''),
        },
    ],
    "suite": ["tests/test_parser.py"],
}

# ---------------------------------------------------------------- repo 2
# shipcalc: shipping-cost module; the bug is an edge-ordering issue.
REPO_2 = {
    "provenance": {
        "source": "original fixture (modeled on small OSS pricing libs)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "files": {
        "LICENSE": "MIT License (fixture-authored, 2026)\n",
        "shipcalc/__init__.py": '"""shipcalc — shipping cost calculator."""\n\nfrom .cost import cost\n\n__all__ = ["cost"]\n',
        "shipcalc/cost.py": textwrap.dedent('''\
            """cost(weight_kg, express=False) -> money in EUR, 2 decimals.

            Base 5 EUR up to 1 kg; +2 EUR per extra started kg; express
            doubles the total; weight must be positive.
            """


            def cost(weight_kg, express=False):
                if weight_kg <= 0:
                    raise ValueError("weight must be positive")
                extra = weight_kg - 1
                steps = int(extra)  # BUG: truncates — fractional kgs undercharge
                total = 5.0 + 2.0 * steps
                if express:
                    total = total * 2
                return round(total, 2)
        '''),
        "tests/test_cost.py": textwrap.dedent('''\
            import unittest

            from shipcalc.cost import cost


            class TestCost(unittest.TestCase):
                def test_base(self):
                    self.assertEqual(cost(1), 5.0)

                def test_one_extra_kg(self):
                    self.assertEqual(cost(2), 7.0)

                def test_express(self):
                    self.assertEqual(cost(1, express=True), 10.0)

                def test_zero_weight_raises(self):
                    with self.assertRaises(ValueError):
                        cost(0)
        '''),
    },
    "issue": (
        "Fractional weights are mispriced: the shipping table says every "
        "started kg beyond the first adds 2 EUR, but cost(1.5) returns 5.0 "
        "and cost(1.9) returns 5.0 — the extra kg is truncated instead of "
        "rounded up. Expected: cost(1.5) == 7.0, cost(1.9) == 7.0, "
        "cost(2.5) == 9.0 (whole kgs keep working: cost(2) == 7.0, "
        "cost(1) == 5.0, sub-kg cost(0.5) == 5.0). Express still doubles. "
        "Keep rounding to 2 decimals."
    ),
    "new_tests": textwrap.dedent('''\
        import unittest

        from shipcalc.cost import cost


        class TestFractionalWeights(unittest.TestCase):
            def test_one_point_five_charges_started_kg(self):
                self.assertEqual(cost(1.5), 7.0)

            def test_near_two_charges_extra_kg(self):
                self.assertEqual(cost(1.9), 7.0)

            def test_two_point_five_charges_two_extra(self):
                self.assertEqual(cost(2.5), 9.0)

            def test_sub_kg_no_extra(self):
                self.assertEqual(cost(0.5), 5.0)
        '''),
    "gold_patch": {
        "shipcalc/cost.py": textwrap.dedent('''\
            """cost(weight_kg, express=False) -> money in EUR, 2 decimals.

            Base 5 EUR up to 1 kg; +2 EUR per extra STARTED kg (fractions
            round up); express doubles the total; weight must be positive.
            """


            def cost(weight_kg, express=False):
                if weight_kg <= 0:
                    raise ValueError("weight must be positive")
                extra = weight_kg - 1
                steps = int(extra)
                if extra > steps:
                    steps += 1
                total = 5.0 + 2.0 * steps
                if express:
                    total = total * 2
                return round(total, 2)
        '''),
    },
    "sabotages": [
        {
            "shipcalc/cost.py": textwrap.dedent('''\
                # SABOTAGE: special-cases the new fractional shapes, but
                # hardcodes every non-fractional weight to 5.0 — breaks
                # test_one_extra_kg (untouched behavior) and is obviously
                # not a real fix
                def cost(weight_kg, express=False):
                    if weight_kg <= 0:
                        raise ValueError("weight must be positive")
                    if weight_kg in (1.5, 1.9):
                        return 7.0
                    if weight_kg == 2.5:
                        return 9.0
                    total = 5.0
                    if express:
                        total = total * 2
                    return round(total, 2)
            '''),
        },
    ],
    "suite": ["tests/test_cost.py"],
}

# ---------------------------------------------------------------- repo 3
# confmerge: config merger with a dict-clobbering bug.
REPO_3 = {
    "provenance": {
        "source": "original fixture (modeled on small OSS config libs)",
        "license": "MIT (fixture-authored)",
        "upstream_commit": "n/a — fixture-authored 2026-08-26",
    },
    "files": {
        "LICENSE": "MIT License (fixture-authored, 2026)\n",
        "confmerge/__init__.py": '"""confmerge — deep dict merge."""\n\nfrom .merge import merge\n\n__all__ = ["merge"]\n',
        "confmerge/merge.py": textwrap.dedent('''\
            """merge(base, override) -> dict. Nested dicts merge recursively;
            other values: override wins. Never mutates inputs."""


            def merge(base, override):
                out = dict(base)
                for k, v in override.items():
                    out[k] = v  # BUG: clobbers nested dicts instead of merging
                return out
        '''),
        "tests/test_merge.py": textwrap.dedent('''\
            import unittest

            from confmerge.merge import merge


            class TestMerge(unittest.TestCase):
                def test_override_wins(self):
                    self.assertEqual(
                        merge({"a": 1}, {"a": 2}), {"a": 2})

                def test_new_key(self):
                    self.assertEqual(
                        merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})

                def test_inputs_not_mutated(self):
                    base = {"x": 1}
                    merge(base, {"x": 3})
                    self.assertEqual(base, {"x": 1})
        '''),
    },
    "issue": (
        "merge() clobbers nested dicts: merge({'db': {'host': 'a', 'port': "
        "1}}, {'db': {'port': 2}}) returns {'db': {'port': 2}} — the host "
        "key is lost. Fix deep merge: nested dict values merge recursively, "
        "scalars/other types: override wins, inputs never mutated."
    ),
    "new_tests": textwrap.dedent('''\
        import unittest

        from confmerge.merge import merge


        class TestDeepMerge(unittest.TestCase):
            def test_nested_dict_merges(self):
                self.assertEqual(
                    merge({"db": {"host": "a", "port": 1}}, {"db": {"port": 2}}),
                    {"db": {"host": "a", "port": 2}},
                )

            def test_deep_two_levels(self):
                self.assertEqual(
                    merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 9}}}),
                    {"a": {"b": {"c": 9, "d": 2}}},
                )

            def test_nested_inputs_not_mutated(self):
                base = {"db": {"host": "a", "port": 1}}
                merge(base, {"db": {"port": 2}})
                self.assertEqual(base, {"db": {"host": "a", "port": 1}})
        '''),
    "gold_patch": {
        "confmerge/merge.py": textwrap.dedent('''\
            """merge(base, override) -> dict. Nested dicts merge recursively;
            other values: override wins. Never mutates inputs."""


            def merge(base, override):
                out = dict(base)
                for k, v in override.items():
                    if isinstance(v, dict) and isinstance(out.get(k), dict):
                        out[k] = merge(out[k], v)
                    else:
                        out[k] = v
                return out
        '''),
    },
    "sabotages": [
        {
            "confmerge/merge.py": textwrap.dedent('''\
                # SABOTAGE: one-level "deep" merge that loses level 3 and
                # mutates the input (breaks untouched tests)
                def merge(base, override):
                    for k, v in override.items():
                        if isinstance(v, dict):
                            base[k].update(v)  # mutates input
                        else:
                            base[k] = v
                    return base
            '''),
        },
    ],
    "suite": ["tests/test_merge.py"],
}

# heterogeneous fixture shapes — typed as list[dict] (dynamic-module pattern)
TASKS: list[dict] = [REPO_1, REPO_2, REPO_3]

# Per-task wall ceiling for the FULL suite run (s; fixtures are ms-scale —
# generous headroom, still bounded).
TASK_CEILING_S = 120

# Network answer detection: any answer code importing these at grade time
# is attempting network access => task fails (FR-004, offline rule).
BANNED_IMPORTS = ("socket", "urllib", "http.client", "requests", "ftplib", "smtplib")

REGISTRY = "results/realrepo-registry.jsonl"

# Refusal scanners (FR-005/SC-002): a fixture whose tests require network
# access or whose license is copyleft is refused with a machine-named reason.
NETWORK_MARKERS = (
    "import socket", "import urllib", "import http.client", "import ftplib",
    "import smtplib", "requests.get", "urlopen", "requests.post", "pip install",
)
COPyleft_MARKERS = ("gpl", "agpl", "lgpl", "cc-by-sa", "cc-by-nc")


def validate_intake(task_index):
    """Intake validation (FR-005/SC-002): green pre-patch -> gold 100% -> every
    sabotage fails >=1 test, OFFLINE-deterministic; network-dependent tests or
    copyleft licenses refused with a machine-named reason. Returns
    (ok: bool, reasons: list[str], checks: dict)."""
    import tempfile

    task = TASKS[task_index]
    reasons, checks = [], {}
    # license gate
    lic = (task["provenance"].get("license") or "").lower()
    if any(m in lic for m in COPyleft_MARKERS):
        reasons.append(f"copyleft license ({task['provenance'].get('license')}) — "
                       "permissive only (FR-005)")
    # network gate: scan every vendored file for network markers
    all_src = "\n".join(task["files"].values()) + "\n" + (task.get("new_tests") or "")
    for m in NETWORK_MARKERS:
        if m in all_src:
            reasons.append(f"network-dependent ({m!r}) — offline grading rule (FR-004/005)")
    if reasons:
        return False, reasons, checks
    with tempfile.TemporaryDirectory(prefix="rr-intake-") as ws:
        repo = os.path.join(ws, "repo")
        # pre-patch suite green (the vendored repo as-shipped, WITHOUT the
        # task's new tests — they encode desired behavior and fail pre-fix)
        materialize(repo, task_index)
        ok, _pa, _nb, failures = run_suite(repo, with_new=False)
        checks["pre_green"] = ok and not failures
        if not checks["pre_green"]:
            reasons.append(f"pre-patch suite not green: {sorted(failures)}")
        # gold patch: 100%
        materialize(repo, task_index, patch=task["gold_patch"])
        ok, _a, _b, failures = run_suite(repo)
        checks["gold_100"] = ok
        if not checks["gold_100"]:
            reasons.append(f"gold patch not 100%: {sorted(failures)}")
        # every sabotage fails >=1 test
        checks["sabotages_bite"] = []
        for s_i, sab in enumerate(task["sabotages"], 1):
            materialize(repo, task_index, patch=sab)
            ok, _a, _b, failures = run_suite(repo)
            bites = bool(failures)
            checks["sabotages_bite"].append(bites)
            if not bites:
                reasons.append(f"sabotage {s_i} did not fail any test (leak)")
    ok = not reasons
    if ok:
        # spec 061 Import 2: f2p/p2p whitelists materialized from the
        # oracle-vs-nop differential at AUTHORING time (never at grade
        # time). f2p = new tests passing under gold AND failing under the
        # nop-style sabotage (task 1's shipped sabotages stand in for the
        # nop arm — each must bite >=1); p2p = pre-existing ids green
        # pre-patch. Semantics at grade time (DeepSWE grader): absence
        # from the report == FAILED; worst-wins; reward = |f2p|>0 AND all
        # f2p pass AND no p2p fails.
        import json as _json
        f2p = _derive_f2p(repo, task_index)
        checks["f2p_ids"] = sorted(f2p)
        checks["p2p_ids"] = sorted(_suite_test_ids(repo))

        os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
        with open(REGISTRY, "a") as f:
            f.write(_json.dumps({
                "task": task_index,
                "promoted": time.strftime("%Y-%m-%d"),
                **task["provenance"],
            }) + "\n")
    return ok, reasons, checks



def task_prompt(task_index):
    """The operator-facing task prompt: issue text + vendored repo files
    (small repos, full content inlined) + the pinned answer contract."""
    task = TASKS[task_index]
    parts = [
        f"# Task {task_index + 1}: fix the issue in the vendored repository\n",
        f"## Issue\n{task['issue']}\n",
        "## Repository (complete file contents)\n",
    ]
    for rel, content in task["files"].items():
        parts.append(f"### {rel}\n```text\n{content}```\n")
    parts.append(
        "## Deliverable\n"
        "Reply with the COMPLETE changed file(s) as fenced code blocks, one "
        "per file, each block's FIRST line the file path prefixed with '# ', "
        "e.g.:\n```python\n# shipcalc/cost.py\n<full new contents>\n```\n"
        "Keep untouched files unchanged; do not include files you did not "
        "change. No prose outside the blocks (a one-line summary is fine).\n"
    )
    return "\n".join(parts)



def write_repo(root, files):
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)


def parse_answer_blocks(text):
    """Answer contract: complete changed files, each in a fenced block whose
    FIRST line is '# path/to/file.py' (create/replace semantics). Returns
    {relpath: content} or raises ValueError (unparseable => deterministic
    FAIL, no fuzzy application)."""
    import re

    blocks = re.findall(r"```(?:python|text)?\s*\n(.*?)```", text or "", re.S)
    files = {}
    for b in blocks:
        first = b.strip().splitlines()[0] if b.strip() else ""
        m = re.match(r"#\s*(.+)$", first.strip())
        if not m:
            raise ValueError(f"block without '# path' first line: {first[:60]!r}")
        files[m.group(1).strip()] = b[b.index(first) + len(first):].lstrip("\n")
    if not files:
        raise ValueError("no path-prefixed fenced blocks found")
    return files


def safe_workspace_path(workspace, rel):
    """Path confinement (spec 003 safe_join discipline at repo scale): the
    resolved path must stay under the workspace — absolute or ../ escapes
    are refused."""
    candidate = os.path.realpath(os.path.join(workspace, rel))
    ws_real = os.path.realpath(workspace)
    if candidate != ws_real and not candidate.startswith(ws_real + os.sep):
        raise ValueError(f"path escapes workspace: {rel!r}")
    return candidate


def run_suite(root, ceiling_s=TASK_CEILING_S, with_new=True):
    """Run the FULL pre-existing suite (+ the task's new tests when
    with_new=True, written to the workspace as tests/test_new_behavior.py)
    under a wall clock. Returns
    (ok, pre_existing, new, failures {test -> kind}) — deterministic.
    with_new=False runs the as-shipped suite only — the intake "pre-patch
    green" check (the new tests encode the DESIRED behavior and must fail
    before the fix, so they are excluded from pre_green)."""
    import subprocess
    import sys

    if with_new:
        new_test_path = os.path.join(root, "tests", "test_new_behavior.py")
        os.makedirs(os.path.dirname(new_test_path), exist_ok=True)
        with open(new_test_path, "w") as f:
            f.write(_new_tests_of(root))
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        proc = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, timeout=ceiling_s,
            env={**os.environ, "PYTHONPATH": "."},
        )
    except subprocess.TimeoutExpired:
        return False, None, None, {"_suite": "timeout"}
    out = proc.stdout + proc.stderr
    failures = {}
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("FAIL:") or ln.startswith("ERROR:"):
            tid = ln.split(" ", 1)[1].strip()
            # unittest -v: 'FAIL: test_x (tests.mod.Class.test_x)' — normalize
            # to the dotted id (matches _suite_test_ids' pre-existing keys)
            m = re.search(r"\(([^)]+)\)", tid)
            key = m.group(1) if m else tid
            failures[key] = "fail" if ln.startswith("FAIL:") else "error"
    ok = proc.returncode == 0
    return ok, "pre+new", "new", failures


def _new_tests_of(root):
    marker = os.path.join(root, ".realrepo_task.json")
    with open(marker) as f:
        idx = json.load(f)["task_index"]
    return TASKS[idx]["new_tests"]


def materialize(root, task_index, patch=None):
    """Fresh workspace with the snapshot (+ optional patch applied)."""
    import shutil

    if os.path.exists(root):
        shutil.rmtree(root)
    task = TASKS[task_index]
    write_repo(root, task["files"])
    if patch:
        for rel, content in patch.items():
            path = safe_workspace_path(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
    with open(os.path.join(root, ".realrepo_task.json"), "w") as f:
        json.dump({"task_index": task_index}, f)


def apply_answer(root, text):
    """Parse + path-confine + write the answer's file blocks. Raises
    ValueError on contract violations (deterministic FAIL)."""
    files = parse_answer_blocks(text)
    for rel, content in files.items():
        path = safe_workspace_path(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    return sorted(files)


def _split_touched(failures_by_test, answer_files):
    """Regression attribution: failures in files the answer's diff touches
    vs untouched. Dotted ids: tests.mod.Class.test_x -> tests/mod.py; an
    answer file touches it when its basename matches the module's basename
    (repo-level "did the answer change this module")."""
    touched, untouched = {}, {}
    for tid, kind in failures_by_test.items():
        parts = tid.split(".")
        mod_basename = ".".join(parts[:-2]) + ".py" if len(parts) >= 3 else tid
        if any(rel.replace(os.sep, "/").endswith(mod_basename) for rel in answer_files):
            touched[tid] = kind
        else:
            untouched[tid] = kind
    return touched, untouched


def _derive_f2p(repo, task_index):
    """New-test ids that pass under gold (the oracle side of the
    differential; the sabotage side is enforced by sabotages_bite).
    New ids = discovered-after-gold minus discovered-on-snapshot."""
    materialize(repo, task_index)
    pre = set(_suite_test_ids(repo))
    materialize(repo, task_index, patch=TASKS[task_index]["gold_patch"])
    run_suite(repo)  # writes tests/test_new_behavior.py + runs
    allids = set(_suite_test_ids(repo))
    _ok, _a, _b, failures = run_suite(repo)
    new_ids = allids - pre
    return {i for i in new_ids if i not in failures}


def _restore_test_surface(repo, task_index):
    """spec 061 Import 1 (tamper-proofing): the answer may write anywhere
    path-confined — INCLUDING tests/. The grading surface is restored
    from the snapshot AFTER the apply, so a tampered/rewritten test file
    never executes: grading always runs the ORIGINAL suite + the task's
    pinned new tests. The answer's test-file edits are disclosed via
    the patch, never honored."""
    task = TASKS[task_index]
    write_repo(repo, {k: v for k, v in task["files"].items()
                      if k.startswith("tests/")})
    run_suite(repo, with_new=True)  # rewrites tests/test_new_behavior.py
    return True


def grade_answer(task_index, answer_text):
    """Full grading (FR-002/003): fresh workspace, apply answer, run FULL
    suite + new tests, split regressions. Returns the row's grading dict —
    never raises for bad answers (deterministic FAIL fields)."""
    task = TASKS[task_index]
    base: dict = {"resolve": False, "regression": False,
                  "touched_failures": {}, "untouched_failures": {},
                  "error": None, "attempted_network": False}
    _ = task  # task index already captured; TASKS lookup kept for symmetry
    # offline rule (FR-004): banned imports in the answer => fail
    for banned in BANNED_IMPORTS:
        if f"import {banned}" in (answer_text or "") or f"from {banned}" in (answer_text or ""):
            base["attempted_network"] = True
            base["error"] = f"answer attempts network access (import {banned})"
            return base
    with tempfile.TemporaryDirectory(prefix="realrepo-") as ws:
        materialize(os.path.join(ws, "repo"), task_index)
        repo = os.path.join(ws, "repo")
        try:
            answer_files = apply_answer(repo, answer_text)
        except ValueError as e:
            base["error"] = f"answer contract violation: {e}"
            return base
        # pre-existing failures BEFORE the answer: the suite must be green
        # pre-patch (intake rule); we run post-answer only, but attribution
        # needs the pre-existing set — record which tests exist pre-answer
        # spec 061: tamper-proof — restore the ORIGINAL test surface from
        # the snapshot AFTER the answer's apply; tampered tests never run
        _restore_test_surface(repo, task_index)
        # pre-existing ids from a PRISTINE snapshot probe (the restore
        # already wrote the new tests into `repo` — deriving pre ids
        # there would misfile new-test failures as pre-existing)
        pre_probe = os.path.join(ws, "pre_probe")
        materialize(pre_probe, task_index)
        pre_tests = _suite_test_ids(pre_probe)
        ok, _a, _b, failures = run_suite(repo)
        if failures.get("_suite") == "timeout":
            base["error"] = "suite exceeded the per-task wall ceiling"
            return base
        new_fail = {t: k for t, k in failures.items() if t not in pre_tests}
        pre_fail = {t: k for t, k in failures.items() if t in pre_tests}
        touched, untouched = _split_touched(pre_fail, answer_files)
        base["resolve"] = not new_fail
        base["regression"] = bool(pre_fail)
        base["touched_failures"] = touched
        base["untouched_failures"] = untouched
        # spec 061 Import 2: f2p/p2p counts + the reward semantics
        f2p_ids = _derive_f2p(os.path.dirname(repo), task_index)
        p2p_ids = set(pre_tests)
        failing = set(failures.keys())
        base["f2p_total"] = len(f2p_ids)
        base["f2p_passed"] = len(f2p_ids - failing)
        base["p2p_total"] = len(p2p_ids)
        base["p2p_passed"] = len(p2p_ids - failing)
        base["reward"] = bool(f2p_ids) and not (f2p_ids & failing) \
            and not (p2p_ids & failing)
        return base


def _suite_test_ids(root):
    """Test ids of the PRE-EXISTING suite (new tests not yet written)."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              timeout=TASK_CEILING_S,
                              env={**os.environ, "PYTHONPATH": "."})
    except subprocess.TimeoutExpired:
        return set()
    ids = set()
    for ln in (proc.stdout + proc.stderr).splitlines():
        m = ln.strip()
        # verbose lines: 'test_x (tests.mod.Class.test_x) ... ok' — the
        # parenthesized part IS the dotted id (matches run_suite's keys)
        if "(" in m:
            ids.add(m.split("(")[1].split(")")[0].strip())
    return ids


def selfcheck():
    """SC-001: green pre-patch -> gold 100% -> every sabotage fails >=1
    test, per task; standalone-runnable."""
    bad = 0
    for i, task in enumerate(TASKS, 1):
        # pre-patch green
        with tempfile.TemporaryDirectory(prefix="rr-sc-") as ws:
            repo = os.path.join(ws, "repo")
            materialize(repo, i - 1)
            ok, _pa, _nb, failures = run_suite(repo)
            if not ok and not _has_expected_new_failures_only(failures, task):
                # pre-patch with new tests appended must fail ONLY the new
                # tests (the issue exists) — that IS the intake shape
                if failures and all("NewBehavior" in t or "new_behavior" in t for t in failures):
                    pass
                else:
                    print(f"REALREPO-SELFCHECK FAIL task {i}: pre-patch suite not green: {failures}")
                    bad += 1
            # gold patch: 100%
            materialize(repo, i - 1, patch=task["gold_patch"])
            ok, _a, _b, failures = run_suite(repo)
            if not ok:
                print(f"REALREPO-SELFCHECK FAIL task {i}: gold patch not 100%: {failures}")
                bad += 1
            # sabotages: fail >= 1
            for s_i, sab in enumerate(task["sabotages"], 1):
                materialize(repo, i - 1, patch=sab)
                ok, _a, _b, failures = run_suite(repo)
                if ok or not failures:
                    print(f"REALREPO-SELFCHECK LEAK task {i} sabotage {s_i}: passed")
                    bad += 1
    return bad == 0


def _has_expected_new_failures_only(failures, task):
    return bool(failures) and all(
        "new_behavior" in t or "NewBehavior" in t or "New" in t for t in failures)


if __name__ == "__main__":
    import sys as _sys

    ok = selfcheck()
    print("realrepo selfcheck:", "OK" if ok else "FAILED")
    _sys.exit(0 if ok else 1)
