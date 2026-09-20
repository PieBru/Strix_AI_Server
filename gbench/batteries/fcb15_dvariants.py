"""FCB-15 D-variants — tier ladder, tier D (drafted 2026-08-27, contract v3).

Pre-registered allocation (docs/FCB15-CALIBRATION.md contract v3): tier D
replaces items 6 (longest valid parens) and 8 (Roman numerals) — both in the
solved-by-all-9 band (OBSERVED 2026-08-27). Constraint stacking per
PROPOSAL-NONSATURATING-BATTERY.md L1. Activation: tier D fires when >=2
recipes saturate battery v3 (post-C swap) with-retry — the ladder rule.

Drafted, selfchecked (refs pass, memorized-classic wrong probes fail),
committed BEFORE activation. Run: uv run python3 batteries/fcb15_dvariants.py
"""

import sys


def _run(check_src, sol):
    ns = {}
    exec(check_src, ns)  # noqa: S102 - battery selfcheck (bvariants pattern)
    ns["check"](sol)


# Item 6D — longest valid parens, RIGHTMOST tie + foreign chars break runs.
# The classic parens-only DP returns the leftmost max and treats only '(' ')'
# as content; here any other character TERMINATES a run, and ties return the
# rightmost occurrence — both memorized-shape violations.
ITEMS_D6 = (
    """def longest_parens(s): return (length, start_index) of the longest valid (well-formed, contiguous) parentheses substring. Ties in length: the RIGHTMOST one. Characters other than '(' and ')' can appear and TERMINATE a substring (they are never part of it). No valid substring -> (0, -1).""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    f=ns['longest_parens']\n"
    "    assert f('(()')==(2,1)\n"
    "    assert f(')()())')==(4,1)\n"
    "    assert f('')==(0,-1)\n"
    "    assert f(')(((')==(0,-1)\n"
    "    assert f('()(()')==(2,3)\n"
    "    assert f('()()')==(4,0)\n"
    "    assert f('()((())()')==(6,3)\n"
    "    # ties -> RIGHTMOST\n"
    "    assert f('()()')==(4,0)\n"
    "    assert f('()x()')==(2,3)\n"
    "    assert f('(())(())')==(8,0)\n"
    "    assert f('(())x(())')==(4,5)\n"
    "    assert f('()a()b()')==(2,6)\n",
)

REF_D6 = (
    "def longest_parens(s):\n"
    "    best_len, best_start = 0, -1\n"
    "    n = len(s)\n"
    "    i = 0\n"
    "    while i < n:\n"
    "        if s[i] not in '()':\n"
    "            i += 1\n"
    "            continue\n"
    "        j = i\n"
    "        while j < n and s[j] in '():':\n"
    "            j += 1\n"
    "        run = s[i:j]\n"
    "        stack = [-1]\n"
    "        for k, ch in enumerate(run):\n"
    "            if ch == '(':\n"
    "                stack.append(k)\n"
    "            else:\n"
    "                stack.pop()\n"
    "                if not stack:\n"
    "                    stack.append(k)\n"
    "                else:\n"
    "                    L = k - stack[-1]\n"
    "                    if L >= best_len:\n"
    "                        best_len, best_start = L, i + stack[-1] + 1\n"
    "        i = j\n"
    "    return (best_len, best_start)\n"
)

# classic parens-only leftmost DP: fails foreign-char termination AND the
# rightmost-tie contract
WRONG_D6 = (
    "def longest_parens(s):\n"
    "    best=0; start=-1\n"
    "    stack=[-1]\n"
    "    for i,ch in enumerate(s):\n"
    "        if ch=='(':\n"
    "            stack.append(i)\n"
    "        else:\n"
    "            stack.pop()\n"
    "            if not stack:\n"
    "                stack.append(i)\n"
    "            else:\n"
    "                L=i-stack[-1]\n"
    "                if L>best:\n"
    "                    best=L; start=i-L+1\n"
    "    return (best,start)\n"
)


# Item 8D — Roman arithmetic with strict canonical I/O. int_to_roman/parse
# as v2, PLUS roman_add(a, b): canonical inputs required, sum canonical
# output, sum > 3999 raises OverflowError — the concat-then-parse shortcut
# and lenient parsers both fail.
ITEMS_D8 = (
    """def int_to_roman(n): 1..3999 canonical. def roman_to_int(s): value; ValueError on invalid chars OR non-canonical forms (IIII, VIIII, IL...). def roman_add(a, b): both must parse as canonical (else ValueError); return the canonical Roman sum; if the sum exceeds 3999 raise OverflowError.""",
    "def check(src):\n"
    "    ns={}\n"
    "    exec(src,ns)\n"
    "    ir=ns['int_to_roman']; ri=ns['roman_to_int']; ra=ns['roman_add']\n"
    "    assert ir(1994)=='MCMXCIV'\n"
    "    assert ir(3999)=='MMMCMXCIX'\n"
    "    assert ri('MCMXCIV')==1994\n"
    "    assert ri('MMMCMXCIX')==3999\n"
    "    for bad in ('IIII','VIIII','IL','IC','IM','XM','VX','IIV','MCMXCIVI','ABC','mcm'):\n"
    "        try:\n"
    "            ri(bad)\n"
    "            raise AssertionError('accepted '+bad)\n"
    "        except ValueError:\n"
    "            pass\n"
    "    assert ra('X','IX')=='XIX'\n"
    "    assert ra('MCMXCIV','VI')=='MM'\n"
    "    assert ra('D','D')=='M'\n"
    "    try:\n"
    "        ra('MMMCMXCIX','I')\n"
    "        raise AssertionError('no OverflowError')\n"
    "    except OverflowError:\n"
    "        pass\n"
    "    try:\n"
    "        ra('IIII','I')\n"
    "        raise AssertionError('accepted non-canonical arg')\n"
    "    except ValueError:\n"
    "        pass\n",
)

REF_D8 = (
    "VAL=[(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),\n"
    "     (50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n"
    "def int_to_roman(n):\n"
    "    out=''\n"
    "    for v,s in VAL:\n"
    "        while n>=v:\n"
    "            out+=s; n-=v\n"
    "    return out\n"
    "def roman_to_int(s):\n"
    "    if not isinstance(s,str) or not s or any(c not in 'MDCLXVI' for c in s):\n"
    "        raise ValueError('invalid')\n"
    "    total=0; i=0\n"
    "    while i<len(s):\n"
    "        for v,sym in VAL:\n"
    "            if s.startswith(sym,i):\n"
    "                total+=v; i+=len(sym); break\n"
    "        else:\n"
    "            raise ValueError('invalid')\n"
    "    if int_to_roman(total)!=s:\n"
    "        raise ValueError('non-canonical')\n"
    "    return total\n"
    "def roman_add(a,b):\n"
    "    t=roman_to_int(a)+roman_to_int(b)\n"
    "    if t>3999:\n"
    "        raise OverflowError('sum exceeds 3999')\n"
    "    return int_to_roman(t)\n"
)

# lenient subtractive parser (accepts IIII, lowercase, concat add): fails
# the strict-rejection and canonical-add asserts
WRONG_D8 = (
    "R={'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}\n"
    "def int_to_roman(n):\n"
    "    out=''\n"
    "    for v,s in [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]:\n"
    "        while n>=v:\n"
    "            out+=s; n-=v\n"
    "    return out\n"
    "def roman_to_int(s):\n"
    "    s=s.upper()\n"
    "    total=0\n"
    "    for i,c in enumerate(s):\n"
    "        v=R[c]\n"
    "        if i+1<len(s) and R[s[i+1]]>v:\n"
    "            total-=v\n"
    "        else:\n"
    "            total+=v\n"
    "    return total\n"
    "def roman_add(a,b):\n"
    "    return int_to_roman(roman_to_int(a)+roman_to_int(b))\n"
)

ITEMS_D = [ITEMS_D6, ITEMS_D8]
REFS_D = [REF_D6, REF_D8]
WRONGS_D = [WRONG_D6, WRONG_D8]


def selfcheck():
    bad = 0
    for i, ((_, h), ref) in enumerate(zip(ITEMS_D, REFS_D, strict=True)):
        try:
            _run(h, ref)
        except Exception:
            print(f"D-VARIANT SELFCHECK FAIL ref {i + 1}")
            bad += 1
    for i, ((_, h), wrong) in enumerate(zip(ITEMS_D, WRONGS_D, strict=True)):
        try:
            _run(h, wrong)
            print(f"D-VARIANT LEAK {i + 1} (memorized-classic probe passed)")
            bad += 1
        except Exception:
            pass
    return bad == 0


if __name__ == "__main__":
    ok = selfcheck()
    print("D-VARIANTS SELFCHECK:", "GREEN" if ok else "RED")
    sys.exit(0 if ok else 1)
