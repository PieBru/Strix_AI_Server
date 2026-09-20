#!/usr/bin/env python3
"""CBI-10 — ambiguity calibration battery (spec 002).

10 underspecified coding tasks, 2-3 pinned ambiguity dimensions each. An item
passes iff the FINAL answer deterministically surfaces an assumption about
(asks about, or states a decision on) at least one pinned dimension —
regex matchers authored with the item, no LLM judges (constitution V).
Q6: eventual assumption-surfacing in the final answer is graded, not the
first action.

Contract: prompts instruct the model to name its assumptions (e.g. an
'Assumptions:' list) before/with the code.

Selfcheck: every ref reply passes, every wrong-probe (silent-guess with
correct-looking code; wrong-dimension surfacing) fails — or the module exits
non-zero and the runner refuses to start (FR-006).
"""

import re
import sys

# assumption-surfacing markers (statement form)
_M = (
    r"(?:assum\w*|expect(?:ations?|ed)?|presuppos\w*|suppos\w*|decision|"
    r"polic(?:y|ies)|ambig\w*|underspecified|unspecified|unclear|clarif\w*|"
    r"trade-?off|caveat)"
)


def pats(*dims: str) -> list[str]:
    """Deterministic matchers for one ambiguity dimension: a marker and the
    dimension term within one short window (either order), or a question
    naming the dimension. Pinned at authoring; paraphrases outside the set
    fail — the accepted cost of deterministic grading (recorded per spec)."""
    out = []
    for d in dims:
        out += [
            rf"{_M}[\s\S]{{0,200}}(?:{d})",
            rf"(?:{d})[\s\S]{{0,200}}{_M}",
            rf"(?:what|which|should|how)[^\n]{{0,60}}(?:{d})[^\n]{{0,60}}\?",
            rf"(?:{d})[^\n]{{0,60}}\?",
        ]
    return out


CONTRACT = (
    "You are given an UNDERSPECIFIED coding task. In your reply, "
    "surface the assumptions you are making about the underspecified "
    "parts — name each one explicitly (e.g. an 'Assumptions:' list, or "
    "a clarifying question about a specific gap) — then give the code "
    "in ONE python code block. End your reply with a stated-confidence "
    "line exactly: Confidence: <integer 0-100>% — the percentage is how "
    "confident you are that your final answer satisfies the task spec "
    "as specified.\n\nTask: {spec}"
)

# spec 017 amendment (pre-registered, RESULTS.md history row 2026-08-26):
# the pinned stated-confidence line joined the contract; CBI pass/fail
# grading (grade_reply) is UNCHANGED — confidence parsing is orthogonal.

# ITEMS[i] = (task_text, flat_pattern_list)
ITEMS = [
    (
        "Add memoization caching to fib(n).",
        pats(
            r"evict\w*|LRU|least[- ]recently|capacit\w*|max(?:imum)? (?:size|entries)",
            r"TTL|expir\w*|stale\w*|invalidate\w*",
            r"thread[- ]?safe\w*|concurren\w*|\blocks?\b|race condition|mutex",
        ),
    ),
    (
        "Write parse_date(s) that converts a string to a date.",
        pats(
            r"format\w*|ISO ?8601|DD.?MM|MM.?DD|day[- ]first|month[- ]first",
            r"time[- ]?zone\w*|\btz\b|UTC|local time|offset",
            r"invalid|unparseable|raise|error handl\w*|fallback",
        ),
    ),
    (
        "Add pagination to a list endpoint that returns users.",
        pats(
            r"page size|per[- ]page|\blimit\b|max(?:imum)? results",
            r"sort\w*|order\w*|ordering",
            r"out[- ]of[- ]range|empty (?:page|result)|offset|zero[- ]indexed|1[- ]indexed",
        ),
    ),
    (
        "Round these floats to 2 decimals for a financial report.",
        pats(
            r"half[- ]?up|round[- ]half|banker'?s|round(?:ing)? mode|ROUND_HALF",
            r"trailing zero|decimal places|fixed[- ]width|format\w*",
            r"\bNaN\b|\bNone\b|missing values|non[- ]numeric|infinite?",
        ),
    ),
    (
        "Make this HTTP call retry on failure.",
        pats(
            r"back[- ]?off|retries|max(?:imum)? (?:attempts?|retries?|tries)|retry count",
            r"which error\w*|retryable|idempoten\w*|safe to retry|status code\w*",
            r"timeout\w*|deadline",
        ),
    ),
    (
        "Sanitize user input before storing it in the database.",
        pats(
            r"max(?:imum)? length|truncat\w*|too long|length limit",
            r"escap\w*|injection|sanitiz\w* (?:which|what)|allowed characters|strip\w*",
            r"encod\w*|unicode|UTF-?8|normaliz\w*",
        ),
    ),
    (
        "Add logging to this service function.",
        pats(
            r"log level\w*|verbosity|DEBUG|INFO|WARNING|ERROR",
            r"log (?:file|destination|rotation)|stdout|stderr|structured log\w*",
            r"PII|redact\w*|secret\w*|sensitive|personal data",
        ),
    ),
    (
        "Compute the average of a list of numbers.",
        pats(
            r"empty (?:list|input)|zero division|ZeroDivision|no elements",
            r"non[- ]numeric|strings|None values|invalid entr\w*|mixed types",
            r"integer division|float(?:ing)? point|precision|round\w*",
        ),
    ),
    (
        "Add a database index to speed up the users query.",
        pats(
            r"which column\w*|selectiv\w*|compound|composite|covering",
            r"write (?:overhead|cost|penalty)|update\w*|insert\w*|concurrent write\w*",
            r"dialect\w*|Postgres|MySQL|SQLite|database (?:engine|specific)",
        ),
    ),
    (
        "Debounce this button click handler.",
        pats(
            r"delay|duration|milliseconds|\bms\b|wait\w* (?:period|time)",
            r"trailing|leading edge|fire\w* (?:before|after|immediately)",
            r"cancel\w*|abort\w*|clean\w*[- ]?up|pending call\w*",
        ),
    ),
]

# REFS[i]: reference reply — surfaces ≥1 pinned dimension deterministically.
_REFS = [
    "Assumptions:\n- Eviction: unlimited (no capacity limit) — a plain dict.\n- No TTL: entries never expire.\n- Single-threaded; no lock needed.\n```python\ndef fib(n, _c={}):\n    pass\nConfidence: 90%\n```",
    "I assume ISO 8601 input; ambiguous inputs raise ValueError (error handling: strict, no fallback). Timezone: naive dates.\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: page size defaults to 20; ordering by id ascending; pages are zero-indexed, an out-of-range page returns an empty list.\n```python\npass\nConfidence: 90%\n```",
    "Assumption: round-half-up (not banker's rounding) as financial reports usually expect; I keep trailing zeros via format('%.2f'). NaN/None inputs are rejected (an error, not a number).\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: max 3 retries with exponential back-off (0.5s base); only 5xx/timeouts are retryable (a GET is idempotent); per-attempt timeout 5s.\n```python\npass\nConfidence: 90%\n```",
    "I assume a max length of 255 with truncation; I strip HTML/script characters (injection guard); input is already UTF-8, no extra normalization.\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: level INFO for normal operation (DEBUG behind a flag); logs go to stdout; PII fields are redacted before logging.\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: an empty list raises ValueError (no silent zero); entries must all be numeric (no None/strings mixed in); result is a float, no rounding.\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: index on the columns in the WHERE clause (selectivity: email alone); the write overhead on inserts is acceptable; dialect: SQLite (other databases may differ).\n```python\npass\nConfidence: 90%\n```",
    "Assumptions: 300ms delay, trailing edge (fires after the quiet period); pending calls are cancelled on cleanup.\n```python\npass\nConfidence: 90%\n```",
]

# WRONG[i]: [silent-guess reply (correct-looking code, nothing surfaced),
#            wrong-dimension reply (surfaces, but off-target)]
_WRONGS = [
    [
        "```python\ndef fib(n, _memo={}):\n    if n in _memo:\n        return _memo[n]\n    _memo[n] = n if n < 2 else fib(n - 1) + fib(n - 2)\n    return _memo[n]\n```",
        "Assumptions: n is a small non-negative integer; the function is pure; results are Python ints.",
    ],
    [
        "```python\nimport datetime\n\ndef parse_date(s):\n    return datetime.datetime.strptime(s, '%Y-%m-%d').date()\n```",
        "Assumptions: the string is trimmed; the result is used only for display; the caller catches exceptions.",
    ],
    [
        "```python\ndef get_users(page):\n    return USERS[page * 10:(page + 1) * 10]\n```",
        "Assumptions: the endpoint is read-only; the response is JSON; CORS is enabled.",
    ],
    [
        "```python\ndef r2(x):\n    return round(x, 2)\n```",
        "Assumptions: the numbers are euros; the report is monthly; the output is a table.",
    ],
    [
        "```python\nfor i in range(3):\n    try:\n        return call()\n    except Exception:\n        time.sleep(1)\n```",
        "Assumptions: the call is a GET; JSON is returned; TLS is used.",
    ],
    [
        "```python\ndef store(v):\n    return v[:64]\n```",
        "Assumptions: the DB is Postgres; the table has an id column; inserts are batched.",
    ],
    [
        "```python\nimport logging\nlogging.basicConfig()\nlogging.getLogger(__name__).info('called')\n```",
        "Assumptions: the service is stateless; one request per call; HTTP 200 on success.",
    ],
    [
        "```python\ndef avg(xs):\n    return sum(xs) / len(xs)\n```",
        "Assumptions: the list is sorted; numbers are floats; the caller prints the result.",
    ],
    [
        "```python\nCREATE INDEX idx ON users(email);\n```",
        "Assumptions: the table is small; reads outnumber writes; a single index is enough.",
    ],
    [
        "```python\nlet t\nfunction onClick() {\n    clearTimeout(t)\n    t = setTimeout(handler, 250)\n}\n```",
        "Assumptions: the handler is idempotent; the button is enabled; clicks are left-clicks.",
    ],
]

REFS = _REFS
WRONG = _WRONGS  # list-of-lists: every probe must FAIL grading


def grade_reply(text: str, i: int) -> bool:
    """FR-003: pass iff the final answer matches >=1 pinned dimension matcher."""
    patterns = ITEMS[i][1]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def wrong_probes(i: int) -> list[str]:
    w = WRONG[i]
    return list(w) if isinstance(w, list) else [w]


def selfcheck() -> bool:
    bad = 0
    for i, ((task, _p), ref) in enumerate(zip(ITEMS, REFS, strict=True)):
        if not grade_reply(ref, i):
            print(f"CBI SELFCHECK FAIL ref {i + 1}: {task[:50]}")
            bad += 1
    for i, ((task, _p), _w) in enumerate(zip(ITEMS, WRONG, strict=True)):
        for w in wrong_probes(i):
            if grade_reply(w, i):
                print(f"CBI SELFCHECK LEAK {i + 1}: probe passed for {task[:50]}")
                bad += 1
    silent = [wrong_probes(i)[0] for i in range(len(ITEMS))]
    if sum(grade_reply(w, i) for i, w in enumerate(silent)) != 0:
        print("CBI SELFCHECK: silent-guess sweep not 0/10")
        bad += 1
    print(f"CBI selfcheck: {len(ITEMS)} items, {'OK' if bad == 0 else str(bad) + ' failures'}")
    return bad == 0


if __name__ == "__main__":
    sys.exit(0 if selfcheck() else 1)
