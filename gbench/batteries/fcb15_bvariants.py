"""FCB-15 B-variants — the pre-registered swap items (drafted 2026-08-25).

The calibration contract (docs/FCB15-CALIBRATION.md) pre-registered:
"14-15/15 -> swap the 2 easiest items (6, 8) for drafted B-variants; rerun
ONCE". The original pre-registration referenced variants that were never
committed (found by the 2026-08-25 adversarial audit); this module is the
honest completion of that remedy — drafted, selfchecked (refs pass,
plausible-wrong probes fail), and committed BEFORE the swap executes in
batteries/fcb15_items.py (battery v2). It stays in the repo as the drafting
record / provenance trail.

Design contract unchanged (docs/BATTERIES.md): spec <=40 words with pinned
semantics, twisted policy (the memorized classic solution must FAIL),
deterministic exec-harness grading, implementation-subtle not knowledge-gated.

Run standalone (selfcheck, exit 1 on any failure):
  uv run python3 batteries/fcb15_bvariants.py
"""

import sys

# Item 6B — path simplification, relative-path twist. V1 item 6 was
# absolute-only (the classic). Here '..' in a relative path with nothing left
# to pop STAYS in the output — the memorized absolute-only solver returns
# '/' + join and fails the relative/empty asserts.
ITEMS_B = [
    (
        """def simplify(path): normalize a POSIX path, absolute or relative. Collapse '.' and duplicate slashes; '..' pops a segment (at an absolute root it vanishes; with nothing to pop in a relative path it stays). Empty: '/' if absolute else '.'.""",
        "def check(src):\n"
        "    ns={}\n"
        "    exec(src,ns)\n"
        "    f=ns['simplify']\n"
        "    assert f('/a/b/../c/./d')=='/a/c/d'\n"
        "    assert f('/../../..')=='/'\n"
        "    assert f('/..')=='/'\n"
        "    assert f('/a/../../b')=='/b'\n"
        "    assert f('a//b/./c/')=='a/b/c'\n"
        "    assert f('a/b/..')=='a'\n"
        "    assert f('../a/..')=='..'\n"
        "    assert f('a/../..')=='..'\n"
        "    assert f('../..')=='../..'\n"
        "    assert f('')=='.'\n"
        "    assert f('.')=='.'\n",
    ),
    # Item 8B — interval merge, half-open twist. V1 item 8 merged on touch (the
    # classic). Here intervals are half-open [a, b): touching endpoints do NOT
    # merge, pairs may arrive in either order, and empty intervals drop — the
    # memorized touching-merge solver fails the first assert.
    (
        """def merge_intervals(intervals): pairs may arrive in either order (normalize). Intervals are half-open [a, b): merge only on positive overlap - touching endpoints do NOT merge. Drop empty intervals (a == b). Return the sorted list of merged tuples.""",
        "def check(src):\n"
        "    ns={}\n"
        "    exec(src,ns)\n"
        "    f=ns['merge_intervals']\n"
        "    assert f([[1,3],[3,5]])==[(1,3),(3,5)]\n"
        "    assert f([[1,3],[2,5]])==[(1,5)]\n"
        "    assert f([[1,5],[2,3]])==[(1,5)]\n"
        "    assert f([[5,3],[1,2]])==[(1,2),(3,5)]\n"
        "    assert f([[2,2],[1,3]])==[(1,3)]\n"
        "    assert f([[4,6],[1,2],[3,5],[5,7]])==[(1,2),(3,7)]\n"
        "    assert f([[1,2],[2,3],[3,4]])==[(1,2),(2,3),(3,4)]\n"
        "    assert f([])==[]\n",
    ),
]

REFS_B = [
    """def simplify(path):
    abs_ = path.startswith('/')
    st = []
    for part in path.split('/'):
        if part == '' or part == '.':
            continue
        if part == '..':
            if st and st[-1] != '..':
                st.pop()
            elif not abs_:
                st.append('..')
        else:
            st.append(part)
    res = '/'.join(st)
    return ('/' + res) if abs_ else (res or '.')""",
    """def merge_intervals(intervals):
    ivs = sorted((min(a, b), max(a, b)) for a, b in intervals if a != b)
    out = []
    for a, b in ivs:
        if out and a < out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(x) for x in out]""",
]

# Plausible-but-wrong probes: the V1 CLASSIC solutions (absolute-only
# simplify; touch-merge intervals) — both must FAIL the B-variant harnesses.
WRONG_B = [
    "def simplify(path):\n"
    "    st = []\n"
    "    for part in path.split('/'):\n"
    "        if part == '' or part == '.': continue\n"
    "        if part == '..':\n"
    "            if st: st.pop()\n"
    "        else: st.append(part)\n"
    "    return '/' + '/'.join(st)",
    "def merge_intervals(intervals):\n"
    "    ivs = sorted(intervals); out = []\n"
    "    for a, b in ivs:\n"
    "        if out and a <= out[-1][1]:\n"
    "            out[-1][1] = max(out[-1][1], b)\n"
    "        else: out.append([a, b])\n"
    "    return [tuple(x) for x in out]",
]


def _run(check_src, sol):
    ns = {}
    exec(check_src, ns)
    ns["check"](sol)


def selfcheck():
    bad = 0
    for i, ((_, h), ref) in enumerate(zip(ITEMS_B, REFS_B)):
        try:
            _run(h, ref)
        except Exception:
            print(f"B-VARIANT SELFCHECK FAIL ref {i + 1}")
            bad += 1
    for i, ((_, h), wrong) in enumerate(zip(ITEMS_B, WRONG_B)):
        try:
            _run(h, wrong)
            print(f"B-VARIANT LEAK {i + 1} (wrong probe passed)")
            bad += 1
        except Exception:
            pass  # wrong probe failed the harness — required
    return bad == 0


if __name__ == "__main__":
    ok = selfcheck()
    print("B-VARIANTS SELFCHECK:", "GREEN" if ok else "RED")
    sys.exit(0 if ok else 1)
