"""FCB-15 E-variants — tier ladder, tier E (drafted 2026-08-27, contract v3).

Pre-registered allocation (docs/FCB15-CALIBRATION.md contract v3): tier E
replaces items 9 (RateLimiter) and 11 (N-Queens count/first) — both in the
solved-by-all-9 band (OBSERVED 2026-08-27). Constraint stacking per
PROPOSAL-NONSATURATING-BATTERY.md L1: the fixed-queen constraint defeats the
memorized A000170 table; next_allowed defeats pure fixed-window counters.
Activation: tier E fires when >=2 recipes saturate battery v4 (post-D swap)
with-retry — the ladder rule.

Drafted, selfchecked (refs pass, memorized-classic wrong probes fail),
committed BEFORE activation. Run: uv run python3 batteries/fcb15_evariants.py
"""

import sys


def _run(check_src, sol):
    ns = {}
    exec(check_src, ns)  # noqa: S102 - battery selfcheck (bvariants pattern)
    ns["check"](sol)


# Item 9E — sliding-window limiter + next_allowed WITHOUT recording. The
# boundary rule is exact (left-open right-closed: an event exactly `window`
# ago is expired); next_allowed must be pure (no state change) — the
# memorized fixed-window counter fails both the boundary and the purity.
ITEMS_E9 = (
    """class RateLimiter(n, window): allow(t, key) -> bool — at most n events per key per sliding window. Window semantics: an event at time t counts for (t, t+window]; one exactly `window` later is EXPIRED. Also next_allowed(key, t) -> earliest t' >= t where allow(t', key) would be True — WITHOUT recording anything. Times are numbers, arrive non-decreasing per key.""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    RL=ns['RateLimiter']\n"
    "    r=RL(2,10)\n"
    "    assert r.allow(0,'a') is True\n"
    "    assert r.allow(5,'a') is True\n"
    "    assert r.allow(9,'a') is False\n"
    "    assert r.allow(10,'a') is True\n"   # event at 0 expired (0+10<=10)
    "    assert r.allow(10,'a') is False\n"
    "    assert r.allow(20,'a') is True\n"   # both 5 and 10 expired (<=20)
    "    s=RL(1,100)\n"
    "    assert s.allow(7,'k') is True\n"
    "    assert s.allow(106,'k') is False\n" # 7 counts for (7,107]
    "    assert s.allow(107,'k') is True\n"
    "    # purity + exactness of next_allowed\n"
    "    t=RL(2,10)\n"
    "    t.allow(0,'x'); t.allow(3,'x')\n"
    "    assert t.next_allowed('x',4)==10\n" # 0 expires at 10
    "    assert t.allow(4,'x') is False\n"   # next_allowed recorded NOTHING
    "    assert t.allow(9,'x') is False and t.allow(10,'x') is True\n"
    "    assert t.next_allowed('x',10)==13\n"  # 10 recorded; 3 expires at 13
    "    assert t.next_allowed('x',11)==13\n" # now 10 recorded; 3 expires at 13
    "    assert t.next_allowed('zz',0)==0\n", # unknown key: allowed now
)

REF_E9 = '''class RateLimiter:
    def __init__(self, n, window):
        self.n = n
        self.window = window
        self.events = {}
    def _live(self, key, t):
        return [x for x in self.events.get(key, []) if x > t - self.window]
    def allow(self, t, key):
        live = self._live(key, t)
        if len(live) >= self.n:
            return False
        self.events.setdefault(key, []).append(t)
        return True
    def next_allowed(self, key, t):
        live = self._live(key, t)
        if len(live) < self.n:
            return t
        return live[0] + self.window
'''

# memorized fixed-window counter: buckets by (t // window) — fails the
# sliding boundary (10 vs 5/10) and has no pure next_allowed
WRONG_E9 = '''class RateLimiter:
    def __init__(self, n, window):
        self.n = n
        self.window = window
        self.count = {}
        self.bucket = {}
    def allow(self, t, key):
        b = int(t // self.window)
        if self.bucket.get(key) != b:
            self.bucket[key] = b
            self.count[key] = 0
        if self.count[key] >= self.n:
            return False
        self.count[key] += 1
        return True
    def next_allowed(self, key, t):
        b = int(t // self.window)
        if self.bucket.get(key) != b or self.count.get(key, 0) < self.n:
            return t
        return (b + 1) * self.window
'''


# Item 11E — constrained N-Queens: a queen PRE-PLACED at (row, col). The
# unconstrained solution count is the memorized OEIS A000170 table; the
# fixed-queen count is a different number for most placements — the table
# looker fails immediately.
ITEMS_E11 = (
    """def nqueens_count_fixed(n, row, col): number of n-queens solutions with one queen PRE-PLACED at (row, col); 0 when the fixed cell is attacked off-board is impossible (row,col always on the board) — just count the placements of the remaining n-1 queens. def nqueens_first_fixed(n, row, col): the lexicographically first such solution as row strings ('.'*c+'Q'+'.'*(n-1-c)), or None when the count is 0.""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    cf=ns['nqueens_count_fixed']; ff=ns['nqueens_first_fixed']\n"
    "    # n=4: only 2 solutions; with a fixed queen at (1,1): count 0\n"
    "    assert cf(4,1,1)==0\n"
    "    assert ff(4,1,1) is None\n"
    "    # n=4 fixed (0,1): exactly the solution .Q../…Q./Q…./…Q. family\n"
    "    s=ff(4,0,1)\n"
    "    assert s is not None and s[0]=='.Q..'\n"
    "    assert s[1].count('Q')==1 and s[3]== '..Q.' or s[3]=='...Q'\n"
    "    assert sum(r.count('Q') for r in s)==4\n"
    "    # n=5 fixed (2,0): known constrained count = 2\n"
    "    assert cf(5,2,0)==2\n"
    "    # n=6 fixed (0,0): NO solution places a queen there (total 4 splits 1,2,0,1,0,0)\n"
    "    assert cf(6,0,0)==0\n"
    "    # n=8 fixed (3,4): NOT the A000170 total 92\n"
    "    assert cf(8,3,4)!=92 and cf(8,3,4)>0\n"
    "    # consistency: unconstrained n=6 total = sum over first-row fixed\n"
    "    assert sum(cf(6,0,c) for c in range(6))==4\n",
)

REF_E11 = '''def _solve(n, row, col):
    def cols():
        return range(n)
    results = []
    queens = [(row, col)]
    def safe(r, c, placed):
        for pr, pc in placed:
            if pc == c or abs(pr - r) == abs(pc - c):
                return False
        return True
    def bt(r):
        if r == n:
            results.append(list(queens))
            return
        if r == row:
            bt(r + 1)
            return
        for c in range(n):
            if safe(r, c, queens):
                queens.append((r, c))
                bt(r + 1)
                queens.pop()
    bt(0)
    return results

def nqueens_count_fixed(n, row, col):
    return len(_solve(n, row, col))

def nqueens_first_fixed(n, row, col):
    res = _solve(n, row, col)
    if not res:
        return None
    best = None
    for sol in res:
        rows = ['.'] * n
        grid = []
        for r, c in sorted(sol):
            grid.append('.' * c + 'Q' + '.' * (n - c - 1))
        key = tuple(grid)
        if best is None or key < best:
            best = key
    return list(best)
'''

# memorized A000170 table looker (wrong for constrained counts)
WRONG_E11 = '''TABLE = {1: 1, 2: 0, 3: 0, 4: 2, 5: 10, 6: 4, 7: 40, 8: 92, 9: 352}
def nqueens_count_fixed(n, row, col):
    return TABLE[n]
def nqueens_first_fixed(n, row, col):
    if n not in TABLE or TABLE[n] == 0:
        return None
    return ['.'] * n
'''

ITEMS_E = [ITEMS_E9, ITEMS_E11]
REFS_E = [REF_E9, REF_E11]
WRONGS_E = [WRONG_E9, WRONG_E11]


def selfcheck():
    bad = 0
    for i, ((_, h), ref) in enumerate(zip(ITEMS_E, REFS_E, strict=True)):
        try:
            _run(h, ref)
        except Exception:
            print(f"E-VARIANT SELFCHECK FAIL ref {i + 1}")
            bad += 1
    for i, ((_, h), wrong) in enumerate(zip(ITEMS_E, WRONGS_E, strict=True)):
        try:
            _run(h, wrong)
            print(f"E-VARIANT LEAK {i + 1} (memorized-classic probe passed)")
            bad += 1
        except Exception:
            pass
    return bad == 0


if __name__ == "__main__":
    ok = selfcheck()
    print("E-VARIANTS SELFCHECK:", "GREEN" if ok else "RED")
    sys.exit(0 if ok else 1)
