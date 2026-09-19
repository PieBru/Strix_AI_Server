#!/usr/bin/env python3
"""fcb15_run — run the FCB-15 frontier battery against an endpoint.

Usage:
  uv run python3 scripts/fcb15_run.py --tag calib27B \
      --model Qwen38-27B-coding [--host 127.0.0.1:8080] \
      [--battery fcb15|traps|combined] [--mode single|bestof] [--shots N] \
      [--hardware "HW-CLASS"]

Protocol (docs/FCB15-CALIBRATION.md): temp 0 primary; on failure ONE retry
at temp 0.6 (E7 rule — internal fleet experiment, REPORTED). Records greedy
+ retry results separately. JSONL resume-safe (skips completed (model,item)
cells). Timeouts: 900 s per HTTP request, 60 s SIGALRM per grade.

Cloud anchors (spec 029, opt-in): --host accepts a full URL, e.g.
  --host https://api.deepseek.com --model <vendor-id>
https:// sends Authorization: Bearer $GEFC_API_KEY — export GEFC_API_KEY
first (one vendor per invocation); without it the runner exits non-zero
BEFORE any request. The key never appears in rows or logs. Plain hosts
(default 127.0.0.1:8080) stay byte-identical http — no auth header.
"""

import argparse
import importlib.util
import json
import os
import re
import signal
import sys
import tempfile
import time
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_battery(rel_path: str):
    """Load a battery module from batteries/<rel_path> (cwd is repo root after
    the chdir above). Static-import analysis stays clean: no sys.path games."""
    spec = importlib.util.spec_from_file_location(rel_path, rel_path)
    assert spec is not None and spec.loader is not None, f"missing {rel_path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_fcb = _load_battery("batteries/fcb15_items.py")
ITEMS, REFS, WRONG = _fcb.ITEMS, _fcb.REFS, _fcb.WRONG
_BATTERY_VERSION = str(getattr(_fcb, "BATTERY_VERSION", "v1"))  # overridden per battery in main()
GRADE_MODE = "check"
TEMP_BASE = None      # V5: README-instruct arms override the greedy base temp
PACE_ITEMS = 0        # pace-abort (operator 2026-08-30): after this many
PACE_MAX_S = 0.0      # greedy items, elapsed > PACE_MAX_S aborts the leg
EXTRA_SAMPLING = {}   # V5: extra payload sampling keys (top_p/top_k/...)
_t_ITEMS = None  # traps (prompt, expected) list when selected
_cbi = None  # cbi10 module when selected
_cmi = None  # cmi10 module when selected (spec 031)
_rsi = None  # rsi4 module when selected
_deep = None  # fcb15_deep module when --deep (spec 005)
_hl = None  # harness_loop module when --mode loop (spec 006)
_rs = None  # runstate module when --mode loop (spec 006)

PROMPT = (
    "Write Python code exactly as specified. Reply with ONE python "
    "code block and nothing else.\n\n{spec}"
)

CMI_CONTRACT = _load_battery("batteries/cmi10_items.py").CONTRACT  # spec 031

CBI_CONTRACT = (
    "You are given an UNDERSPECIFIED coding task. In your reply, "
    "surface the assumptions you are making about the "
    "underspecified parts — name each one explicitly (e.g. an "
    "'Assumptions:' list, or a clarifying question about a specific "
    "gap) — then give the code in ONE python code block.\n\nTask: {spec}"
)

# in stdout mode item tuple is (prompt, None): use prompt directly


GRADE_TIMEOUT = 60  # s — model code with an infinite loop must not hang the battery


class _GradeTimeout(Exception):
    pass


def open_or_die(path, mode):
    """Fail loud on I/O errors — a runner that cannot read its rows must exit
    with a message, never limp on silently (constitution V)."""
    try:
        return open(path, mode)
    except OSError as e:
        print(f"ERROR: cannot open {path} ({mode}): {e}", file=sys.stderr)
        raise SystemExit(2) from e


_FACTORY = None  # set by --factory: captured effective serving config
_MAX_TOKENS = 4000  # overridable via --max-tokens (thinking models: the
# answer must survive the reasoning phase; see ornith15-halo 2026-08-27)


def _factory_stamp():
    """FR-001 (spec 024): every factory-mode row carries the factory recipe
    slot + the OBSERVED effective serving config (captured from the live
    endpoint at run start — what ran, recorded verbatim, never intention).
    Empty for non-factory runs."""
    if _FACTORY is None:
        return {}
    return {"recipe": "factory-default (engine defaults)", "serving_config": _FACTORY}


def usage_fields(resp):
    """FR-001 (spec 001): endpoint usage -> row fields. Absent -> None, never
    zero-filled (a zero would fabricate a CEI denominator)."""
    u = resp.get("usage") or {}
    det = u.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "total_tokens": u.get("total_tokens"),
        "reasoning_tokens": det.get("reasoning_tokens"),
    }


def _timed(fn):
    """Run fn under a SIGALRM guard; on expiry raise _GradeTimeout."""

    def _h(signum, frame):
        raise _GradeTimeout()

    old_h = signal.signal(signal.SIGALRM, _h)
    signal.setitimer(signal.ITIMER_REAL, GRADE_TIMEOUT)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_h)


def _grade(src, item_idx, full_text=None):
    """Grade: check-mode runs the item harness on src; traps-mode execs src and
    compares the LAST stdout line, falling back to a prose-stated answer when the
    code block doesn't print (models sometimes answer in prose + demo code);
    cbi-mode deterministically matches assumption-surfacing patterns in the
    final answer (spec 002 FR-003).
    The whole grade is wall-clock bounded (GRADE_TIMEOUT) so an infinite loop in
    model code FAILS the item instead of hanging the battery."""
    if GRADE_MODE == "cbi":
        assert _cbi is not None, "cbi battery selected but module unset"
        return _cbi.grade_reply(full_text or "", item_idx)
    if GRADE_MODE == "cmi":
        assert _cmi is not None, "cmi battery selected but module unset"
        return _cmi.grade_reply(full_text or "", item_idx)
    if GRADE_MODE == "rsi":
        assert _rsi is not None, "rsi battery selected but module unset"
        d = _rsi.grade(src, item_idx)
        return bool(d["resolve_ok"] and d["rsi"] == 1.0)
    _, harness = ITEMS[item_idx]
    if harness is None:  # traps mode
        import contextlib as _cl
        import io as _io

        assert _t_ITEMS is not None, "traps rows selected but _t_ITEMS unset"
        pe = _t_ITEMS[item_idx]
        want = pe[1]
        buf = _io.StringIO()
        try:

            def _run_traps():
                with _cl.redirect_stdout(buf):
                    exec(src, {})

            _timed(_run_traps)
        except Exception:
            pass
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        if lines and lines[-1] == want:
            return True
        if full_text:
            import re as _re

            tail = full_text[-400:]
            pats = [
                rf"output[^0-9\n]*{_re.escape(want)}\b",
                rf"\*\*{_re.escape(want)}\*\*",
                rf"→\s*{_re.escape(want)}\b",
                rf"->\s*{_re.escape(want)}\b",
                rf"is\s+\**{_re.escape(want)}\**\s*(?:\.|$)",
            ]
            return any(_re.search(p, tail) for p in pats)
        return False

    def _run_check():
        ns = {}
        exec(harness, ns)
        ns["check"](src)

    try:
        _timed(_run_check)
    except _GradeTimeout:
        return False  # model code infinite-looped — item FAILS, battery survives
    return True


def _all_wrongs(i):
    """Battery-agnostic wrong-probes: a plain string (fcb15/traps) or a list
    of probes (cbi) — every probe must fail the gate on every run."""
    w = WRONG[i]
    return list(w) if isinstance(w, list) else [w]


def selfcheck():
    bad = 0
    for i, ((_spec, _h), ref) in enumerate(zip(ITEMS, REFS, strict=True)):
        try:
            if not _grade(ref, i, full_text=ref):
                print(f"SELFCHECK FAIL ref {i + 1}")
                bad += 1
        except Exception:
            print(f"SELFCHECK FAIL ref {i + 1}")
            bad += 1
    for i, ((_spec, _h), _wrong) in enumerate(zip(ITEMS, WRONG, strict=True)):
        # leak probes gate EVERY battery (traps WRONGs are trivially-wrong
        # prints; cbi WRONGs are silent-guess + wrong-dimension replies)
        for probe in _all_wrongs(i):
            try:
                if _grade(probe, i, full_text=probe):
                    print(f"SELFCHECK LEAK {i + 1}")
                    bad += 1
            except Exception:
                pass
    return bad == 0


def extract_code(text):
    m = re.findall(r"```(?:python)?\s*(.*?)```", text or "", re.S)
    return m[-1] if m else (text or "")  # LAST block = final answer (models emit sketch-first)


def one(item_idx, model, host, temp, tries=5, seed=None, http_timeout=900):
    """seed: optional int -> appended as a system-nudge-free deterministic
    variation via temperature sampling; llama-server seeds via 'seed' param."""
    spec_, harness = ITEMS[item_idx]
    last = None
    if TEMP_BASE is not None:
        temp = TEMP_BASE  # README-instruct arm: base temp replaces greedy
    for a in range(tries):
        try:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            CBI_CONTRACT if GRADE_MODE == "cbi"
                            else CMI_CONTRACT if GRADE_MODE == "cmi"
                            else PROMPT
                        ).format(
                            spec=spec_
                        ),
                    }
                ],
                "max_tokens": _MAX_TOKENS,
                "temperature": temp,
            }
            if seed is not None:
                payload["seed"] = seed
            payload.update(EXTRA_SAMPLING)
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                _completions_url(host), body, _auth_headers(host)
            )
            t0 = time.time()
            r = json.load(urllib.request.urlopen(req, timeout=http_timeout))
            dt = time.time() - t0
            m = r["choices"][0]["message"]
            code = extract_code(m.get("content") or "")
            try:
                ok = _grade(code, item_idx, full_text=m.get("content") or "")
            except Exception:
                ok = False
            extra = (
                dict(_rsi.LAST) if (GRADE_MODE == "rsi" and _rsi is not None and _rsi.LAST) else {}
            )
            if GRADE_MODE == "cbi":
                # spec 017 FR-002: rows carry {stated confidence, outcome};
                # absent/unparseable -> None (never zero-filled), the row
                # marks it and ECE excludes it with the count reported
                _cal = _load_battery("scripts/calibration.py")
                extra = {"stated_confidence": _cal.parse_confidence(m.get("content") or "")}
            if _deep is not None and GRADE_MODE == "check":
                d_ok = _deep.deep_ok(item_idx, code) if ok else None
                extra = {"deep_ok": d_ok, "silent_failure": bool(ok and not d_ok)}
            return {
                "ok": ok,
                **extra,
                "wall": round(dt, 1),
                "content_tail": (m.get("content") or "")[-120:],
                "reason_w": len((m.get("reasoning_content") or "").split()),
                "content_w": len((m.get("content") or "").split()),
                "finish": r["choices"][0].get("finish_reason"),
                **usage_fields(r),
            }
        except Exception as e:
            last = e
            # connection REFUSED = server down, not transient: never retry-sleep it
            import urllib.error as _ue
            if isinstance(e, _ue.URLError) and isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                raise
            time.sleep(3 * (a + 1))
    assert last is not None, "no completion attempt succeeded or failed"
    raise last


# --- spec 029 scheme-auth: cloud anchors (opt-in, explicit, fail loud) ---
# --host may now be a full URL (http:// or https:// + optional port).
# Plain hostnames keep the byte-identical http:// default (FR-001,
# regression-gated). https:// sends Authorization: Bearer $GEFC_API_KEY
# (FR-002); the key lives ONLY in the env var — never rows, never logs
# (FR-003). No key => SystemExit before any request: zero network bytes,
# never an unauthenticated call, never a silent fallback (FR-004).
def _host_url(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host.rstrip("/")
    return f"http://{host}"


def _completions_url(host: str) -> str:
    """Completions endpoint for any vendor shape: base + /v1/... for
    version-less bases (llama-server, deepseek.ai) — byte-identical to
    the pre-029 convention; bases already ending in a version segment
    (/v4 on z.ai coding + pay-as-you-go) get /chat/completions appended
    directly (an extra /v1 there 404s)."""
    base = _host_url(host)
    if re.search(r"/v\d+$", base):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _auth_headers(host: str) -> dict:
    if host.startswith("https://"):
        key = os.environ.get("GEFC_API_KEY")
        if not key:
            raise SystemExit(
                "ERROR: https host requires GEFC_API_KEY — export it first, e.g. "
                "GEFC_API_KEY=<vendor key> uv run python3 scripts/fcb15_run.py "
                "--host https://api.deepseek.com ... (spec 029 FR-002; refusing "
                "to send any request unauthenticated)"
            )
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
    return {"Content-Type": "application/json"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:8080")
    ap.add_argument("--model", default="Qwen38-27B-coding")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--agent", default="none",
                    help="agent arm: 'none' (direct) or an adapter name (pi; tau = 050)")
    ap.add_argument("--agents-md", default=None,
                    help="AGENTS.md registry label — required when --agent != none")
    ap.add_argument("--mode", default="single", choices=["single", "bestof", "loop", "verifier"])
    ap.add_argument(
        "--battery",
        default="fcb15",
        choices=["fcb15", "traps", "combined", "cbi", "cmi", "sli", "rsi", "realrepo", "refactor"],
    )
    ap.add_argument("--shots", type=int, default=5)
    ap.add_argument(
        "--deep",
        action="store_true",
        help="adversarial layer (spec 005): layered grading "
        "(shallow+deep) on fcb15, SFI summary; shallow layer "
        "and scoring stay v2-comparable",
    )
    ap.add_argument(
        "--hardware",
        default=None,
        help="hardware class that produced this run; speed/cost "
        "rows are hardware-bound and carry this tag",
    )
    ap.add_argument(
        "--factory",
        action="store_true",
        help="spec 024: record this run as the factory-default baseline "
        "(recipe slot 'factory-default (engine defaults)'); captures the "
        "effective serving config from the live endpoint at run start",
    )
    ap.add_argument(
        "--heldout",
        default=None,
        metavar="GEN",
        help="private held-out generation id (spec 006): grade against "
        "results/heldout/GEN/items.py instead of the public battery; the "
        "generation must be registered active (scripts/heldout.py); rows "
        "carry heldout=GEN",
    )
    ap.add_argument(
        "--bestof-tag",
        default=None,
        help="--mode verifier: same-seed bestof artifact tag for the paired "
        "verifier-vs-sampling comparison in the summary",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=0,
        help="spec 009: R seeded sampling attempts per item (temp 0.7, seeds "
        "2000+r, rows phase repN); single mode only — repeats subsume "
        "bestof's variance question at the item level",
    )
    ap.add_argument(
        "--shuffle-seed",
        type=int,
        default=None,
        metavar="S",
        help="spec 009: deterministic seeded item execution order (indices "
        "permuted, never renumbered — pairing stays valid); recorded in "
        "every row and the summary",
    )
    ap.add_argument(
        "--items",
        type=int,
        default=0,
        help="run only the first N items (0 = all) — live slice checks / spot "
        "probes; the summary covers exactly the items run",
    )
    ap.add_argument(
        "--budget",
        type=int,
        default=0,
        help="whole-run wall budget in seconds (0 = unlimited); exceeding it "
        "stops the run LOUDLY with partial results marked partial",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="completion budget per item (default 4000; raise for thinking "
        "models whose reasoning outlives the answer — ornith15-halo 2026-08-27)",
    )
    ap.add_argument(
        "--temp",
        type=float,
        default=None,
        help="V5: override the greedy base temperature (README-instruct "
        "arms); the retry leg keeps this base temp with a fresh seed",
    )
    ap.add_argument("--top-p", type=float, default=None)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--presence-penalty", type=float, default=None)
    ap.add_argument("--min-p", type=float, default=None,
                    help="V5 sampling: min_p — cuts the low-probability "
                    "token tail (llama.cpp-specific; cloud endpoints may "
                    "ignore)")
    ap.add_argument("--repeat-penalty", type=float, default=None)
    ap.add_argument("--frequency-penalty", type=float, default=None)
    ap.add_argument(
        "--chat-template-kwargs",
        default=None,
        help="JSON dict merged into every payload, e.g. "
        "'{\"enable_thinking\": false}'",
    )
    args = ap.parse_args()
    global _MAX_TOKENS, _BATTERY_VERSION, TEMP_BASE, EXTRA_SAMPLING, \
        PACE_ITEMS, PACE_MAX_S
    _MAX_TOKENS = args.max_tokens
    if args.temp is not None:
        TEMP_BASE = args.temp
        try:
            PACE_ITEMS = int(os.environ.get("GEFC_PACE_ITEMS", "0") or 0)
            PACE_MAX_S = float(os.environ.get("GEFC_PACE_MAX_S", "0") or 0)
        except ValueError:
            PACE_ITEMS, PACE_MAX_S = 0, 0.0  # malformed env: pace-abort off
        # server-ready pre-flight (2026-08-30 503 crash): a LOADING
        # llama-server answers 503 — poll until 200 (or exit 2 loud)
        # before any item. SKIPPED for https cloud hosts (fixed
        # 2026-08-31: the poll sends no auth header — deepseek /v1/models
        # 401s unauthenticated, z.ai /v4 bases 404 outright — so the loop
        # could only exhaust; vendor APIs do not cold-load anyway).
        if not args.host.startswith("https://"):
            import urllib.request as _ur
            _url = (f"http://{args.host}/v1/models"
                    if not args.host.startswith("http") else
                    f"{args.host.rstrip('/')}/v1/models")
            for _w in range(120):  # up to 10 min
                try:
                    with _ur.urlopen(_url, timeout=5) as _resp:
                        if _resp.status == 200:
                            break
                except Exception:
                    pass
                time.sleep(5)
            else:
                print(f"ERROR: inference server {_url} not ready "
                      f"after 10 min", file=sys.stderr)
                return 2
    for _k in ("top_p", "top_k", "presence_penalty", "min_p",
               "repeat_penalty", "frequency_penalty"):
        _v = getattr(args, _k)
        if _v is not None:
            EXTRA_SAMPLING[_k] = _v
    if args.chat_template_kwargs:
        try:
            EXTRA_SAMPLING["chat_template_kwargs"] = json.loads(
                args.chat_template_kwargs)
        except ValueError as e:
            raise SystemExit(
                f"ERROR: --chat-template-kwargs is not valid JSON: {e}") from e
    # provenance stamp (homogeneity rule, 2026-08-28): every row records which
    # battery version produced it — fcb15 moves v1->v2->v3 via the calibration
    # contract; the other batteries are frozen at v1
    _BATTERY_VERSION = {"fcb15": _BATTERY_VERSION}.get(args.battery, "v1")

    # spec 029: https without a key refuses HERE — before the selfcheck
    # probe, before any network byte (SC-002: zero bytes sent).
    _auth_headers(args.host)

    if args.battery in ("realrepo", "refactor") and (args.deep or args.repeats
                                                     or args.mode != "single"
                                                     or args.heldout):
        print(
            f"ERROR: --battery {args.battery} applies to --mode single without "
            "--deep/--repeats/--heldout (repo/refactor tasks are graded by the "
            "full vendored suite; sampling/repeats/held-out are parked for this "
            "battery in v1)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.deep and (args.battery != "fcb15" or args.mode != "single"):
        print(
            "ERROR: --deep applies to --battery fcb15 --mode single only "
            "(the adversarial layer grades greedy/with-retry answers)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.mode == "verifier" and (args.deep or args.repeats or args.mode == "loop"):
        print(
            "ERROR: --mode verifier is exclusive with --deep and --repeats "
            "in v1 (verifier already samples N; composing is a parked "
            "refinement)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.mode == "verifier" and args.battery in ("cbi", "cmi", "rsi", "traps", "combined"):
        print(
            "ERROR: --mode verifier applies to check-graded batteries with "
            "per-item wrong-probes (fcb15/sli, or --heldout) — cbi/cmi grade "
            "prose, rsi grades patch suites, traps/combined mix stdout-mode "
            "rows: the self-test selection seam needs code+probe pairs",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.mode == "loop" and args.battery in ("cbi", "cmi", "rsi"):
        print(
            "ERROR: --mode loop applies to code-graded batteries "
            "(fcb15/sli/traps/combined) only — cbi/cmi grade prose and rsi "
            "grades patch suites: the loop's run-your-own-test feedback "
            "seam does not exist for them",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.repeats and (args.mode != "single" or args.deep):
        print(
            "ERROR: --repeats applies to --mode single without --deep in v1 "
            "(repeats subsume bestof's variance question; composing with "
            "bestof/verifier/deep is a parked refinement)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args.heldout and (args.deep or args.mode == "bestof"):
        print(
            "ERROR: --heldout applies to --mode single|loop without --deep "
            "(held-out sets are harness-row grading universes)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    hw = args.hardware  # bound to every row: speed/cost are hardware-class-specific

    global _FACTORY
    if args.factory:
        # FR-001: capture the EFFECTIVE serving config from the live endpoint
        # (observed fingerprint — engine defaults, no recipe pins; what ran is
        # recorded verbatim, not the intention).
        try:
            probe = {
                "model": args.model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
                "temperature": 0.0,
            }
            req = urllib.request.Request(
                _completions_url(args.host),
                json.dumps(probe).encode(),
                _auth_headers(args.host),
            )
            pr = json.load(urllib.request.urlopen(req, timeout=60))
            _FACTORY = {
                "model_requested": args.model,
                "model_served": pr.get("model"),
                "system_fingerprint": pr.get("system_fingerprint"),
                "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note": "engine-default serving config as observed from the "
                         "live endpoint (no recipe/reasoning pins; template-"
                         "default behavior; bare prompt)",
            }
            print(
                f"FACTORY baseline: requested {args.model} served "
                f"{_FACTORY['model_served']} "
                f"(fingerprint {_FACTORY['system_fingerprint']}) — every row "
                "carries recipe 'factory-default (engine defaults)'",
                flush=True,
            )
        except Exception as e:
            print(
                f"ERROR: --factory requires a live endpoint to capture the "
                f"effective serving config: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            raise SystemExit(2) from e

    if args.battery in ("realrepo", "refactor"):
        _rr = _load_battery(
            "batteries/realrepo_tasks.py" if args.battery == "realrepo"
            else "batteries/refactor_items.py"
        )
        assert _rr.selfcheck(), f"{args.battery} selfcheck failed — refusing to run"
        out_path = f"results/fcb15-{args.tag}.jsonl"
        done_rr: set[int] = set()
        if os.path.exists(out_path):
            for ln in open_or_die(out_path, "r"):
                try:
                    r = json.loads(ln)
                    if r.get("battery") == args.battery and r["model"] == args.model:
                        done_rr.add(r["item"])
                except Exception:
                    pass
        _items = _rr.TASKS if args.battery == "realrepo" else _rr.ITEMS
        n_items = len(_items) if not args.items else min(len(_items), args.items)
        t_run0 = time.monotonic()
        with open_or_die(out_path, "a") as out:
            for i in range(n_items):
                if i in done_rr:
                    continue
                if args.budget and time.monotonic() - t_run0 > args.budget:
                    print(
                        f"BUDGET STOP: {args.budget} s wall budget exceeded — "
                        f"partial run ({i}/{n_items} tasks); relaunch to resume "
                        "from the JSONL",
                        flush=True,
                    )
                    break
                prompt = _rr.task_prompt(i)
                last = None
                for a in range(3):
                    try:
                        payload = {
                            "model": args.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 6000,
                            "temperature": 0.0,
                        }
                        req = urllib.request.Request(
                            _completions_url(args.host),
                            json.dumps(payload).encode(),
                            _auth_headers(args.host),
                        )
                        t0 = time.time()
                        resp = json.load(urllib.request.urlopen(req, timeout=300))
                        dt = time.time() - t0
                        content = resp["choices"][0]["message"].get("content") or ""
                        grade = _rr.grade_answer(i, content)
                        if args.battery == "realrepo":
                            row = {
                                "model": args.model,
                                "item": i,
                                "phase": "realrepo",
                                "hardware": hw,
                                "ts": time.strftime("%Y-%m-%d %H:%M"),
                                "battery": "realrepo",
                                "resolve": grade["resolve"],
                                "regression": grade["regression"],
                                "touched_failures": grade["touched_failures"],
                                "untouched_failures": grade["untouched_failures"],
                                **({"error": grade["error"]} if grade["error"] else {}),
                                "wall": round(dt, 1),
                                "content_tail": content[-120:],
                                **usage_fields(resp),
                            }
                            print(
                                f"task {i + 1}: {'RESOLVED' if grade['resolve'] else 'UNRESOLVED'}"
                                + (f" | regression {grade['regression']}"
                                   if grade["regression"] else "")
                                + (f" | {grade['error']}" if grade["error"] else "")
                                + f" ({dt:.1f}s)",
                                flush=True,
                            )
                        else:
                            row = {
                                "model": args.model,
                                "item": i,
                                "phase": "refactor",
                                "hardware": hw,
                                "ts": time.strftime("%Y-%m-%d %H:%M"),
                                "battery": "refactor",
                                "ok": grade["ok"],
                                "behavior_ok": grade["behavior_ok"],
                                "stale_ok": grade["stale_ok"],
                                "import_ok": grade["import_ok"],
                                "stale_sites": grade["stale_sites"],
                                "behavior_failures": grade["behavior_failures"],
                                **({"stale_error": grade["stale_error"]}
                                   if grade["stale_error"] else {}),
                                **({"error": grade["error"]} if grade["error"] else {}),
                                "wall": round(dt, 1),
                                "content_tail": content[-120:],
                                **usage_fields(resp),
                            }
                            print(
                                f"task {i + 1}: {'PASS' if grade['ok'] else 'FAIL'}"
                                f" (behavior={grade['behavior_ok']} "
                                f"stale={grade['stale_ok']} "
                                f"import={grade['import_ok']})"
                                + (f" | stale sites {len(grade['stale_sites'])}"
                                   if not grade["stale_ok"] else "")
                                + (f" | {grade['error']}" if grade["error"] else "")
                                + f" ({dt:.1f}s)",
                                flush=True,
                            )
                        out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                            _BATTERY_VERSION}) + "\n")
                        out.flush()
                        break
                    except Exception as e:
                        last = e
                        time.sleep(3 * (a + 1))
                if last is not None:
                    print(
                        f"ERROR: {args.battery} task {i + 1} failed hard "
                        f"({type(last).__name__}: {last}) — pre-registered stop "
                        "condition: fail loud, never blind-retry past a wedged "
                        "completion path; resume-safe JSONL picks up on relaunch",
                        flush=True,
                    )
                    raise SystemExit(2) from last
        # summary over ALL rows (incl. resumed)
        rows = []
        for ln_no, ln in enumerate(open_or_die(out_path, "r"), 1):
            if args.model not in ln:
                continue
            try:
                r = json.loads(ln)
                if r.get("battery") == args.battery and r["model"] == args.model:
                    rows.append(r)
            except json.JSONDecodeError as e:
                print(f"ERROR: {out_path}:{ln_no}: malformed JSON row: {e}", file=sys.stderr)
                raise SystemExit(2) from e
        _arms = _load_battery("scripts/arms_summary.py")
        n = len(rows)
        hw_tag = f" [{hw}]" if hw else ""
        part_tag = f" | PARTIAL ({len(rows)}/{n_items} tasks)" if len(rows) < n_items else ""
        if n:
            if args.battery == "realrepo":
                res_n = sum(1 for r in rows if r["resolve"])
                reg_n = sum(1 for r in rows if r["regression"])
                unt_n = sum(1 for r in rows if r.get("untouched_failures"))
                lo_r, hi_r = _arms.wilson(res_n, n)
                lo_g, hi_g = _arms.wilson(reg_n, n)
                print(
                    f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: REALREPO "
                    f"resolve {res_n}/{n} (Wilson 95% CI [{lo_r:.2f}, {hi_r:.2f}]) "
                    f"| regression {reg_n}/{n} (CI [{lo_g:.2f}, {hi_g:.2f}]) "
                    f"| untouched-only regressions {unt_n}{part_tag}",
                    flush=True,
                )
            else:
                ok_n = sum(1 for r in rows if r["ok"])
                beh_n = sum(1 for r in rows if r["behavior_ok"])
                stale_n = sum(1 for r in rows if r["stale_ok"])
                imp_n = sum(1 for r in rows if r["import_ok"])
                lo, hi = _arms.wilson(ok_n, n)
                print(
                    f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: REFACTOR "
                    f"pass {ok_n}/{n} (Wilson 95% CI [{lo:.2f}, {hi:.2f}]) "
                    f"| behavior {beh_n}/{n} | stale-clean {stale_n}/{n} "
                    f"| import-clean {imp_n}/{n}{part_tag}",
                    flush=True,
                )
        else:
            print(
                f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: "
                f"{args.battery.upper()} no rows on disk",
                flush=True,
            )
        return

    global ITEMS, REFS, WRONG, GRADE_MODE, _t_ITEMS, _cbi, _cmi, _rsi, _deep, _hl, _rs

    if args.battery == "combined":
        _t = _load_battery("batteries/traps14_items.py")
        _t_ITEMS = {15 + i: pe for i, pe in enumerate(_t.ITEMS)}  # traps rows live at idx>=15
        ITEMS = list(ITEMS) + [(p, None) for p, _ in _t.ITEMS]
        REFS = list(REFS) + list(_t.REFS)
        WRONG = list(WRONG) + ["print('DELIBERATELY WRONG')"] * len(_t.ITEMS)
        assert selfcheck(), "combined selfcheck failed"
    elif args.battery == "traps":
        _t = _load_battery("batteries/traps14_items.py")
        _BATTERY_VERSION = str(getattr(_t, "BATTERY_VERSION", "v1"))
        _t_ITEMS = _t.ITEMS  # (prompt, expected) for traps rows
        ITEMS = [(p, None) for p, _ in _t.ITEMS]
        REFS = _t.REFS
        WRONG = ["print('DELIBERATELY WRONG')"] * len(ITEMS)
        GRADE_MODE = "stdout"
        assert selfcheck(), "traps selfcheck failed"
    elif args.battery == "rsi":
        _rsi = _load_battery("batteries/rsi4_items.py")
        ITEMS = _rsi.ITEMS  # (prompt, task_idx) pairs
        REFS = _rsi.REFS
        WRONG = _rsi.WRONG  # list-of-lists (regress probe, broken probe)
        GRADE_MODE = "rsi"
        assert selfcheck(), "rsi selfcheck failed — refusing to run"
    elif args.battery == "sli":
        _sli = _load_battery("batteries/sli10_items.py")
        ITEMS = _sli.ITEMS  # (spec, harness) pairs — check-mode, same as fcb15
        REFS = _sli.REFS
        WRONG = _sli.WRONG
        GRADE_MODE = "check"
        assert selfcheck(), "sli selfcheck failed — refusing to run"
    elif args.battery == "cbi":
        _cbi = _load_battery("batteries/cbi10_items.py")
        ITEMS = [(task, None) for task, _p in _cbi.ITEMS]
        REFS = _cbi.REFS
        WRONG = _cbi.WRONG  # list-of-lists; _all_wrongs flattens
        _t_ITEMS = _cbi.ITEMS
        GRADE_MODE = "cbi"
        assert selfcheck(), "cbi selfcheck failed — refusing to run"
    elif args.battery == "cmi":
        _cmi = _load_battery("batteries/cmi10_items.py")
        ITEMS = [(task, None) for task, _g, _f in _cmi.ITEMS]
        REFS = _cmi.REFS
        WRONG = _cmi.WRONG
        _t_ITEMS = _cmi.ITEMS
        GRADE_MODE = "cmi"
        assert selfcheck(), "cmi selfcheck failed — refusing to run"
    else:
        if args.deep:
            _deep = _load_battery("batteries/fcb15_deep.py")
            assert _deep.selfcheck(), "deep-layer selfcheck failed — refusing to run"
        assert selfcheck(), "battery selfcheck failed — refusing to run"

    heldout_gen = None
    if args.heldout:
        _heldout = _load_battery("scripts/heldout.py")
        if not _heldout.check_active(args.heldout):
            raise SystemExit(2)
        _ho = _heldout._load(args.heldout)[0]
        ITEMS, REFS, WRONG, GRADE_MODE = list(_ho.ITEMS), list(_ho.REFS), list(_ho.WRONG), "check"
        heldout_gen = args.heldout
        print(
            f"held-out generation {heldout_gen}: {len(ITEMS)} items (private, machine-local)",
            flush=True,
        )
        assert selfcheck(), "held-out selfcheck failed — refusing to run"

    _hl = None
    if args.mode in ("loop", "verifier"):
        _hl = _load_battery("scripts/harness_loop.py")
        assert _hl.selfcheck(ITEMS), "harness-loop selfcheck failed — refusing to run"

    out_path = f"results/fcb15-{args.tag}.jsonl"
    # spec 048: agent arms key the resume cells on (model, item, agent,
    # agents_md) — legacy direct rows never mask agent cells and vice versa
    _agent_mod = None
    _agents_md_path = _agents_md_sha = None
    _arm_budget = 0.0
    if args.agent != "none":
        _agent_mod = _load_battery("scripts/agents/adapter.py")
        if args.agents_md is None:
            print("ERROR: --agents-md is required when --agent != none", file=sys.stderr)
            raise SystemExit(2)
        if args.agent not in _agent_mod.IMPLEMENTED:
            print(f"ERROR: agent {args.agent!r} is not implemented (declared in "
                  "spec 047, lands in 050)", file=sys.stderr)
            raise SystemExit(2)
        _agents_md_path, _agents_md_sha = _agent_mod.verify_label(args.agents_md)
        try:
            _arm_budget = float(os.environ.get("GEFC_WALL_BUDGET_S", "0") or 0)
        except ValueError:
            _arm_budget = 0.0  # malformed env: unbounded (the documented default)
        _budget_tag = f"{_arm_budget:.0f}s" if _arm_budget else "unbounded"
        print(f"agent arm: {args.agent} | agents_md={args.agents_md}@"
              f"{(_agents_md_sha or '?')[:12]} | arm budget {_budget_tag}", flush=True)
    done: set[tuple] = set()  # (model, item[, repeat]) — legacy rows use the 2-tuple
    if os.path.exists(out_path):
        for line in open_or_die(out_path, "r"):
            try:
                r = json.loads(line)
                if args.agent != "none":
                    # only THIS agent arm's rows count as done
                    if (r.get("agent") == args.agent
                            and r.get("agents_md") == args.agents_md):
                        done.add((r["model"], r["item"]))
                elif str(r.get("phase", "")).startswith("rep"):
                    done.add((r["model"], r["item"], r.get("repeat")))
                elif "agent" not in r or r.get("agent", "none") == "none":
                    done.add((r["model"], r["item"]))  # legacy row: R=1 key
            except Exception:
                pass

    greedy_ok = retry_ok = 0
    n_items = len(ITEMS) if not args.items else min(len(ITEMS), args.items)
    t_run0 = time.monotonic()
    _rs = _load_battery("scripts/runstate.py") if args.mode == "loop" else None
    if _rs:
        _rs.begin(
            args.tag,
            budget_s=args.budget or None,
            model=args.model,
            mode="loop",
            battery=args.battery,
            heldout=heldout_gen,
        )
    order = list(range(n_items))
    if args.shuffle_seed is not None:
        _armod = _load_battery("scripts/arms_summary.py")
        order = _armod.shuffle_order(n_items, args.shuffle_seed)
    with open_or_die(out_path, "a") as out:
        for i in order:
            if args.repeats and any((args.model, i, r) in done for r in range(1, args.repeats + 1)):
                continue
            if not args.repeats and (args.model, i) in done:
                continue
            if args.budget and time.monotonic() - t_run0 > args.budget:
                print(
                    f"BUDGET STOP: {args.budget} s wall budget exceeded — partial "
                    f"run ({i}/{n_items} items reached); relaunch to resume "
                    "from the JSONL",
                    flush=True,
                )
                break
            if args.repeats:
                for r_idx in range(1, args.repeats + 1):
                    if (args.model, i, r_idx) in done:
                        continue
                    rep_row = one(i, args.model, args.host, 0.7, seed=2000 + r_idx)
                    row = {
                        "model": args.model,
                        "item": i,
                        "phase": f"rep{r_idx}",
                        "repeat": r_idx,
                        "hardware": hw,
                        "ts": time.strftime("%Y-%m-%d %H:%M"),
                        **(
                            {"shuffle_seed": args.shuffle_seed}
                            if args.shuffle_seed is not None
                            else {}
                        ),
                        **rep_row,
                    }
                    out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                        _BATTERY_VERSION}) + "\n")
                    out.flush()
                print(f"item {i + 1}: repeats R={args.repeats} done", flush=True)
                continue
            if args.mode == "verifier":
                assert _hl is not None
                spec_, _harness = ITEMS[i]
                _w = WRONG[i]
                wrong = _w if isinstance(_w, str) else _w[0]
                samples, vshot_rows = [], []
                for shot in range(args.shots):
                    content, meta = _hl.chat(
                        args.host,
                        args.model,
                        [{"role": "user", "content": _hl.LOOP_PROMPT.format(spec=spec_)}],
                        0.7,
                        seed=1000 + shot,
                    )
                    code, test = _hl.parse_answer(content)
                    st = _hl.run_model_test(code, test, wrong)
                    try:
                        h_ok = bool(_grade(code, i, full_text=content))
                    except Exception:
                        h_ok = False  # same armor as one()/loop
                    samples.append({"code": code, "test": test, "st": st})
                    vr = {
                        "model": args.model,
                        "item": i,
                        "phase": f"vshot{shot}",
                        "hardware": hw,
                        "ts": time.strftime("%Y-%m-%d %H:%M"),
                        "shot": shot,
                        "st_outcome": st["outcome"],
                        "ok": h_ok,
                        **({"fp": st["fp"]} if st["fp"] else {}),
                        **meta,
                    }
                    vshot_rows.append(vr)
                    out.write(json.dumps({**vr, **_factory_stamp()}) + "\n")
                    out.flush()
                sel_idx, sel_flag = _hl.select_by_self_tests(samples)
                sel_hidden = vshot_rows[sel_idx]["ok"]
                ceiling = any(r["ok"] for r in vshot_rows)
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "verifier",
                    "hardware": hw,
                    "ts": time.strftime("%Y-%m-%d %H:%M"),
                    "harness": "verifier-selected v1",
                    "ok": sel_hidden,
                    "selected_shot": sel_idx,
                    **({"selection_flag": sel_flag} if sel_flag else {}),
                    "ceiling_any": ceiling,
                    "n_shots": args.shots,
                    "st_outcomes": [r["st_outcome"] for r in vshot_rows],
                }
                out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                    _BATTERY_VERSION}) + "\n")
                out.flush()
                print(
                    f"item {i + 1}: verifier {'RESOLVED' if sel_hidden else 'UNRESOLVED'} "
                    f"(selected shot {sel_idx + 1}"
                    + (f", {sel_flag}" if sel_flag else "")
                    + f"; ceiling {'any-pass' if ceiling else 'none'})",
                    flush=True,
                )
                continue
            if args.mode == "loop":
                assert _hl is not None and _rs is not None
                spec_, _harness = ITEMS[i]
                _w = WRONG[i]
                wrong = _w if isinstance(_w, str) else _w[0]
                try:
                    r_ = _hl.run_loop_item(
                        i,
                        args.model,
                        args.host,
                        spec_,
                        wrong,
                        grade=lambda s, idx, full_text=None: _grade(s, idx, full_text=full_text),
                    )
                except SystemExit:
                    raise
                except Exception as e:
                    print(
                        f"ERROR: loop item {i + 1} failed hard "
                        f"({type(e).__name__}: {e}) — pre-registered stop "
                        "condition: fail loud, never blind-retry past a wedged "
                        "completion path; resume-safe JSONL picks up on relaunch",
                        flush=True,
                    )
                    if _rs:
                        _rs.end(args.tag, "error", items_done=i)
                    raise SystemExit(2) from e
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "loop",
                    "hardware": hw,
                    "ts": time.strftime("%Y-%m-%d %H:%M"),
                    "harness": _hl.HARNESS_ID,
                    **({"heldout": heldout_gen} if heldout_gen else {}),
                    **r_,
                }
                out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                    _BATTERY_VERSION}) + "\n")
                out.flush()
                _rs.update(args.tag, items_done=i + 1, last_item=i)
                _outs = " -> ".join(f"it{it['it']}:{it['outcome']}" for it in r_["iters"])
                print(
                    f"item {i + 1}: loop {'RESOLVED' if r_['ok'] else 'UNRESOLVED'} ({_outs})",
                    flush=True,
                )
                continue
            if args.mode == "bestof":
                solved = False
                any_ok = []
                for shot in range(args.shots):
                    r_ = one(i, args.model, args.host, 0.7, seed=1000 + shot)
                    any_ok.append(r_["ok"])
                    row = {
                        "model": args.model,
                        "item": i,
                        "phase": f"shot{shot}",
                        "hardware": hw,
                        "ts": time.strftime("%Y-%m-%d %H:%M"),
                        **r_,
                    }
                    out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                        _BATTERY_VERSION}) + "\n")
                    out.flush()
                    if r_["ok"]:
                        solved = True
                        break  # early stop: best-of-N solved (solving shot IS logged)
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "bestof",
                    "hardware": hw,
                    "ok": solved,
                    "shots_used": len(any_ok),
                }
                out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                    _BATTERY_VERSION}) + "\n")
                out.flush()
                print(
                    f"item {i + 1}: best-of-{args.shots} {'SOLVED' if solved else 'unsolved'}"
                    f" ({len(any_ok)} shots)",
                    flush=True,
                )
                continue
            if args.agent != "none":
                assert _agent_mod is not None and _agents_md_sha is not None
                # spec 048: agent arm — one graded attempt per item (FR-004),
                # the per-item agent wall cap bounds the attempt (047 FR-003),
                # the arm budget bounds the battery; the partial artifact
                # STANDS at the budget boundary (FR-005)
                if _arm_budget and (time.monotonic() - t_run0) > _arm_budget:
                    print(f"arm budget {_arm_budget:.0f}s reached — partial "
                          f"artifact stands ({greedy_ok} items solved)",
                          flush=True)
                    break
                spec_a, _harness_a = ITEMS[i]
                try:
                    os.makedirs(_agent_mod.WS_ROOT, exist_ok=True)
                except OSError as e:
                    raise SystemExit(
                        f"cannot create agent workspace root "
                        f"{_agent_mod.WS_ROOT}: {e}") from e
                ws_a = tempfile.mkdtemp(prefix=f"{args.tag}-item-{i + 1}-",
                                        dir=_agent_mod.WS_ROOT)
                res_a: dict
                try:
                    res_a = _agent_mod.run(ws_a, spec_a, _agents_md_path,
                                           _agent_mod.item_budget_s(),
                                           agent=args.agent, model=args.model)
                except _agent_mod._AgentTimeout as e:
                    res_a = {"artifact_path": os.path.join(ws_a, "solution.py"),
                             "transcript_path": None, "turns": 0,
                             "wall": _agent_mod.item_budget_s(),
                             "meta": {"stderr_tail": str(e), "timeout": True}}
                except _agent_mod._SandboxEscape as e:
                    res_a = {"artifact_path": os.path.join(ws_a, "solution.py"),
                             "transcript_path": None, "turns": 0, "wall": 0.0,
                             "meta": {"escape": str(e)}}
                ok_a, fail_a = False, ""
                if res_a["meta"].get("timeout"):
                    fail_a = "agent_timeout"
                elif res_a["meta"].get("escape") or res_a["meta"].get("escape_paths"):
                    fail_a = "escape_attempt"
                elif not os.path.exists(res_a["artifact_path"]):
                    fail_a = f"missing_artifact ({res_a['artifact_path']})"
                else:
                    try:
                        ok_a = bool(_grade(open(res_a["artifact_path"]).read(), i))
                    except Exception:
                        ok_a = False  # a raising check = FAIL (same armor)
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "greedy",
                    "hardware": hw,
                    "ts": time.strftime("%Y-%m-%d %H:%M"),
                    "ok": ok_a,
                    "fail": fail_a,
                    "wall": res_a["wall"],
                    "agent_wall": res_a["wall"],
                    "turns": res_a["turns"],
                    "agent": args.agent,
                    "agents_md": args.agents_md,
                    "agents_md_sha256": _agents_md_sha,
                }
                out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                    _BATTERY_VERSION}) + "\n")
                out.flush()
                greedy_ok += ok_a
                print(
                    f"item {i + 1}: agent {args.agent} "
                    f"{'PASS' if ok_a else 'FAIL' + (f' ({fail_a})' if fail_a else '')}"
                    f" ({res_a['wall']}s, turns={res_a['turns']})",
                    flush=True,
                )
                continue
            g = one(i, args.model, args.host, 0.0)
            row = {
                "model": args.model,
                "item": i,
                "phase": "greedy",
                "hardware": hw,
                "ts": time.strftime("%Y-%m-%d %H:%M"),
                **({"shuffle_seed": args.shuffle_seed} if args.shuffle_seed is not None else {}),
                **g,
            }
            out.write(json.dumps({**row, **_factory_stamp(), "battery_version": _BATTERY_VERSION})
                + "\n")
            out.flush()
            greedy_ok += g["ok"]
            # pace-abort (operator 2026-08-30): if the first PACE_ITEMS greedy
            # items already burned more than PACE_MAX_S, the arm is hopelessly
            # off the winner's pace — abort the leg (partial stands), the
            # driver moves to the next test
            if PACE_ITEMS and PACE_MAX_S and (i + 1) == PACE_ITEMS \
                    and (time.monotonic() - t_run0) > PACE_MAX_S:
                print(
                    f"pace-abort: first {PACE_ITEMS} items took "
                    f"{time.monotonic() - t_run0:.0f}s > {PACE_MAX_S:.0f}s "
                    "— aborting the leg (partial artifact stands)",
                    flush=True,
                )
                break
            rr = None
            if not g["ok"]:
                rr = one(i, args.model, args.host, 0.6)
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "retry06",
                    "hardware": hw,
                    "ts": time.strftime("%Y-%m-%d %H:%M"),
                    **rr,
                }
                out.write(json.dumps({**row, **_factory_stamp(), "battery_version":
                    _BATTERY_VERSION}) + "\n")
                out.flush()
                retry_ok += rr["ok"]
            print(
                f"item {i + 1}: greedy {'PASS' if g['ok'] else 'FAIL'}"
                + (f" | retry@0.6 {'PASS' if rr and rr['ok'] else 'FAIL'}" if rr else "")
                + f" ({g['wall']}s)",
                flush=True,
            )

    # V5 retry loop (operator 2026-08-30): up to two more passes over the
    # still-unsolved items, bounded by the arm wall budget
    # (GEFC_WALL_BUDGET_S; 0/unset = loop only while items remain unsolved).
    # The arm ends solved-all or budget-exhausted — the artifact stands
    # either way; the chain's kill-and-discard now only backstops a first
    # pass that overruns the budget on its own.
    def _resolved_map():
        m: dict = {}
        for ln in open_or_die(out_path, "r"):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if (r.get("model") != args.model
                    or r.get("phase") not in ("greedy", "retry06")):
                continue
            m[r["item"]] = m.get(r["item"], False) or bool(r.get("ok"))
        return m

    if args.mode == "single" and args.agent == "none":
        try:
            budget_s = float(os.environ.get("GEFC_WALL_BUDGET_S", "0") or 0)
        except ValueError:
            budget_s = 0.0
        for extra in (2, 3):
            unsolved = sorted(i for i, ok in _resolved_map().items() if not ok)
            if not unsolved:
                print("V5 retry loop: all items solved", flush=True)
                break
            elapsed = time.monotonic() - t_run0
            if budget_s and elapsed >= budget_s:
                print(f"V5 retry loop: wall budget {budget_s:.0f}s exhausted "
                      f"(elapsed {elapsed:.0f}s) — {len(unsolved)} item(s) "
                      "remain unsolved", flush=True)
                break
            print(f"V5 retry loop round {extra}: {len(unsolved)} unsolved "
                  "item(s)", flush=True)
            for i in unsolved:
                if budget_s and (time.monotonic() - t_run0) >= budget_s:
                    break
                r_ = one(i, args.model, args.host, 0.6,
                         seed=3000 + extra * 1000 + i)
                row = {
                    "model": args.model,
                    "item": i,
                    "phase": "retry06",
                    "attempt": extra + 1,  # greedy=1, inline retry=2, loop=3+
                    "hardware": hw,
                    "ts": time.strftime("%Y-%m-%d %H:%M"),
                    **r_,
                }
                # the item-loop handle is closed by now: append per write
                # (the resume-safe JSONL stays the source of truth)
                try:
                    with open(out_path, "a") as out:
                        out.write(json.dumps({**row, **_factory_stamp(),
                                              "battery_version":
                                              _BATTERY_VERSION}) + "\n")
                except OSError as e:
                    raise SystemExit(
                        f"ERROR: cannot append artifact {out_path}: {e}") from e
                print(f"item {i + 1}: retry#{extra} "
                      f"{'PASS' if r_['ok'] else 'FAIL'} ({r_['wall']}s)",
                      flush=True)

    # summary over ALL rows (incl. resumed); malformed JSONL fails loud with
    # its line number — a corrupt results file must not render a wrong summary
    rows = []
    for ln_no, ln in enumerate(open_or_die(out_path, "r"), 1):
        if args.model not in ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError as e:
            print(f"ERROR: {out_path}:{ln_no}: malformed JSON row: {e}", file=sys.stderr)
            raise SystemExit(2) from e
    hw_tag = f" [{hw}]" if hw else ""
    if args.repeats:
        _arms2 = _load_battery("scripts/arms_summary.py")
        by_item: dict[int, list[int]] = {}
        for r in rows:
            if str(r.get("phase", "")).startswith("rep"):
                by_item.setdefault(r["item"], []).append(1 if r["ok"] else 0)
        probs = [sum(v) / len(v) for v in by_item.values()]
        mean_p = sum(probs) / len(probs)
        partial_note = ""
        if len(probs) < 2 or args.repeats < 2:
            partial_note = " (no repeats depth — point estimate only)"
            print(
                f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: REPEATS R={args.repeats} "
                f"mean per-item pass probability {mean_p:.3f}{partial_note}",
                flush=True,
            )
            return
        se = _arms2.clustered_se(probs)
        lo, hi = _arms2.bootstrap_ci(probs, lambda xs: sum(xs) / len(xs), seed=200900)
        print(
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: REPEATS R={args.repeats} "
            f"mean per-item pass probability {mean_p:.3f} | clustered SE (cluster=item) "
            f"{se:.3f} | percentile-bootstrap 95% CI [{lo:.3f}, {hi:.3f}] (seed 200900, "
            f"{len(probs)} items) | shuffle-seed "
            f"{args.shuffle_seed if args.shuffle_seed is not None else 'none (natural order)'}"
            " — census of fixed items: intervals generalize over the seeded sampling",
            flush=True,
        )
        return
    if args.mode == "verifier":
        v_rows = [r for r in rows if r["phase"] == "verifier"]
        sel_n = sum(r["ok"] for r in v_rows)
        ceil_n = sum(r["ceiling_any"] for r in v_rows)
        all_pass = sum(1 for r in rows if str(r.get("phase", "")).startswith("vshot") and r["ok"])
        eff = round(sel_n / all_pass, 3) if all_pass else None
        vacuous_items = sum(1 for r in v_rows if r.get("selection_flag"))
        line = (
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: VERIFIER best-of-{args.shots} "
            f"selected {sel_n}/{len(v_rows)} | any-of-{args.shots} ceiling {ceil_n}/{len(v_rows)} "
            f"| selection-efficiency {eff if eff is not None else 'n/a (no passing samples)'} "
            f"| flagged items {vacuous_items}"
        )
        if args.bestof_tag:
            b_path = f"results/fcb15-{args.bestof_tag}.jsonl"
            b_res = {}
            if os.path.exists(b_path):
                for ln in open_or_die(b_path, "r"):
                    try:
                        r = json.loads(ln)
                        if r["phase"] == "bestof" and r["model"] == args.model:
                            b_res[r["item"]] = bool(r["ok"])
                    except Exception:
                        pass
            common = [r["item"] for r in v_rows if r["item"] in b_res]
            b_cnt = sum(
                1
                for it in common
                if bool(next(r for r in v_rows if r["item"] == it)["ok"]) and not b_res[it]
            )
            c_cnt = sum(
                1
                for it in common
                if not bool(next(r for r in v_rows if r["item"] == it)["ok"]) and b_res[it]
            )
            if common:
                _arms = _load_battery("scripts/arms_summary.py")
                p = _arms.mcnemar_exact(b_cnt, c_cnt)
                delta = sum(
                    1 for it in common if bool(next(r for r in v_rows if r["item"] == it)["ok"])
                ) - sum(1 for it in common if b_res[it])
                word = (
                    "beats"
                    if p < 0.05 and delta > 0
                    else "loses"
                    if p < 0.05 and delta < 0
                    else "ties-within-noise"
                )
                line += (
                    f" | vs bestof[{args.bestof_tag}] paired n={len(common)}: "
                    f"b={b_cnt} c={c_cnt} McNemar p={p:.3f} -> {word}"
                )
            else:
                line += f" | vs bestof[{args.bestof_tag}]: no paired items found"
        if heldout_gen:
            line += f" | heldout {heldout_gen}"
        line += (
            " | exploratory (public battery) — verdict-grade claims need a held-out batch"
            if not heldout_gen
            else ""
        )
        print(line + "\n", flush=True)
        return
    if args.mode == "loop":
        assert _hl is not None
        l_rows = [r for r in rows if r["phase"] == "loop"]
        res_n = sum(r["ok"] for r in l_rows)
        partial = len(l_rows) < n_items
        gen_tag = f" | heldout {heldout_gen}" if heldout_gen else ""
        part_tag = f" | PARTIAL ({len(l_rows)}/{n_items} items)" if partial else ""
        ci_tag = ""
        if l_rows:
            _arms = _load_battery("scripts/arms_summary.py")
            lo, hi = _arms.wilson(res_n, len(l_rows))
            ci_tag = f" | Wilson 95% CI [{lo:.2f}, {hi:.2f}]"
        print(
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: HARNESS {_hl.HARNESS_ID} "
            f"resolved {res_n}/{len(l_rows)}{ci_tag}{gen_tag}{part_tag}",
            flush=True,
        )
        if _rs:
            _rs.end(args.tag, "partial" if partial else "done", items_done=len(l_rows))
        return
    if args.mode == "bestof":
        b_rows = [r for r in rows if r["phase"] == "bestof"]
        print(
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: "
            f"best-of-{args.shots} {sum(r['ok'] for r in b_rows)}/{len(b_rows)}",
            flush=True,
        )
        return
    g_rows = [r for r in rows if r["phase"] == "greedy"]
    r_rows = [r for r in rows if r["phase"] == "retry06"]
    gs = sum(r["ok"] for r in g_rows)
    rs = gs + sum(r["ok"] for r in r_rows)
    if args.battery == "rsi":
        _arms = _load_battery("scripts/arms_summary.py")
        per_item = {}
        for r in rows:  # retry06 overwrites greedy per phase conventions
            if r["phase"] in ("greedy", "retry06"):
                per_item[r["item"]] = r
        fin = list(per_item.values())
        n = len(fin)
        res_n = sum(1 for r in fin if r.get("resolve_ok"))
        lo, hi = _arms.wilson(res_n, n)
        mean_rsi = sum(r.get("rsi", 0.0) for r in fin) / n if n else 0.0
        regs = sum(1 for r in fin if r.get("regression"))
        print(
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: "
            f"RSI resolve {res_n}/{n} | mean RSI {mean_rsi:.3f} | "
            f"regressions {regs} | resolve Wilson 95% CI [{lo:.2f}, {hi:.2f}]",
            flush=True,
        )
        return
    if args.battery in ("cbi", "cmi", "sli"):
        _arms = _load_battery("scripts/arms_summary.py")
        lo, hi = _arms.wilson(rs, len(g_rows))
        label = {"cbi": "CBI", "cmi": "CMI", "sli": "SLI"}[args.battery]
        print(
            f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: "
            f"{label} {rs}/{len(g_rows)} | greedy {gs}/{len(g_rows)} | "
            f"with-retry {rs}/{len(g_rows)} | Wilson 95% CI [{lo:.2f}, {hi:.2f}]",
            flush=True,
        )
        if args.battery == "cbi":
            # spec 017 FR-003: the reliability table (curve data) + ECE with
            # direction + excluded fraction — machine-readable, panel-ward
            _cal = _load_battery("scripts/calibration.py")
            # final outcome per item: retry06 overwrites greedy per phase
            per_item = {}
            for r in rows:
                if r["phase"] in ("greedy", "retry06"):
                    per_item[r["item"]] = r
            ece = _cal.ece_table(
                [(r.get("stated_confidence"), r["ok"]) for r in per_item.values()]
            )
            ou = f"{ece['over_under']:+.4f}" if ece["over_under"] is not None else "n/a"
            print(
                f"ECE (spec 017): n={ece['n']} ECE={ece['ece']} "
                f"direction={ece['direction']} (over_under={ou}) "
                f"| excluded {ece['excluded']} rows ({ece['excluded_fraction']:.0%})"
                f" | buckets {ece['bucket_scheme']}",
                flush=True,
            )
            print("reliability table (bucket | n | mean stated | empirical accuracy):")
            for b in ece["buckets"]:
                ms = f"{b['mean_stated']:.0f}%" if b["mean_stated"] is not None else "—"
                acc = f"{b['accuracy']:.0f}%" if b["accuracy"] is not None else "—"
                print(f"  {b['bucket']} | {b['n']} | {ms} | {acc}")
            # FR-006: machine-readable curve data for the panel
            ece_path = f"results/fcb15-{args.tag}-ece.json"
            with open_or_die(ece_path, "w") as f:
                f.write(json.dumps({"tag": args.tag, "model": args.model, **ece}, indent=1) + "\n")
            print(f"curve data -> {ece_path}", flush=True)
        return
    print(
        f"\nSUMMARY {args.model} [{args.tag}]{hw_tag}: greedy {gs}/{len(g_rows)}"
        f" | with-retry {rs}/{len(g_rows)}",
        flush=True,
    )
    if _deep is not None:
        _arms = _load_battery("scripts/arms_summary.py")
        per_item = {}
        for r in rows:  # retry06 overwrites greedy per phase conventions
            if r["phase"] in ("greedy", "retry06"):
                per_item[r["item"]] = r
        fin = list(per_item.values())
        sh = [r for r in fin if r["ok"]]
        deep = [r for r in sh if r.get("deep_ok")]
        silent = [r for r in sh if r.get("silent_failure")]  # row field, not re-derived
        sfi = 100 * (1 - len(silent) / len(sh)) if sh else None
        if sh:
            lo, hi = _arms.wilson(len(silent), len(sh))
            print(
                f"DEEP {args.model} [{args.tag}]: shallow(with-retry) {len(sh)}/{len(fin)}"
                f" | deep {len(deep)}/{len(sh)} | silent-failures {len(silent)}"
                f" | SFI {sfi:.1f} (denominator {len(sh)} shallow-passes)"
                f" | SFI Wilson 95% CI [{100 * (1 - hi):.1f}, {100 * (1 - lo):.1f}]",
                flush=True,
            )
        else:
            print(
                f"DEEP {args.model} [{args.tag}]: insufficient shallow passes "
                f"({len(sh)}) — SFI not computed",
                flush=True,
            )


if __name__ == "__main__":
    main()
