#!/usr/bin/env python3
"""FCB-15 deep layer — amplified hidden asserts + grader hardening (spec 005).

Additive layer ONLY: item prompts and shallow asserts (batteries/
fcb15_items.py) are untouched (SC-004 diff-verified by test) — every number
stays comparable to the frozen v2 conventions on the shallow layer.

Contents:
  * DEEP[i]      — amplified adversarial asserts (new discriminating cases).
  * CATCHERS[i]  — plausible-wrong solutions that PASS shallow and FAIL deep:
                   the demonstrated catcher every amplified assert must ship
                   (authoring rule); a planted silent-failure instance.
  * MUTANTS[i]   — curated single-change corruptions of the references that
                   must NOT be clean passes (mutation testing: a grader that
                   passes a mutant is blind).
  * TRAPS_ALT[j] — second independent implementations of the traps expected
                   values (differential testing; divergence fails selfcheck).

Items 7, 10 and 15 ship NO deep asserts, recorded here: automated mutation
search (comparison flips, off-by-ones) found ZERO shallow-surviving mutants
and every designed plausible-wrong variant fails the existing shallow asserts
— the authoring rule (an assert without a demonstrated catcher does not ship)
forbids amplification there. Their MUTANTS still ship (shallow must bite).

Standalone: `uv run python3 batteries/fcb15_deep.py` exits 0/1.
"""

import importlib.util
import os
import signal
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fcb15 = _load("fcb15_items.py", "fcb15_items_deep")
traps14 = _load("traps14_items.py", "traps14_items_deep")

DEEP_TIMEOUT = 10  # s per deep check — bounded, never hangs the battery


class _DeepTimeout(Exception):
    pass


def _timed(fn):
    def _h(signum, frame):
        raise _DeepTimeout()

    old_h = signal.signal(signal.SIGALRM, _h)
    signal.setitimer(signal.ITIMER_REAL, DEEP_TIMEOUT)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_h)


def _chk(src, body):
    """Deep check: exec the answer, then run the amplified assert body."""
    ns: dict = {}

    def _run():
        exec(src, ns)  # noqa: S102 - grading executes answers by design
        exec(body, ns, dict(ns))  # noqa: S102

    _timed(_run)


# deep assert bodies, keyed by item index (None = no catcher, no ship)
DEEP: dict[int, str | None] = {
    # v3 (spec 037): positions 0/4 hold C0/C4 — NOT amplified (pre-registered
    # follow-up); None = shallow-only, same contract as item 15
    0: None,
    # 2. match: star edge amplification
    1: (
        "assert match('a', 'a*b') is False, 'star quantifies preceding char'\n"
        "assert match('abba', 'ab*a') is True\n"
        "assert match('ab', '.*c') is False\n"
        "assert match('a', 'ab*') is True\n"
    ),
    # 3. glob: trailing-dash class, negated ], multi-star
    2: (
        "assert glob_match('[a-]x', '-x') is True, 'trailing dash is literal'\n"
        "assert glob_match('[-a]x', '-x') is True, 'leading dash is literal'\n"
        "assert glob_match('[a-z0-9]9', '99') is True, 'compound class'\n"
    ),
    # 4. justify: word longer than W stays whole (never truncated)
    3: (
        "assert justify(['a', 'verylongword'], 5) == ['a    ', 'verylongword'], 'overflow word must not be truncated'\n"
    ),
    # 5. num_words: the 90s (typo hunting ground) + Hundred Thousand
    4: None,  # C4 unamplified (v3)
    # 6. simplify: double leading slashes collapse
    5: (
        "assert simplify('//a') == '/a', 'double leading slash collapses'\n"
        "assert simplify('///a/b') == '/a/b'\n"
        "assert simplify('a//../b') == 'b'\n"
    ),
    6: None,  # no catcher exists: shallow layer airtight (see module docstring)
    # 8. merge_intervals: float boundaries (touch never merges, overlap does)
    7: (
        "assert merge_intervals([[1, 2.5], [2.5, 3]]) == [(1, 2.5), (2.5, 3)], 'float touch'\n"
        "assert merge_intervals([[1, 2.5], [2.4, 3]]) == [(1, 3)], 'float overlap'\n"
        "assert merge_intervals([[1, 4], [2, 4]]) == [(1, 4)], 'subset merges'\n"
    ),
    # 9. roman: case-sensitive canonical
    8: (
        "for bad in ('iv', 'Iv', 'iV'):\n"
        "    try:\n"
        "        roman_to_int(bad); assert False, bad\n"
        "    except ValueError: pass\n"
        "assert int_to_roman(1600) == 'MDC'\n"
    ),
    9: None,  # no catcher exists (see module docstring)
    # 11. rle: single digits carry their count too
    10: (
        "assert rle_encode('5') == \"1'5'\", 'single digit carries count'\n"
        "assert rle_decode(rle_encode('w' * 12)) == 'w' * 12, 'multi-digit counts'\n"
    ),
    # 12. nqueens: counts beyond the shallow table (overfit detector)
    11: (
        "assert nqueens_count(7) == 40, '7-queens count'\n"
        "assert nqueens_count(9) == 352 and nqueens_count(10) == 724\n"
    ),
    # 13. eval_fraction: unary minus after an infix operator
    12: (
        "assert eval_fraction('1/2*-1/2') == (-1, 4), 'unary after *'\n"
        "assert eval_fraction('1/3--1/3') == (2, 3), 'minus negative'\n"
    ),
    # 14. edit_script: new pairs (distance still Levenshtein)
    13: (
        "for a, b, dist in (('a', 'aabb', 3), ('ab', 'aabb', 2), ('aab', 'aabb', 1),\n"
        "                       ('saturday', 'sunday', 3), ('xyz', 'zyx', 2), ('a', 'b', 1)):\n"
        "    ops = edit_script(a, b)\n"
        "    assert apply_script(a, ops) == b\n"
        "    assert sum(1 for o in ops if o[0] != 'k') == dist, (a, b)\n"
    ),
    14: None,  # no catcher exists (see module docstring)
}

CATCHERS: dict[int, str | None] = {
    # 1. get does not refresh recency (tie falls back to insertion order)
    0: None,  # C0 unamplified (v3)
    # 2. shallow-surviving ref mutant (verified by mutation search: char-match
    # branch inverted for '.', star-extend accepts non-matching chars)
    1: fcb15.REFS[1].replace(
        "elif p[j-1] == '.' or p[j-1] == s[i-1]:", "elif p[j-1] != '.' or p[j-1] == s[i-1]:"
    ),
    # 3. strict range parser: a '-' inside a class must form a single-char
    #    range on both sides; trailing/leading dash or compound classes
    #    return False (plausible strictness; the spec pins them literal)
    2: """def glob_match(pattern, s):
    toks = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == '[':
            j = i + 1
            neg = j < len(pattern) and pattern[j] == '^'
            if neg:
                j += 1
            body = []
            first = True
            while j < len(pattern) and (pattern[j] != ']' or first):
                body.append(pattern[j]); j += 1; first = False
            if j >= len(pattern):
                return False
            b = ''.join(body)
            if '-' in b:
                parts = b.split('-')
                if len(parts) != 2 or len(parts[0]) != 1 or len(parts[1]) != 1 or parts[0] > parts[1]:
                    return False
                toks.append((('nrng' if neg else 'rng'), parts[0], parts[1]))
            else:
                toks.append((('nset' if neg else 'set'), frozenset(b)))
            i = j + 1
        elif c == '*':
            toks.append(('*',)); i += 1
        elif c == '?':
            toks.append(('?',)); i += 1
        else:
            toks.append(('lit', c)); i += 1
    def go(t, p):
        if t == len(toks):
            return p == len(s)
        kind = toks[t]
        if kind[0] == 'lit':
            return p < len(s) and s[p] == kind[1] and go(t+1, p+1)
        if kind[0] == '?':
            return p < len(s) and s[p] != '/' and go(t+1, p+1)
        if kind[0] == '*':
            k = p
            while k <= len(s):
                if go(t+1, k):
                    return True
                if k == len(s) or s[k] == '/':
                    break
                k += 1
            return False
        if kind[0] == 'set':
            return p < len(s) and s[p] in kind[1] and go(t+1, p+1)
        if kind[0] == 'nset':
            return p < len(s) and s[p] not in kind[1] and go(t+1, p+1)
        if kind[0] == 'rng':
            return p < len(s) and kind[1] <= s[p] <= kind[2] and go(t+1, p+1)
        return p < len(s) and not (kind[1] <= s[p] <= kind[2]) and go(t+1, p+1)
    return go(0, 0)""",
    # 4. truncates overflow words at output time (shallow lines are all <= W,
    #    so shallow never sees it; a word longer than W must stay whole)
    3: fcb15.REFS[3].replace(
        "out.append(' '.join(line).ljust(W))", "out.append(' '.join(line)[:W].ljust(W))"
    ),
    # 5. 'Ninty' typo in the tens table (shallow tests stop at the 80s)
    4: None,  # C4 unamplified (v3)
    # 6. os.path.normpath (POSIX keeps a double leading slash)
    5: (
        "def simplify(path):\n"
        "    import os\n"
        "    out = os.path.normpath(path)\n"
        "    if path.startswith('/') and not out.startswith('/'):\n"
        "        out = '/' + out\n"
        "    return out\n"
    ),
    # 8. integer-arithmetic overlap test (a <= last_b - 1) breaks on floats
    7: fcb15.REFS[7].replace(
        "        if out and a < out[-1][1]:", "        if out and a <= out[-1][1] - 1:"
    ),
    # 9. case-insensitive parser accepts 'iv'
    8: fcb15.REFS[8].replace(
        "    if not re.fullmatch(r'[MDCLXVI]+', s): raise ValueError(s)",
        "    s = s.upper()\n    if not re.fullmatch(r'[MDCLXVI]+', s): raise ValueError(s)",
    ),
    # 11. decoder parses only the LAST digit of the count run (every shallow
    # count is single-digit; multi-digit runs decode wrong)
    10: fcb15.REFS[10].replace("        n = int(e[i:j])", "        n = int(e[j-1])"),
    # 12. overfit lookup table (passes every tested count, no search at all)
    11: (
        "def nqueens_count(n):\n"
        "    return {1: 1, 4: 2, 5: 10, 6: 4, 8: 92}.get(n, 0)\n"
        "def nqueens_first(n):\n"
        "    table = {8: ['Q.......','....Q...','.......Q','.....Q..','..Q.....',"
        "'......Q.','.Q......','...Q....']}\n"
        "    return table.get(n, ['Q' + '.' * (n - 1)] * n)\n"
    ),
    # 13. unary minus recognized only at expression start / after '(' (not
    #     after an infix operator)
    12: fcb15.REFS[12].replace(
        "        if t == '-':\n            take(); p, q = prim(); return (-p, q)",
        "        if t == '-' and (pos[0] == 0 or toks[pos[0] - 1] == '('):\n"
        "            take(); p, q = prim(); return (-p, q)",
    ),
    # 14. shallow-surviving ref mutant (verified by mutation search: insert
    # cost corrupted in the DP table; all 6 shallow pairs still pass)
    13: fcb15.REFS[13].replace("dp[i][j-1] + 1,", "dp[i][j-1] + 2,"),
}

# curated mutants of the references (single change); each must NOT be a clean
# pass under the layered grader. Items without deep asserts still bite here.
MUTANTS: dict[int, list[str]] = {
    # v3 (spec 037): positions 0/4 hold the C-bank items (unamplified —
    # DEEP/CATCHERS None below); mutants corrupt the NEW references and
    # shallow must bite them, same contract as every unamplified item.
    0: [fcb15.REFS[0].replace("(self.freq[k], -self.time[k])", "(self.freq[k], self.time[k])")],
    1: [fcb15.REFS[1].replace("dp[0][j] = dp[0][j-2]", "dp[0][j] = dp[0][j-1]")],
    2: [fcb15.REFS[2].replace("if pat[j] == ']' and not first: break", "if pat[j] == ']': break")],
    3: [fcb15.REFS[3].replace("base + (1 if i < extra else 0)", "base + (1 if i >= extra else 0)")],
    4: [fcb15.REFS[4].replace("'Forty'", "'Fourty'")],
    5: [fcb15.REFS[5].replace("res or '.'", "'.'")],
    6: [fcb15.REFS[6].replace("if L > best:", "if L >= best:")],
    7: [fcb15.REFS[7].replace("a < out[-1][1]", "a <= out[-1][1]")],
    8: [fcb15.REFS[8].replace("total += m[s[i+1]] - m[s[i]]", "total -= m[s[i+1]] - m[s[i]]")],
    9: [fcb15.REFS[9].replace("q[0] <= t - self.w", "q[0] < t - self.w")],
    10: [
        fcb15.REFS[10].replace(
            "while j < len(e) and e[j].isdigit(): j += 1",
            "while j < len(e) and e[j].isdigit(): j += 2",
        )
    ],
    11: [
        fcb15.REFS[11].replace(
            "(row - c) in d1 or (row + c) in d2", "(row - c) in d1 or (row + c) in d1"
        )
    ],
    12: [
        fcb15.REFS[12].replace(
            "v = add(v, r) if op == '+' else sub(v, r)", "v = add(v, r) if op == '+' else add(v, r)"
        )
    ],
    13: [fcb15.REFS[13].replace("dp[i-1][j-1] + (a[i-1] != b[j-1])", "dp[i-1][j-1] + 1")],
    14: [fcb15.REFS[14].replace("r = (r + k) % i", "r = (r + k - 1) % i")],
}

# second independent implementations of every traps expected value
TRAPS_ALT = [
    # v2 (2026-08-28): twins for the swapped positions regenerate from the
    # new expected values — different algorithm than the battery refs.
    "import re\nprint(len(re.findall(r'(?=aa)', 'aaaaa')))",  # 4 (overlap via lookahead)
    "r = 7\nwhile r > 0 or r < -3:\n    r += -3 if r > 0 else 3\nprint(r)",  # -2
    "out = []\nfor n in (2, 1):\n    out += [p for p in [('a',1),('b',1),('c',2)] if p[1] == n]\nprint(out)",
    "lst = [1, 2, 4, 4, 4, 6, 8]\n"
    "lft = next(i for i, v in enumerate(lst) if v >= 4)\n"
    "rgt = next(i for i, v in enumerate(lst) if v > 4)\n"
    "print((rgt, lft))",  # (5, 2) via manual scans, no bisect module
    "pts = sorted([1, 4, 4, 5, 6, 8])\nseg = []\nfor t in pts:\n    pass\n"
    "import itertools\n"
    "merged = []\n"
    "for a, b in [[1,4],[4,5],[6,8]]:\n"
    "    if merged and a <= merged[-1][1]:\n"
    "        merged[-1][1] = max(merged[-1][1], b)\n"
    "    else:\n"
    "        merged.append([a, b])\n"
    "print(merged)",
    "b = ''\nfor x in range(8):\n    b = ('1' if (-5 >> x) & 1 else '0') + b\nprint(b)",
    "line = 'a,\"b,c\",d'\nfields = []\ncur = ''\nin_q = False\n"
    "for ch in line:\n"
    "    if ch == '\"':\n"
    "        in_q = not in_q\n"
    "    elif ch == ',' and not in_q:\n"
    "        fields.append(cur); cur = ''\n"
    "    else:\n"
    "        cur += ch\n"
    "fields.append(cur)\nprint(fields)",
    "a, b = 'flaw', 'lawn'\n"
    "M = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]\n"
    "for i in range(len(a) + 1): M[i][0] = i\n"
    "for j in range(len(b) + 1): M[0][j] = j\n"
    "for i in range(1, len(a) + 1):\n"
    "    for j in range(1, len(b) + 1):\n"
    "        M[i][j] = min(M[i-1][j] + 1, M[i][j-1] + 1,\n"
    "                      M[i-1][j-1] + (a[i-1] != b[j-1]))\n"
    "print(M[len(a)][len(b)])",
    "shared = []\nshared.append(1)\nprint(shared[:])\nshared.append(2)\nprint(shared)",
    "row = [0, 0, 0]\ngrid = [row, row, row]\nrow[0] = 1\nprint([list(r) for r in grid])",
    "print('%r' % (0.1 + 0.2))",
    "import itertools\nn = 0\nfor ones in range(12):\n"
    "    for fives in range(3):\n"
    "        for tens in range(2):\n"
    "            if ones + 5 * fives + 10 * tens == 11:\n"
    "                n += 1\nprint(n)",
    "import re\ns = '1'\nfor _ in range(5):\n"
    "    s = ''.join(str(len(m.group(0))) + m.group(0)[0]\n"
    "                for m in re.finditer(r'(.)\\1*', s))\nprint(s)",
]


def shallow_ok(i: int, src: str) -> bool:
    ns: dict = {}
    try:
        exec(fcb15.ITEMS[i][1], ns)  # noqa: S102
        ns["check"](src)
        return True
    except Exception:
        return False


def deep_ok(i: int, src: str) -> bool:
    body = DEEP[i]
    if body is None:
        return True  # no amplified layer for this item (documented)
    try:
        _chk(src, body)
        return True
    except Exception:
        return False


def grade_layered(i: int, src: str) -> dict:
    """Two-layer grade (FR-002): shallow, deep, silent-failure flag."""
    s = shallow_ok(i, src)
    d = deep_ok(i, src) if s else None  # deep only defined for shallow passers
    return {
        "shallow_ok": s,
        "deep_ok": d,
        "silent_failure": bool(s and not d),
    }  # d is None only when not s


def traps_differential() -> list[int]:
    """Run every second implementation; return indices that disagree."""
    import contextlib
    import io

    bad = []
    for j, alt in enumerate(TRAPS_ALT):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                exec(alt, {})  # noqa: S102
            lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
            if not lines or lines[-1] != traps14.ITEMS[j][1]:
                bad.append(j)
        except Exception:
            bad.append(j)
    return bad


def selfcheck() -> bool:
    bad = 0
    # (a) refs pass shallow AND deep
    for i, ref in enumerate(fcb15.REFS):
        if not shallow_ok(i, ref):
            print(f"DEEP SELFCHECK FAIL shallow ref {i + 1}")
            bad += 1
        if not deep_ok(i, ref):
            print(f"DEEP SELFCHECK FAIL deep ref {i + 1}")
            bad += 1
    # (b) catchers: pass shallow, FAIL deep (planted silent failures detected)
    for i, c in CATCHERS.items():
        if c is None:
            continue
        if not shallow_ok(i, c):
            print(f"DEEP SELFCHECK FAIL catcher {i + 1}: does not pass shallow")
            bad += 1
        elif deep_ok(i, c):
            print(
                f"DEEP SELFCHECK LEAK catcher {i + 1}: passes deep (assert "
                f"has no demonstrated catcher — do not ship)"
            )
            bad += 1
    # (c) mutants must not be clean passes (mutation testing)
    for i, muts in MUTANTS.items():
        for k, mut in enumerate(muts):
            g = grade_layered(i, mut)
            if g["shallow_ok"] and g["deep_ok"]:
                print(f"DEEP SELFCHECK MUTANT ESCAPE item {i + 1}#{k + 1}")
                bad += 1
    # (d) traps differential: second implementations reproduce expected values
    for j in traps_differential():
        print(f"DEEP SELFCHECK TRAPS DIVERGENCE item {j + 1}")
        bad += 1
    n_deep = sum(1 for v in DEEP.values() if v is not None)
    print(
        f"FCB deep selfcheck: {n_deep} amplified items, "
        f"{len(CATCHERS)} catchers, {sum(len(v) for v in MUTANTS.values())} "
        f"mutants, 13 traps twins, "
        f"{'OK' if bad == 0 else str(bad) + ' failures'}"
    )
    return bad == 0


if __name__ == "__main__":
    sys.exit(0 if selfcheck() else 1)
