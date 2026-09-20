"""TRAPS-14 v2 swap variants (spec: TRAPS v2 escalation, pre-registered
2026-08-28 in docs/RESULTS.md BEFORE the calibration rerun).

Positions 0 and 3 are the two lowest-index consensus-ceiling items (5/5
cells solved greedy in the 2026-08-28 five-cell analysis) — the same
mechanical rule FCB-15 v3 used. Each variant keeps the item's fact family
and deepens the edge:

  * 0T (was 0: overlapping 'aa' count in 'aaaa' = 3): overlapping count in
    'aaaaa' = 4 — the naive s.count('aa') returns 2, and the off-by-one
    window is one longer than the v1 item.
  * 3T (was 3: bisect_left of 4 among duplicates = 2): BOTH bisect_right
    and bisect_left of 4 among duplicates, printed as an ordered tuple
    (5, 2) — tests knowing the left/right distinction AND the required
    order.

Expected values verified by live execution on CPython 3.11 (2026-08-28);
both semantics (str.count non-overlap, bisect_left/right among equals) are
version-stable across CPythons in common use — the battery's own rule.
"""

ITEMS_B = [
 ("Write a Python function that counts occurrences of the substring 'aa' in a string, including overlapping occurrences. Apply it to 'aaaaa' and print the result.", "4"),
 ("Write Python code using the bisect module: for a = [1, 2, 4, 4, 4, 6, 8], print the tuple (bisect_right index of 4, bisect_left index of 4). Print the tuple exactly.", "(5, 2)"),
]

REFS_B = [
 "s = 'aaaaa'\nprint(sum(1 for i in range(len(s)-1) if s[i:i+2]=='aa'))",
 "import bisect\na=[1,2,4,4,4,6,8]\nprint((bisect.bisect_right(a,4), bisect.bisect_left(a,4)))",
]

# plausible-wrongs: the CLASSIC answers (non-overlapping count; left/right
# swapped). Selfcheck must REJECT both.
WRONGS_B = [
 "print('aaaaa'.count('aa'))",
 "import bisect\na=[1,2,4,4,4,6,8]\nprint((bisect.bisect_left(a,4), bisect.bisect_right(a,4)))",
]
