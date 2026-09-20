#!/usr/bin/env python3
"""RSI-4 — regression safety battery (spec 004).

4 multi-test tasks: a small module, an issue that changes ONE behavior, and a
pre-existing suite of 9 asserts per task covering behavior the issue does NOT
mention. The answer contract is pinned: the COMPLETE modified module source in
one code block.

Grading (deterministic, machine-only, per FR-003):
  * every assert runs in a FRESH namespace with the answer exec'd (no
    inter-assert coupling);
  * rsi        = surviving pre-existing asserts / total;
  * resolve_ok = all new-behavior asserts pass;
  * regression = resolve_ok AND rsi < 1  (the quiet regression — resolved the
    issue, broke untouched behavior; never a clean pass: ok = resolve AND rsi==1).
Unparseable answers fail deterministically (compile gate, FR-002).

Selfcheck gates every run: refs resolve with rsi 1.0; regression wrongs are
DETECTED (flag set); broken wrongs yield rsi 0. Standalone exit 0/1.
"""

import ast
import signal
import sys
from typing import TypedDict


class Task(TypedDict):
    module: str
    issue: str
    old_asserts: list[str]
    new_asserts: list[str]
    ref: str
    wrong_regress: str
    wrong_broken: str


ASSERT_TIMEOUT = 5  # s per assert — an infinite loop in an answer FAILS the
# task instead of hanging the battery (same rule as the runner's 60s guard)


class _AssertTimeout(Exception):
    pass


def _timed(fn):
    def _h(signum, frame):
        raise _AssertTimeout()

    old_h = signal.signal(signal.SIGALRM, _h)
    signal.setitimer(signal.ITIMER_REAL, ASSERT_TIMEOUT)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_h)


CONTRACT = (
    "Below is a module and an issue. Apply the issue by replying with "
    "the COMPLETE modified module source in ONE python code block — "
    "keep every existing behavior the issue does not ask to change.\n\n"
)

_T1_MODULE = """class Stack:
    def __init__(self):
        self._items = []

    def push(self, x):
        self._items.append(x)

    def pop(self):
        return self._items.pop()

    def peek(self):
        return self._items[-1]

    def size(self):
        return len(self._items)

    def is_empty(self):
        return not self._items
"""

_T2_MODULE = """def c_to_f(c):
    return c * 9 / 5 + 32


def f_to_c(f):
    return (f - 32) * 5 / 9


def c_to_k(c):
    return c + 273.15


def k_to_c(k):
    return k - 273.15
"""

_T3_MODULE = """class Invoice:
    def __init__(self):
        self.items = []

    def add_item(self, name, qty, unit_price):
        self.items.append((name, qty, unit_price))

    def total(self):
        return sum(q * p for _, q, p in self.items)

    def item_count(self):
        return len(self.items)

    def apply_discount(self, pct):
        return self.total() * (1 - pct / 100)
"""

_T4_MODULE = """class Version:
    def __init__(self, major, minor, patch):
        self.major = major
        self.minor = minor
        self.patch = patch

    @classmethod
    def parse(cls, s):
        a, b, c = s.split(".")
        return cls(int(a), int(b), int(c))

    def __eq__(self, other):
        return (self.major, self.minor, self.patch) == \
               (other.major, other.minor, other.patch)

    def __lt__(self, other):
        return (self.major, self.minor, self.patch) < \
               (other.major, other.minor, other.patch)
"""

TASKS: list[Task] = [
    {  # 1: Stack.swap_top
        "module": _T1_MODULE,
        "issue": (
            "Add swap_top(): with two or more items, exchange the top "
            "two; with fewer than two items raise IndexError."
        ),
        "old_asserts": [
            "s = Stack()\nassert s.is_empty()",
            "s = Stack()\ns.push(1)\nassert s.size() == 1",
            "s = Stack()\ns.push(1)\ns.push(2)\nassert s.pop() == 2",
            "s = Stack()\ns.push(1)\ns.push(2)\ns.push(3)\nassert s.pop() == 3 and s.pop() == 2 and s.pop() == 1",
            "s = Stack()\ns.push('a')\nassert s.peek() == 'a'\nassert s.size() == 1",
            "s = Stack()\ns.push(1)\ns.push(2)\nassert s.peek() == 2",
            "s = Stack()\ntry:\n    s.pop()\n    assert False\nexcept IndexError:\n    pass",
            "s = Stack()\ns.push(None)\nassert s.pop() is None",
            "s = Stack()\nfor i in range(3):\n    s.push(i)\ns.pop()\nassert s.size() == 2",
        ],
        "new_asserts": [
            "s = Stack()\ns.push(1)\ns.push(2)\ns.swap_top()\nassert s.pop() == 1 and s.peek() == 2",
            "s = Stack()\ns.push(1)\ntry:\n    s.swap_top()\n    assert False\nexcept IndexError:\n    pass",
        ],
        "ref": _T1_MODULE[:-1]
        + """

    def swap_top(self):
        if len(self._items) < 2:
            raise IndexError("need two items")
        self._items[-1], self._items[-2] = self._items[-2], self._items[-1]
""",
        "wrong_regress": _T1_MODULE.replace(
            "    def size(self):\n        return len(self._items)",
            "    def size(self):\n        return len(self._items) + 1",
        )[:-1]
        + """

    def swap_top(self):
        if len(self._items) < 2:
            raise IndexError("need two items")
        self._items[-1], self._items[-2] = self._items[-2], self._items[-1]
""",
        "wrong_broken": "raise RuntimeError('module broken at import')",
    },
    {  # 2: f_to_k
        "module": _T2_MODULE,
        "issue": "Add f_to_k(f): Fahrenheit to Kelvin, exact real formula.",
        "old_asserts": [
            "assert c_to_f(0) == 32",
            "assert c_to_f(100) == 212",
            "assert c_to_f(-40) == -40",
            "assert f_to_c(32) == 0",
            "assert f_to_c(212) == 100",
            "assert round(f_to_c(100), 2) == 37.78",
            "assert c_to_k(0) == 273.15",
            "assert k_to_c(273.15) == 0",
            "assert c_to_f(k_to_c(c_to_k(37))) == c_to_f(37)",
        ],
        "new_asserts": [
            "assert f_to_k(32) == 273.15",
            "assert round(f_to_k(212), 2) == 373.15",
        ],
        "ref": _T2_MODULE
        + """

def f_to_k(f):
    return (f - 32) * 5 / 9 + 273.15
""",
        "wrong_regress": _T2_MODULE.replace(
            "def c_to_f(c):\n    return c * 9 / 5 + 32", "def c_to_f(c):\n    return c * 9 / 5 + 33"
        )
        + """

def f_to_k(f):
    return (f - 32) * 5 / 9 + 273.15
""",
        "wrong_broken": "def f(:\n",
    },
    {  # 3: Invoice.apply_tax
        "module": _T3_MODULE,
        "issue": (
            "Add apply_tax(rate): total() plus rate percent tax (e.g. rate 20 on total 100 -> 120)."
        ),
        "old_asserts": [
            "inv = Invoice()\nassert inv.total() == 0",
            "inv = Invoice()\ninv.add_item('a', 2, 5.0)\nassert inv.total() == 10.0",
            "inv = Invoice()\ninv.add_item('a', 1, 5.0)\nassert inv.item_count() == 1",
            "inv = Invoice()\ninv.add_item('a', 3, 2.0)\ninv.add_item('b', 1, 4.0)\nassert inv.total() == 10.0",
            "inv = Invoice()\ninv.add_item('a', 100, 1.0)\nassert inv.apply_discount(10) == 90.0",
            "inv = Invoice()\ninv.add_item('a', 100, 1.0)\nassert inv.apply_discount(0) == 100.0",
            "inv = Invoice()\ninv.add_item('a', 100, 1.0)\nassert inv.apply_discount(100) == 0.0",
            "inv = Invoice()\ninv.add_item('a', 2, 3.5)\nassert inv.total() == 7.0",
            "inv = Invoice()\nfor i in range(5):\n    inv.add_item('x', 1, 2.0)\nassert inv.item_count() == 5 and inv.total() == 10.0",
        ],
        "new_asserts": [
            "inv = Invoice()\ninv.add_item('a', 4, 25.0)\nassert inv.apply_tax(20) == 120.0",
            "inv = Invoice()\ninv.add_item('a', 1, 50.0)\nassert inv.apply_tax(0) == 50.0",
        ],
        "ref": _T3_MODULE
        + """

    def apply_tax(self, rate):
        return self.total() * (1 + rate / 100)
""",
        "wrong_regress": _T3_MODULE.replace(
            "        return self.total() * (1 - pct / 100)",
            "        return self.total() * (1 - pct / 100) * 0.9",
        )
        + """

    def apply_tax(self, rate):
        return self.total() * (1 + rate / 100)
""",
        "wrong_broken": "assert 0",
    },
    {  # 4: Version.bump_minor
        "module": _T4_MODULE,
        "issue": (
            "Add bump_minor(): return a NEW Version with minor+1 and "
            "patch reset to 0; the receiver is not mutated."
        ),
        "old_asserts": [
            "v = Version.parse('1.2.3')\nassert v.major == 1 and v.minor == 2 and v.patch == 3",
            "assert Version.parse('2.0.0') == Version(2, 0, 0)",
            "assert Version.parse('1.2.3') == Version.parse('1.2.3')",
            "assert Version.parse('1.2.3') < Version.parse('1.2.4')",
            "assert Version.parse('1.2.3') < Version.parse('1.3.0')",
            "assert not (Version.parse('1.10.0') < Version.parse('1.2.0'))",
            "assert Version.parse('0.9.9') < Version.parse('1.0.0')",
            "v = Version.parse('1.2.3')\nassert not (v < Version.parse('1.2.3'))",
            "assert Version.parse('3.1.4').patch == 4",
        ],
        "new_asserts": [
            "v = Version.parse('1.2.3')\nb = v.bump_minor()\nassert b.major == 1 and b.minor == 3 and b.patch == 0",
            "v = Version.parse('2.5.7')\nv.bump_minor()\nassert v.minor == 5 and v.patch == 7",
        ],
        "ref": _T4_MODULE
        + """

    def bump_minor(self):
        return Version(self.major, self.minor + 1, 0)
""",
        # regression probe: comparison direction reversed — every __lt__ assert
        # breaks while bump_minor (the issue) stays green
        "wrong_regress": _T4_MODULE.replace(".patch) < ", ".patch) > ")
        + """

    def bump_minor(self):
        return Version(self.major, self.minor + 1, 0)
""",
        "wrong_broken": "while True:\n    pass",
    },
]

ITEMS = [
    (
        CONTRACT
        + "--- module ---\n"
        + t["module"]
        + "\n--- issue ---\n"
        + t["issue"]
        + f"\n\n(Pre-existing behavior is tested by a hidden suite of {len(t['old_asserts'])} "
        "asserts you cannot see; keep it green.)",
        i,
    )
    for i, t in enumerate(TASKS)
]
REFS = [t["ref"] for t in TASKS]
WRONG = [[t["wrong_regress"], t["wrong_broken"]] for t in TASKS]

LAST: dict = {}  # last grade result (runner row fields come from here)


def _module_ns(code: str) -> dict | None:
    """Exec the answer module once under the timer; None = broken/hanging.
    Asserts then run against a fresh copy of this namespace per assert
    (fresh state, no inter-assert coupling, one exec — not one per assert)."""
    ns: dict = {}
    try:
        # pi-lens-ignore: eval-exec
        _timed(lambda: exec(code, ns))  # noqa: S102 - grading executes answers
        return ns
    except Exception:
        return None


def _assert_ok(ns: dict, expr: str) -> bool:
    try:
        # pi-lens-ignore: eval-exec
        _timed(lambda: exec(expr, dict(ns)))  # noqa: S102
        return True
    except Exception:
        return False


def grade(code: str, i: int) -> dict:
    """Deterministic per-task grade -> {resolve_ok, rsi, regression, ...}."""
    t = TASKS[i]
    try:
        ast.parse(code)  # FR-002 syntax gate — parse-only, nothing compiled/executed here
    except SyntaxError:
        d = {"resolve_ok": False, "rsi": 0.0, "regression": False, "unparseable": True}
        LAST.clear()
        LAST.update(d)
        return d
    template = _module_ns(code)
    if template is None:  # raises/hangs at import: total breakage (rsi 0)
        d = {"resolve_ok": False, "rsi": 0.0, "regression": False, "broken_module": True}
        LAST.clear()
        LAST.update(d)
        return d
    surv = sum(1 for a in t["old_asserts"] if _assert_ok(template, a))
    new_ok = all(_assert_ok(template, a) for a in t["new_asserts"])
    rsi = round(surv / len(t["old_asserts"]), 3)
    d = {
        "resolve_ok": new_ok,
        "rsi": rsi,
        "regression": bool(new_ok and rsi < 1.0),
        "old_alive": surv,
        "old_total": len(t["old_asserts"]),
    }
    LAST.clear()
    LAST.update(d)
    return d


def selfcheck() -> bool:
    bad = 0
    for i, t in enumerate(TASKS):
        d = grade(t["ref"], i)
        if not (d["resolve_ok"] and d["rsi"] == 1.0):
            print(f"RSI SELFCHECK FAIL ref {i + 1}: {d}")
            bad += 1
        g = grade(t["wrong_regress"], i)
        if not (g["resolve_ok"] and g["rsi"] < 1.0 and g["regression"]):
            print(f"RSI SELFCHECK MISS regression {i + 1}: {g}")
            bad += 1
        b = grade(t["wrong_broken"], i)
        if not (b["rsi"] == 0.0 and not b["resolve_ok"]):
            print(f"RSI SELFCHECK MISS broken {i + 1}: {b}")
            bad += 1
    print(
        f"RSI selfcheck: {len(TASKS)} tasks "
        f"(ref rsi=1.0, regressions detected, broken rsi=0), "
        f"{'OK' if bad == 0 else str(bad) + ' failures'}"
    )
    return bad == 0


if __name__ == "__main__":
    sys.exit(0 if selfcheck() else 1)
