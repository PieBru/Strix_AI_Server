"""FCB-15 C-variants — tier ladder, tier C (drafted 2026-08-27, contract v3).

Pre-registered allocation (docs/FCB15-CALIBRATION.md contract v3): tier C
replaces the easiest band items 0 (LFU) and 4 (num_words) — both solved by
ALL 9 measured arms (OBSERVED 2026-08-27, artifacts in results/). Constraint
stacking per PROPOSAL-NONSATURATING-BATTERY.md L1: same task shape, added
contracts that the memorized classic solution violates.

Activation rule (contract v3): when >=2 recipes saturate battery v2
with-retry (14-15/15), the C swap fires (v3) and reruns once per recipe —
same mechanism as the v1->v2 B-swap that already fired (2026-08-25).

Drafted, selfchecked (refs pass, memorized-classic wrong probes fail),
committed BEFORE activation. Not referenced by the runner until the swap
executes.

Run standalone: uv run python3 batteries/fcb15_cvariants.py
"""

import sys


def _run(check_src, sol):
    ns = {}
    exec(check_src, ns)  # noqa: S102 - battery selfcheck (bvariants pattern)
    ns["check"](sol)


# Item 0C — LFU with inverted tie-break + degenerate capacities. The classic
# LFU evicts the least-RECENTLY-used on frequency ties; here it is the MOST
# recently used, and capacity 0 is legal (store nothing) — the memorized
# LRU-tie solver fails the tie asserts.
ITEMS_C0 = (
    """class LFU(capacity): get(key)->value or -1, put(key,value). Evict least-frequent; frequency ties evict the MOST recently used (inverted vs the classic). capacity 0: put stores nothing, get always -1. get() on a missing key returns -1 WITHOUT touching frequency.""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    LFU=ns['LFU']\n"
    "    c=LFU(2)\n"
    "    c.put('a',1); c.put('b',2)\n"
    "    assert c.get('a')==1\n"
    "    assert c.get('b')==2\n"
    "    assert c.get('a')==1\n"
    "    c.put('c',3)\n"                      # a,b freq 2,1 -> evict b
    "    assert c.get('b')==-1\n"
    "    assert c.get('c')==3\n"
    "    d=LFU(2)\n"
    "    d.put('x',1); d.put('y',2)\n"
    "    assert d.get('x')==1; assert d.get('y')==2\n"
    "    d.put('z',9)\n"                      # x,y both freq 1; tie -> MOST recent (y) evicted
    "    assert d.get('y')==-1 and d.get('x')==1 and d.get('z')==9\n"
    "    e=LFU(0)\n"
    "    e.put('k',5)\n"
    "    assert e.get('k')==-1\n"
    "    f=LFU(1)\n"
    "    assert f.get('nope')==-1\n"
    "    f.put('p',7); f.put('q',8)\n"
    "    assert f.get('p')==-1 and f.get('q')==8\n",
)

REF_C0 = (
    "class LFU:\n"
    "    def __init__(self, capacity):\n"
    "        self.cap = capacity\n"
    "        self.data = {}\n"
    "        self.freq = {}\n"
    "        self.time = {}\n"
    "        self.tick = 0\n"
    "    def get(self, key):\n"
    "        if key not in self.data:\n"
    "            return -1\n"
    "        self.tick += 1\n"
    "        self.freq[key] += 1\n"
    "        self.time[key] = self.tick\n"
    "        return self.data[key]\n"
    "    def put(self, key, value):\n"
    "        if self.cap <= 0:\n"
    "            return\n"
    "        self.tick += 1\n"
    "        if key in self.data:\n"
    "            self.data[key] = value\n"
    "            self.freq[key] += 1\n"
    "            self.time[key] = self.tick\n"
    "            return\n"
    "        if len(self.data) >= self.cap:\n"
    "            victim = min(self.data, key=lambda k: (self.freq[k], -self.time[k]))\n"
    "            del self.data[victim], self.freq[victim], self.time[victim]\n"
    "        self.data[key] = value\n"
    "        self.freq[key] = 1\n"
    "        self.time[key] = self.tick\n"
)

# classic LRU-tie LFU (the memorized shape): evicts least-RECENTLY-used on
# ties — passes every cache-ops assert EXCEPT the inverted-tie assert
WRONG_C0 = (
    "class LFU:\n"
    "    def __init__(self, capacity):\n"
    "        self.cap = capacity\n"
    "        self.data = {}\n"
    "        self.freq = {}\n"
    "        self.lastuse = {}\n"
    "        self.tick = 0\n"
    "    def get(self, key):\n"
    "        if key not in self.data:\n"
    "            return -1\n"
    "        self.tick += 1\n"
    "        self.freq[key] += 1\n"
    "        self.lastuse[key] = self.tick\n"
    "        return self.data[key]\n"
    "    def put(self, key, value):\n"
    "        if self.cap <= 0:\n"
    "            return\n"
    "        self.tick += 1\n"
    "        if key in self.data:\n"
    "            self.data[key] = value\n"
    "            self.freq[key] += 1\n"
    "            self.lastuse[key] = self.tick\n"
    "            return\n"
    "        if len(self.data) >= self.cap:\n"
    "            victim = min(self.data, key=lambda k: (self.freq[k], self.lastuse[k]))\n"
    "            del self.data[victim], self.freq[victim], self.lastuse[victim]\n"
    "        self.data[key] = value\n"
    "        self.freq[key] = 1\n"
    "        self.lastuse[key] = self.tick\n"
)


# Item 4C — num_words over the full signed 64-bit range with negatives and
# Zero. The classic 0..2^31-1 solver fails negatives and quintillions.
ITEMS_C4 = (
    """def num_words(n): -(2**63) <= n <= 2**63-1 to English words, Title Case, single spaces, hyphenate 21..99 non-multiples of ten. Negative numbers prefixed 'Negative ' (single space). 0 -> 'Zero'. Scale words: Thousand Million Billion Trillion Quadrillion Quintillion.""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    f=ns['num_words']\n"
    "    assert f(0)=='Zero'\n"
    "    assert f(5)=='Five'\n"
    "    assert f(42)=='Forty-Two'\n"
    "    assert f(1001)=='One Thousand One'\n"
    "    assert f(1234567890)=='One Billion Two Hundred Thirty-Four Million Five Hundred Sixty-Seven Thousand Eight Hundred Ninety'\n"
    "    assert f(-42)=='Negative Forty-Two'\n"
    "    assert f(-1000000)=='Negative One Million'\n"
    "    assert f(2**62)=='Four Quintillion Six Hundred Eleven Quadrillion Six Hundred Eighty-Six Trillion Eighteen Billion Four Hundred Twenty-Seven Million Three Hundred Eighty-Seven Thousand Nine Hundred Four'\n"  # noqa: E501
    "    assert f(-(2**63))=='Negative Nine Quintillion Two Hundred Twenty-Three Quadrillion Three Hundred Seventy-Two Trillion Thirty-Six Billion Eight Hundred Fifty-Four Million Seven Hundred Seventy-Five Thousand Eight Hundred Eight'\n",  # noqa: E501
)

REF_C4 = (
    "def num_words(n):\n"
    "    if n == 0:\n"
    "        return 'Zero'\n"
    "    ones=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',\n"
    "          'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',\n"
    "          'Seventeen','Eighteen','Nineteen']\n"
    "    tens=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']\n"
    "    scales=['','Thousand','Million','Billion','Trillion','Quadrillion','Quintillion']\n"
    "    neg = n < 0\n"
    "    n = abs(n)\n"
    "    def under1000(x):\n"
    "        parts=[]\n"
    "        if x >= 100:\n"
    "            parts.append(ones[x//100]+' Hundred')\n"
    "            x %= 100\n"
    "        if x >= 20:\n"
    "            parts.append(tens[x//10] + ('-'+ones[x%10] if x%10 else ''))\n"
    "        elif x:\n"
    "            parts.append(ones[x])\n"
    "        return parts\n"
    "    groups=[]\n"
    "    gi=0\n"
    "    while n:\n"
    "        chunk=n%1000\n"
    "        if chunk:\n"
    "            groups = under1000(chunk) + ([scales[gi]] if gi else []) + groups\n"
    "        n//=1000\n"
    "        gi+=1\n"
    "    out=' '.join(groups)\n"
    "    return ('Negative ' + out) if neg else out\n"
)

# classic 0..2^31 positive-only solver: fails negatives and 2**62
WRONG_C4 = (
    "def num_words(n):\n"
    "    ones=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine',\n"
    "          'Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen',\n"
    "          'Seventeen','Eighteen','Nineteen']\n"
    "    tens=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety']\n"
    "    scales=['','Thousand','Million','Billion']\n"
    "    def under1000(x):\n"
    "        parts=[]\n"
    "        if x >= 100:\n"
    "            parts.append(ones[x//100]+' Hundred')\n"
    "            x %= 100\n"
    "        if x >= 20:\n"
    "            parts.append(tens[x//10] + ('-'+ones[x%10] if x%10 else ''))\n"
    "        elif x:\n"
    "            parts.append(ones[x])\n"
    "        return parts\n"
    "    groups=[]\n"
    "    gi=0\n"
    "    while n:\n"
    "        chunk=n%1000\n"
    "        if chunk:\n"
    "            groups = under1000(chunk) + ([scales[gi]] if gi else []) + groups\n"
    "        n//=1000\n"
    "        gi+=1\n"
    "    return ' '.join(groups)\n"
)

ITEMS_C = [ITEMS_C0, ITEMS_C4]
REFS_C = [REF_C0, REF_C4]
WRONGS_C = [WRONG_C0, WRONG_C4]


def selfcheck():
    bad = 0
    for i, ((_, h), ref) in enumerate(zip(ITEMS_C, REFS_C, strict=True)):
        try:
            _run(h, ref)
        except Exception:
            print(f"C-VARIANT SELFCHECK FAIL ref {i + 1}")
            bad += 1
    for i, ((_, h), wrong) in enumerate(zip(ITEMS_C, WRONGS_C, strict=True)):
        try:
            _run(h, wrong)
            print(f"C-VARIANT LEAK {i + 1} (memorized-classic probe passed)")
            bad += 1
        except Exception:
            pass  # wrong probe failed the harness — required
    return bad == 0


if __name__ == "__main__":
    ok = selfcheck()
    print("C-VARIANTS SELFCHECK:", "GREEN" if ok else "RED")
    sys.exit(0 if ok else 1)
