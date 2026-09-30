# Serving Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "which models this box serves right now" a named, applied, and *measurably verified* profile, with a dropdown in the Doctor and a nightly collector that reports drift and stale verification.

**Architecture:** Three pieces, no new daemon. `scripts/strix-profile` is the only actor (reads `configs/profiles/*.ini`, drives `systemctl --user enable/disable`, writes a stamp last). `scripts/profile-gate.py` is the only judge (loads a profile's set, drives a tiny real workload through every model at once, measures the machine, writes numeric evidence JSON). Everything else — the Doctor dropdown and the `c_profiles.py` collector — reads those two artifacts and never decides anything itself.

**Tech Stack:** Python 3.12 stdlib only (`configparser`, `subprocess`, `threading`, `http.server` for stubs, `urllib`). Bash for the systemd glue. INI for profiles and thresholds. No new dependencies, no pytest, no web framework.

**Spec:** `proposals/serving-profiles-260930.md` — read it first; this plan argues from it and does not restate its reasoning.

Location note: the plan lives beside its spec in `proposals/` rather than `docs/superpowers/plans/`, because this repo keeps every pre-development `.md` in `proposals/` and has no `docs/` tree.

> **Status 260930 (dated snapshot — read the commits, not this box).** Tasks 1–8 built on
> branch `feat/serving-profiles`, TDD throughout (each step's test written failing first,
> sabotage confirmed). The branch is checked out as a **git worktree** at
> `~/Piero/Work/serving-profiles` (same repository as this checkout, `cat` its `.git`), so the
> code is visible from here with `git show feat/serving-profiles:scripts/strix-profile`.
> `scripts/strix-profile`, `scripts/profile-gate.py`, `scripts/profile_probes.py`,
> `doctor/Doctor.py`, `doctor/profile_pw_check.py`, `configs/profiles/*.ini` (8 files) and the
> four `tests/*_check.py` are on that branch, newest commit `e77f794`. The nightly collector is
> Task 9's and lives where collectors live:
> `~/.pi/agent/skills/doctor-dream/collectors/c_profiles.py`.
> Measured on strix-9ad3: `panic`, `emergency`, `coding` and `lab-video` all gated **PASS**
> (27 B alone: GTT peak 35.11 %, tool call 4.35 s; **coding** — 27 B + image + music + STT
> concurrently: 66.69 %, min mem_avail 26.4 GiB, **swap 0.0 MiB**, 4/4 resident; lab-video:
> 40.11 %, swap 0.04 MiB); browser switch `lab-video -> panic -> lab-video` verified
> against a real Chromium with `systemctl` read back outside the page. The step boxes below are
> NOT ticked — the commits are the record.
> Gating `coding` (the heaviest set, slowest to load) exposed and fixed two gate bugs in the
> same commit `d01bda3`: readiness was a TCP connect, so a cold arm answering 503 mid-load was
> declared ready and its probe failed in 0.01 s; and the gate started its own units without
> stopping the rest, so it could measure two profiles at once and blame the wrong one. Both had
> produced false FAILs. `coding` and `lab-video` now carry `verified` stamps pointing at their
> evidence files; the other six stay empty and say why.
> The **unbreakable watchdog** (operator directive 260930) is built on the same branch —
> `scripts/strix-watchdog.py` + `systemd/strix-watchdog.{service,timer}`, drilled, installed in
> `~/.config/systemd/user/` and **left disabled**: its `ExecStart` points at this worktree, so
> arming it before the branch lands on `main` would tie an always-on actor to a path that a
> branch switch can remove. See §9 of `UNBREAKABLE_WATCHDOG_PROPOSAL_260930.md` for the drill
> table and what is still un-run.
> Remaining: Task 10 (strixy2: profiles + gate its champion — host unreachable 260930) and
> Task 11 (nightly gate + `coding` evidence on both boxes).

## Global Constraints

- **Python is never bare.** Run everything as `uv run --no-project python <file>` (repo rule: bare `python` is the wrong interpreter). No third-party imports in `strix-profile` or `profile-gate.py` — stdlib only, so a broken venv can never take the recovery path down with it.
- **Checks are stdlib assert scripts, not a framework.** Follow the `acestep/check.py` / `sos/check.py` idiom: a module docstring showing the exact run command, `assert`-based `--self-test`, `print("SELF-TEST OK")`, `sys.exit(main())`.
- **Positive evidence only** (operator-sealed 260930). No function may conclude success from an empty error list, from a zero exit code alone, or from "the process is alive". Every pass is a counted OK, a measured number, or an artifact that exists at the expected size.
- **Never block the operator.** Any gate run is launched detached (`setsid nohup … > /tmp/x.log 2>&1 &`) and polled; nothing in the Doctor's request path waits on a model.
- **Config is sacred.** Profile and threshold writes go through temp-file + `os.replace`, and are re-parsed after the write.
- **Paths, verbatim:** profiles `~/Piero/Work/Strix_AI_Server/configs/profiles/*.ini`; stamp `~/.config/strix/profile`; evidence `~/.local/state/strix/profiles/<box>-<profile>.json`; previous-set snapshot `~/.local/state/strix/previous.json`; thresholds `~/.pi/agent/skills/doctor-dream/doctor.config`.
- **Unit names are the ones on disk today** (`27b-collm`, `gemma-collm`, `sos-collm`, `llama-llm`, `gufo-llm`, `gufo-serve`, `qwen-image-test`, `comfyui-h3`, `h3-video-ui`, `acestep-serve`, `acestep-ui`, `whisper-stt`, `ltx25-ui`), `.service` suffix omitted in the INI.
- **Threshold defaults, verbatim:** `PROFILE_GTT_PCT_MAX=88`, `PROFILE_MEM_AVAIL_MIN_MIB=8192`, `PROFILE_SWAP_MAX_MIB=16`, `PROFILE_GATE_MAX_AGE_H=168`, `PROFILE_PROBE_TIMEOUT_S=300`.

## Seal Gates (operator decisions that block a step, not the whole plan)

The spec's §12 decisions are unresolved. Each is defaulted so work can proceed; the default is marked and the blocked step names it.

| # | decision | default used by this plan | blocks |
|---|---|---|---|
| D1 | `panic` binds `:8080` or stays `:8082` | stays `:8082`; `panic` profile records `text_port = 8082` and the Doctor links to it | Task 11 only |
| D2 | apply hard-blocks without a fresh PASS | **hard block**, `--i-know` overrides | Task 3 |
| D3 | does `lab-all` exist | exists, `experimental = true`, expected to fail its gate | Task 2 |
| D4 | same no-auth posture for `/profile` | yes, POST-only + name validated against files on disk | Task 7 |
| D5 | strixy2 pinned to `coding` | not pinned in this plan; strixy2 gets `coding`/`emergency`/`panic` only | Task 11 |

## Review Focus

Failure modes the spec implies that a happy-path implementation will not cover, each pinned by a named test in the task listed:

1. **A profile applied while a render is mid-flight** — the operator's 3 a.m. LTX job must not be silently killed by someone switching to `lab-image`. Expected: `apply` refuses unless `--force`, naming the busy unit. → Task 3 `test_apply_refuses_busy_gpu`.
2. **Partial apply** — three units started, the fourth OOMs. Expected: the stamp still names the *previous* profile and `rollback` restores it. → Task 3 `test_stamp_written_last_and_rollback`.
3. **A PASS that a later unit-file edit invalidated** — age alone is not staleness. Expected: the evidence carries a hash of the unit files it tested; a changed file makes the PASS invalid immediately. → Task 6 `test_evidence_unit_hash`, Task 9 `test_stale_after_unit_edit`.
4. **`panic` when the profile config is corrupt or missing** — the recovery path must not depend on the config it recovers from. Expected: `apply panic` works with `configs/profiles/` deleted. → Task 2 `test_panic_survives_missing_config`.
5. **A text arm that is up but useless** — a listening port is not a model. Expected: the probe requires a completion with non-empty content, and a tool call for arms declared `tools = true`. → Task 5 `test_probe_rejects_empty_completion`.

---

### Task 1: Profile loader and the truth-telling `current`

**Files:**
- Create: `scripts/strix-profile` (executable, `#!/usr/bin/env python3`)
- Test: `tests/strix_profile_check.py`

**Interfaces:**
- Produces:
  - `Profile` — dataclass with fields `name, summary, start: list[str], stop: list[str], text_arm: str | None, text_port: int, budget_gtt_gib: int, workload: str, gate_max_age_h: int, experimental: bool, tools: bool`
  - `load_profiles(dir: str) -> dict[str, Profile]` — raises `ProfileError` on a malformed file; a directory that is missing or unreadable yields `{}` plus a `ProfileError` from `require_profile()`, never a silent empty dict at call sites
  - `read_stamp(path: str) -> str | None`
  - `live_units(profile: Profile) -> tuple[set[str], set[str]]` → `(running_from_start_list, running_not_in_profile)`; the second set is only meaningful for units the tool manages (`MANAGED_UNITS`), so an unrelated user unit is never drift
  - `drift(profile: Profile, live: set[str]) -> dict` → `{"missing": [...], "extra": [...], "text_arm_up": bool}`
  - `main(argv) -> int` with subcommands `current`, `list`
- Constants: `PROFILES_DIR`, `STAMP`, `EVIDENCE_DIR`, `MANAGED_UNITS` (the 13 names from Global Constraints).

- [ ] **Step 1: Write the failing test.** In `tests/strix_profile_check.py`, build a fixture profile dir under `/tmp/strix-test/profiles/` with one valid INI and assert the loader's field types, then assert drift detection:

```python
def check_loader_and_drift():
    p = load_profiles(FIXTURE)["lab-video"]
    assert p.start == ["comfyui-h3", "gemma-collm"] and p.text_arm == "gemma-collm"
    assert p.gate_max_age_h == 168 and p.experimental is False
    d = drift(p, live={"gemma-collm", "open-webui"})
    assert d["missing"] == ["comfyui-h3"] and d["extra"] == []      # open-webui is unmanaged
    assert d["text_arm_up"] is True
    # a stamp naming a profile that does not exist is drift, not a crash
    assert drift(load_profiles(FIXTURE)["nope"], set()) or True     # raises ProfileError
```

Run `uv run --no-project python tests/strix_profile_check.py`; expect `NameError`/`ImportError` on `load_profiles`.

- [ ] **Step 2: Implement the loader and `current`.** `strix-profile` is importable as a module (`if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`) so the test imports it with `importlib.util.spec_from_file_location` — the file has no `.py` suffix on purpose, it is a user command.

`current` prints, and its exit code is part of its contract:

```
strix-9ad3  profile=lab-video (stamp 260930T09:41)
  running   comfyui-h3 gemma-collm
  missing   h3-video-ui ltx25-ui
  text arm  gemma-collm :8080 up
```
exit 0 = stamp parses, profile exists, no missing units, text arm up. exit 1 = any of those false, with the reason on the first line. `--json` emits the same dict the collector will consume.

- [ ] **Step 3: Run the test; expect PASS.** Also run it against the live box: `uv run --no-project python scripts/strix-profile current --json` must exit **1** right now, because this box has no text arm — that is the spec's §1 case and the first real assertion the tool makes about the world.
- [ ] **Step 4: Commit** `git add scripts/strix-profile tests/strix_profile_check.py` — message names the exit-code contract.

---

### Task 2: The profile files, and `panic` that survives a broken config

**Files:**
- Create: `configs/profiles/{panic,emergency,coding,lab-image,lab-video,lab-audio,lab-all,off}.ini`
- Modify: `scripts/strix-profile` (add `BUILTIN: dict[str, Profile]`)
- Test: `tests/strix_profile_check.py`

**Interfaces:**
- Consumes: `Profile`, `load_profiles` from Task 1.
- Produces: `BUILTIN` — `panic` and `emergency` defined in code, byte-identical to their INI files; `resolve(name) -> Profile` = file if present, else `BUILTIN`, else `ProfileError`.
- Produces: `check_profiles(dir) -> list[str]` — the integrity list `strix-profile check` prints (one line per problem, empty = clean).

- [ ] **Step 1: Write the failing tests.**

```python
def check_panic_survives_missing_config():
    assert resolve("panic", PROFILES_DIR="/nonexistent").start == ["sos-collm"]
    assert resolve("emergency", PROFILES_DIR="/nonexistent").text_arm == "27b-collm"

def check_profile_files_are_self_consistent():
    problems = check_profiles("configs/profiles")
    assert problems == [], problems
    # every profile names a text arm unless it declares the violation
    for n, p in load_profiles("configs/profiles").items():
        assert p.text_arm or n == "off", f"{n} serves no text model and does not declare it"
        assert set(p.start) <= set(sp.MANAGED_UNITS), f"{n} names a unit outside the allow-list"
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Write the eight INI files** using the field set from Task 1 plus `text_port`, `tools`, `experimental`. Content is the spec's §3 table; `lab-all` carries `experimental = true`. `check_profiles` verifies, for each file: required keys present, no unit in both lists, every named unit exists as `~/.config/systemd/user/<u>.service` **or** is in `BUILTIN`'s set, `text_arm` ∈ `start` ∪ {None}, `budget_gtt_gib` is an int > 0, and `panic`/`emergency` match `BUILTIN` exactly (a divergence here is the bug that bites at 3 a.m.).
- [ ] **Step 4: Run; expect PASS**, then `uv run --no-project python scripts/strix-profile check` on the live box prints nothing and exits 0.
- [ ] **Step 5: Commit.**

---

### Task 3: `apply` / `rollback` against a stub systemctl

**Files:**
- Modify: `scripts/strix-profile`
- Test: `tests/strix_profile_check.py`

**Interfaces:**
- Consumes: `resolve`, `read_stamp`, `live_units` (Task 1/2); `gate_verdict(box, profile) -> dict | None` (Task 6 — import it, and for this task inject a fake via the `verdict_fn` parameter).
- Produces:
  - `apply(name: str, *, dry_run=False, force=False, i_know=False, systemctl=_systemctl, verdict_fn=gate_verdict) -> int`
  - `snapshot(path=PREVIOUS, units: list[str]) -> None` / `rollback(*, systemctl=_systemctl) -> int`
  - `_systemctl(args: list[str], timeout=180) -> int` — the single place `systemctl` is ever called; argv is always a fixed list, never a shell string.
- Order is the contract: **gate check → snapshot → stop → start → wait-for-text-arm → write stamp.** A stamp written before the system agrees is a lie waiting to be believed.
- The stop set is **computed, never read**: `live ∩ (MANAGED_UNITS − profile.start)`, from the same probe that prices the budget (allow-list ruling 260930 — there is no `stop` key). `apply off` therefore stops all thirteen. Gate refusal also covers a `verified` stamp whose evidence unit set differs from `start`.

- [ ] **Step 1: Write the failing tests.** All three run against a stub `systemctl` injected as `systemctl=`; nothing touches the box.

```python
def test_apply_order_and_stamp_last():
    calls, stamps = [], []
    rc = apply("panic", systemctl=lambda a, timeout=180: calls.append(a) or 0,
               verdict_fn=lambda box, p: {"verdict": "PASS", "age_h": 1},
               stamp_write=lambda *a: stamps.append(a))
    assert rc == 0
    assert calls[0][:3] == ["disable", "--now"] and calls[-1][:2] == ["enable", "--now"]
    assert stamps, "stamp must be written, and only after the units"

def test_apply_refuses_busy_gpu():                      # Review Focus 1
    rc = apply("lab-image", systemctl=lambda a, timeout=180: 0,
               verdict_fn=lambda box, p: {"verdict": "PASS", "age_h": 1},
               busy=lambda: ["comfyui-h3"])
    assert rc == 1 and "comfyui-h3" in captured_err()
    assert apply("lab-image", force=True, ...) == 0

def test_stamp_written_last_and_rollback():             # Review Focus 2
    # the third start fails -> no stamp, previous profile restored
    ...
    assert read_stamp(TMP_STAMP) == "lab-video"          # unchanged, not "panic"
    assert rollback(systemctl=stub) == 0 and stub.wrote == ["enable", "--now", ...]

def test_apply_refuses_stale_gate_without_i_know():     # D2
    assert apply("lab-video", verdict_fn=lambda b, p: {"verdict": "PASS", "age_h": 400}) == 1
    assert apply("lab-video", i_know=True, verdict_fn=lambda b, p: {"verdict": "PASS", "age_h": 400}) == 0
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `busy()` is `gpu_busy_percent > PROFILE_BUSY_PCT` (default 20) **or** any unit in `RENDER_UNITS = ("comfyui-h3", "h3-video-ui", "ltx25-ui", "ltx25-serve")` having logged a start in the last 20 min — a render can be GPU-idle between steps and still be alive, so busy-ness alone is not the signal. `wait-for-text-arm` polls `http://127.0.0.1:<text_port>/health` **and** requires a non-empty completion (reuse Task 5's `probe_arm`; inject a stub here), ceiling 180 s.
- [ ] **Step 4: Run; expect PASS.** Then a real dry run on this box: `uv run --no-project python scripts/strix-profile apply emergency --dry-run` prints the exact `systemctl` argv it would run and changes nothing (`git`-clean, `systemctl --user is-active 27b-collm` still `inactive`).
- [ ] **Step 5: Commit.**

---

### Task 4: Measurement core with injectable sources

**Files:**
- Create: `scripts/profile-gate.py`
- Test: `tests/profile_gate_check.py`

**Interfaces:**
- Produces:
  - `Sample(gtt_pct: float, mem_avail_mib: int, swap_pages: int, gpu_pct: float)`
  - `read_sample() -> Sample` — `/sys/class/drm/card0/device/mem_info_gtt_used` ÷ `mem_info_gtt_total`, `/proc/meminfo` `MemAvailable`, `/proc/vmstat` `pswpin`+`pswpout`, `gpu_busy_percent`. GTT is the only GPU-memory truth on this box; `rocm-smi`'s VRAM% reads the 1 GiB carve-out and always says ~90 %.
  - `sampler(stop: threading.Event, out: list[Sample], interval=1.0)`
  - `verdict(samples, swap_delta_pages, oom_lines, amdgpu_lines, restarts, probes, cfg) -> dict` — pure function, no I/O, so the whole pass/fail rule is testable on synthetic input.
  - `load_cfg(path) -> dict[str, str]` — `KEY=value` lines, `#` comments.
- Thresholds come from `doctor.config` (Task 9 adds the keys); `verdict` takes them as `cfg` and never reads a file itself.

- [ ] **Step 1: Write the failing test** — the pass/fail rule as data, including each boundary:

```python
def check_verdict_boundaries():
    ok = [Sample(50, 20000, 0, 10), Sample(87.9, 8192, 0, 90)]
    assert verdict(ok, swap_delta_pages=16*256, oom_lines=[], amdgpu_lines=[],
                   restarts=0, probes={"text": {"ok": True}}, cfg=CFG)["verdict"] == "PASS"
    # each of these alone must flip it to FAIL, with the reason named
    for kw, why in [({"gtt_pct": 88.1}, "gtt"), ({"mem_avail_mib": 8191}, "mem"),
                    ({"swap": 17*256}, "swap"), ({"oom": ["Killed process"]}, "oom"),
                    ({"amdgpu": ["GPU fault"]}, "amdgpu"), ({"restarts": 1}, "restart"),
                    ({"probes": {"text": {"ok": False}}}, "text")]:
        v = verdict(**{**BASE, **kw})
        assert v["verdict"] == "FAIL" and why in " ".join(v["reasons"]), (kw, v)

def check_probe_latency_budget_counts():
    # a model that answers in 400 s under load has passed nothing
    assert verdict(**{**BASE, "probes": {"text": {"ok": True, "s": 400}}})["verdict"] == "FAIL"
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `read_sample` wraps each read in try/except returning `None` fields; `verdict` treats a missing measurement as **FAIL** with reason `"no <name> measurement"` — an unreadable metric is never a pass (Global Constraints).
- [ ] **Step 4: Run; expect PASS.** Sanity-check the real reader against the Doctor's own numbers: `uv run --no-project python -c "import importlib.util as u;s=u.spec_from_file_location('g','scripts/profile-gate.py');m=u.module_from_spec(s);s.loader.exec_module(m);print(m.read_sample())"` and compare `gtt_pct` with the Doctor's VRAM card — they must agree within a point, since both read the same sysfs pair.
- [ ] **Step 5: Commit.**

---

### Task 5: Functional probes — positive evidence per model family

**Files:**
- Create: `scripts/profile_probes.py`
- Test: `tests/profile_probes_check.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `probe(name: str, kind: str, cfg: dict) -> dict` → `{"ok": bool, "s": float, "detail": str}` where `kind ∈ {text, image, video, music, stt}`. Dispatch is a dict `PROBES = {"text": probe_text, ...}`.
- `probe_text(port, tools: bool)` — `POST /v1/chat/completions`, requires `choices[0].message.content` non-empty after strip; when `tools` is true, requires a parsed `tool_calls` entry whose `arguments` is valid JSON. This is the `sos/check.py` contract, reused rather than re-invented.
- `probe_image(port)` / `probe_video(port)` / `probe_music(port)` / `probe_stt(port)` — one tiny real generation each through the endpoint that unit actually serves (Qwen-Image `:8081`, ComfyUI `:8188` queue, ACE-Step engine `:8001`, whisper UI `:7863`), asserting the artifact is non-empty and decodes (a WAV with non-zero RMS, an image with non-zero bytes, a job that reaches `execution_success`).

- [ ] **Step 1: Write the failing test** against a stdlib `http.server` stub — no GPU, no model:

```python
def test_probe_rejects_empty_completion():               # Review Focus 5
    serve_once({"choices": [{"message": {"content": "   "}}]})
    assert probe_text(PORT, tools=False)["ok"] is False
    serve_once({"choices": [{"message": {"content": "hi", "tool_calls":
                       [{"function": {"name": "x", "arguments": "{not json"}}]}}]})
    assert probe_text(PORT, tools=True)["ok"] is False
    serve_once({"choices": [{"message": {"content": "hi", "tool_calls":
                       [{"function": {"name": "x", "arguments": "{\"a\":1}"}}]}}]})
    r = probe_text(PORT, tools=True)
    assert r["ok"] is True and r["s"] > 0
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Every probe has its own deadline from `PROFILE_PROBE_TIMEOUT_S`, scaled per kind by a `PROBE_BUDGET_S = {"text": 60, "image": 180, "video": 600, "music": 300, "stt": 120}` table; exceeding the budget returns `ok=False` with `detail="over budget"`, never a hang. A connection refused is `ok=False, detail="no listener"` — distinct from a timeout, because the operator reads `detail`.
- [ ] **Step 4: Run; expect PASS.** Then run the two probes that can run right now against the live box (`music`, `stt` are up): `uv run --no-project python -c "…probe('music','music',{})"` → `ok True`.
- [ ] **Step 5: Commit.**

---

### Task 6: The gate — concurrent workload, evidence JSON, sabotage

**Files:**
- Modify: `scripts/profile-gate.py`
- Test: `tests/profile_gate_check.py`

**Interfaces:**
- Consumes: `Profile`/`resolve` (Task 1/2), `read_sample`/`sampler`/`verdict`/`load_cfg` (Task 4), `probe` (Task 5).
- Produces:
  - `run_gate(profile: Profile, *, dry_run=False, hold_s=60) -> dict` — the evidence dict.
  - `gate_verdict(box: str, profile: str) -> dict | None` — reads the evidence file, returns it with `"age_h"` computed, or `None` if absent. **This is what Task 3's `apply` and Task 9's collector call.**
  - `unit_hash(units: list[str]) -> str` — sha256 over the concatenated contents of the unit files (and their `.d/` drop-ins) in sorted order.
- **Evidence schema, verbatim** (Doctor and collector both parse these keys; nothing else is authoritative):

```json
{"box": "strix-9ad3", "profile": "lab-video", "started": "260930T11:02:11+02:00",
 "duration_s": 412, "verdict": "PASS", "reasons": [],
 "units": ["comfyui-h3", "gemma-collm"], "unit_hash": "sha256:…", "repo_sha": "ceb8460",
 "peak_gtt_pct": 84.2, "min_mem_avail_mib": 19120, "swap_delta_mib": 2.1,
 "oom_lines": 0, "amdgpu_lines": 0, "unit_restarts": 0,
 "overlap_ms": 61234, "resident_units": 2, "samples": 412,
 "probes": {"text": {"ok": true, "s": 3.4}, "video": {"ok": true, "s": 118.0}}}
```

  `verdict` is one of `PASS` / `FAIL` / `INCONCLUSIVE`. `overlap_ms` is the interval in which
  every probe was simultaneously in flight; `resident_units` is how many units passed their
  residency floor; `samples` is the number of 1 Hz machine samples the peaks came from.
  Tasks 7 and 9 read the earlier keys only, so these three are additive.

- [ ] **Step 1: Write the failing tests.**

```python
def check_evidence_unit_hash():                          # Review Focus 3
    h = unit_hash(["gemma-collm"])
    # appending a drop-in must change the hash: a PASS predating that edit is void
    ...
    assert unit_hash(["gemma-collm"]) != h

def check_gate_writes_evidence_or_fails(tmp):
    # a gate that cannot write its evidence has failed, by definition
    assert run_gate(P, evidence_dir="/proc/nope")["verdict"] == "FAIL"

def check_concurrent_not_sequential():
    # the whole point: probes overlap in time
    started, finished = run_gate_recorded(P)
    assert max(started) < min(finished), "probes ran sequentially; the gate proves nothing"

def check_a_unit_that_never_loaded_is_inconclusive():      # operator rule 260930
    # 27b-collm runs --lazy-mode on-direct: is-active with 400 MiB pinned is NOT loaded.
    # Certifying that shape is worse than not testing — it licenses apply.
    r = run_gate(P, load=lambda u: ResidentRss(u, gib=0.4))   # started, weights absent
    assert r["verdict"] == "INCONCLUSIVE" and r["resident_units"] < len(P.start)

def check_no_overlap_window_is_inconclusive():
    # probes that never overlap measure five separate peaks, not one co-resident set
    r = run_gate(P, schedule="sequential")
    assert r["verdict"] == "INCONCLUSIVE" and r["overlap_ms"] == 0

def check_swap_storm_fails_even_if_it_settles():
    # a storm that resolves before the final read must still fail → sample at 1 Hz, judge on
    # the delta, never on the last sample
    r = run_gate(P, vmstat=[("pswpout", 0), ("pswpout", 9_000_000), ("pswpout", 9_000_010)])
    assert r["verdict"] == "FAIL" and "swap" in " ".join(r["reasons"])
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement the four phases** from spec §5 (preflight budget → load → concurrent work → 60 s pressure hold → aftermath scan). Phase 2 launches every probe in a `threading.Thread` and starts the sampler before the first one. Phase 4 is `journalctl -k --since <started> | grep -i 'killed process\|out of memory'` plus the amdgpu scan the Doctor already uses, and `systemctl show -p NRestarts` before/after each unit. `--dry-run` prints the plan and the budget arithmetic without starting a unit.

  **Concurrency is the requirement (operator 260930), so two rules are load-bearing:**

  1. **Residency floor per family, asserted before phase 2 measures anything.** A unit is
     `resident` only after its warm-up request AND its RSS plus system GTT have grown past
     the per-family minimum (`PROFILE_FLOOR_LLM_GIB`, `PROFILE_FLOOR_IMAGE_GIB`,
     `PROFILE_FLOOR_VIDEO_GIB`, `PROFILE_FLOOR_AUDIO_GIB` in `doctor.config`). Reason is on
     disk: `--lazy-mode on-direct` lets a 44 GiB arm report `active` at 400 MiB, and a gate
     that measured that would certify a shape that OOMs on first use. Any unit below its
     floor → `INCONCLUSIVE`, never `PASS`.
  2. **The overlap window is computed and recorded.** `overlap_ms = min(finish) - max(start)`
     over the probes that were launched; `<= 0` → `INCONCLUSIVE` with the reason naming which
     probe never overlapped.

  Sampler: 1 Hz for the whole run (spec §5.1 has the verified paths — `mem_info_gtt_used`,
  `MemAvailable`, `pswpin`/`pswpout` deltas, `gpu_busy_percent`). Peaks and deltas come from
  the sample series, never from a single end-of-run read.
- [ ] **Step 4: Run; expect PASS.** Then the **manual sabotage run** (spec §5, not automated — it costs a GPU minute and can OOM the box): `apply` a throwaway profile of `27b-collm` + `comfyui-h3` and confirm the gate **FAILS**. Record the observed peak in the commit message. A gate that passes this set is broken; stop and fix it before Task 7.
- [ ] **Step 5: Commit** with the sabotage observation quoted in the message.

---

### Task 7: Doctor — dropdown in the title row, profile line in the ARM card

**Files:**
- Modify: `doctor/Doctor.py:506` (the `<h1>`), `:394-405` (the ARM card), `:600-646` (`do_POST`)
- Test: `tests/doctor_profile_card_check.py`

**Interfaces:**
- Consumes: `load_profiles`, `read_stamp`, `drift` (import `scripts/strix-profile` by path, same `importlib` trick as Task 1), `gate_verdict` (Task 6).
- Produces: `POST /profile?name=<n>` → 200 `starting profile 'n'…` and a detached `strix-profile apply n`; `GET /profilestate` → the ARM-card fragment's profile line.
- The name is validated against `load_profiles()` keys **before** any subprocess call; an unknown name is 404 with no side effect (D4: no auth, but never an unvalidated argv).

- [ ] **Step 1: Write the failing test** — pure functions, no browser:

```python
def test_profile_line_shows_claim_truth_and_drift():
    h = profile_line_html(stamp="lab-video", live={"gemma-collm"},
                          missing=["comfyui-h3"], verdict={"verdict": "PASS", "age_h": 6,
                          "peak_gtt_pct": 84.2})
    assert "lab-video" in h and "PASS" in h and "DRIFT" in h and "comfyui-h3" in h
    assert "<script" not in h                                       # names are escaped
    assert profile_line_html(stamp=None, ...) .count("no profile") == 1

def test_unknown_profile_name_is_404_and_runs_nothing():
    assert post_profile("/profile?name=../../etc/passwd")[0] == 404
    assert subprocess_calls == []
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** In the `<h1>` insert `<select id="prof" onchange="profGo(this)">` with options from `load_profiles()` (current one `selected`, `panic` and `emergency` always present even if the dir is gone — same reason as Task 2). In the ARM card title, above `_pills`, insert `<div class="prof">__PROFILE_LINE__</div>`; the line is `profile <name> · applied <hh:mm> · gate <VERDICT> <date> (peak GTT <n>%)` and, when `drift()` is non-empty, `<span class="bad">DRIFT: …</span>`. The apply is `Popen(["/bin/bash","-c","sleep 1; …"], start_new_session=True)` exactly like `/restart`, so the request never waits on a model.
- [ ] **Step 4: Run; expect PASS**, then `systemctl --user restart Doctor && curl -s localhost:8667/stats | grep -o 'id="prof"'` returns a match and the page still renders (no exception in the log).
- [ ] **Step 5: Commit.**

---

### Task 8: Browser verification of the switch (not `curl`)

**Files:**
- Create: `doctor/profile_pw_check.py`

**Interfaces:**
- Consumes: the live Doctor on `:8667`, `strix-profile current`.
- Produces: an exit-0/1 browser check the operator can re-run. Repo rule: a web/UI change is not verified without driving the real flow.

- [ ] **Step 1: Write the check** with Playwright (`uv run --with playwright`, chromium already installed here): open `:8667`, assert the `<select>` exists and its selected option equals `strix-profile current`; select `panic`; assert the ARM card's profile line changes to `panic` within 90 s **and** that `systemctl --user is-active sos-collm` is `active`; assert a hand-started unmanaged unit does **not** appear as drift; screenshot to `/tmp/profile-ui.png`.
- [ ] **Step 2: Run it detached** (`setsid nohup … > /tmp/profile-pw.log 2>&1 &`), poll ≤55 s, read the log and the screenshot.
- [ ] **Step 3: Sabotage it** — point the check at a profile whose apply will fail (a name whose units cannot start) and confirm the check FAILS rather than timing out silently. Green tests that don't bite are theater.
- [ ] **Step 4: Restore the box** to whatever profile it was in before the check, and confirm with `strix-profile current` exit 0.
- [ ] **Step 5: Commit.**

---

### Task 9: `c_profiles.py` — the nightly report

**Files:**
- Create: `~/.pi/agent/skills/doctor-dream/collectors/c_profiles.py`
- Modify: `~/.pi/agent/skills/doctor-dream/gather_all.sh:17-19` (append to the collector loop), `doctor.config` (add the five `PROFILE_*` keys)
- Test: the collector's own `--self-test` branch

**Interfaces:**
- Consumes: `gate_verdict`, `load_profiles`, `drift`, `read_stamp`, `unit_hash` — imported from the repo by absolute path, so there is one implementation of each.
- Produces: `collect(hours: int) -> tuple[str, dict]` and `state/findings-profiles.json`, following the collector idiom exactly (`md` to stdout, json to `state/`, `--self-test` printing `SELF-TEST OK`, `sys.exit(main())`).

- [ ] **Step 1: Write the `--self-test` asserts** covering the five checks of spec §7 on fixtures:

```python
assert f["drift"]["missing"] == ["h3-video-ui"]
assert f["gate"]["status"] == "stale"          # age_h > gate_max_age_h
assert f["text_arm"]["up"] is False            # the "?" case must be a finding, not a shrug
assert any("unit edited after gate" in a for a in f["alerts"])   # Review Focus 3
assert f["budget"]["headroom_gib"] >= 0
```

- [ ] **Step 2: Run `--self-test`; expect FAIL.**
- [ ] **Step 3: Implement** the five checks, then wire it into `gather_all.sh` and add the `PROFILE_*` keys to `doctor.config` with a one-line comment each (config fields carry descriptions — repo rule).
- [ ] **Step 4: Run `--self-test`; expect PASS.** Then run it for real: `uv run --no-project python collectors/c_profiles.py --hours 24` must, on today's box, report the missing text arm as a finding — the same fact `strix-profile current` reports, arriving through the channel the operator actually reads.
- [ ] **Step 5: Commit** in **both** repos, which are separate (verified 260930: `doctor/Doctor.py` lives only in `Strix_AI_Server`; the collectors live only in `~/.pi/agent/skills/doctor-dream/`, inside the `~/.pi` git repo — they are not mirrors of each other). The collector imports `strix-profile` across that boundary, so pin the path once: `STRIX_REPO = os.environ.get("STRIX_REPO", os.path.expanduser("~/Piero/Work/Strix_AI_Server"))` and fail loudly with a named finding (`"strix repo not found"`) if it is absent — a collector that silently skips its checks is the silence-is-not-success failure again. Commit the collector to `~/.pi`, the thresholds and plan to `Strix_AI_Server`.

---

### Task 10: Re-prove on a timer, and on any unit edit

**Files:**
- Create: `~/.pi/agent/skills/doctor-dream/units/pi-doctor-profile-gate.timer`, `.service`
- Test: `systemd-analyze --user verify` on both files

- [ ] **Step 1: Write the timer** (`OnCalendar=Sun 09:00`, `Persistent=true`) and the service (`ExecStart=… profile-gate.py --profile-from-stamp`, `Type=oneshot`, `TimeoutStartSec=3600`, `Nice=10`).
- [ ] **Step 2: `systemd-analyze --user verify` both units; expect exit 0.**
- [ ] **Step 3: Unit-edit invalidation** lives in the collector (Task 9 check 3), not in a path unit — a `path` unit that fires a GPU-heavy gate on every `systemctl edit` would run the gate during the operator's own debugging. Note the ceiling in a `ponytail:` comment: invalidation is discovered at the next nightly pass, not instantly; upgrade path is a `.path` unit if that lag ever matters.
- [ ] **Step 4: Enable the timer**, `systemctl --user list-timers` shows it, and `systemctl --user start pi-doctor-profile-gate.service` runs one real gate against the stamp's profile without leaving the arms down (verify with `is-active` after).
- [ ] **Step 5: Commit.**

---

### Task 11: Land the profiles on both boxes

Blocked on D1 and D5. This task changes what the boxes serve; do it when the operator is watching.

- [ ] **Step 1:** Resolve D1 (`panic` on `:8080` or `:8082`) and D5 (strixy2 pinned to `coding`) with the operator; edit the two INI files accordingly.
- [ ] **Step 2:** Gate `panic`, `emergency`, `coding` on strixy-9ad3; each must write a PASS evidence file. Then apply each once and confirm `strix-profile current` exits 0.
- [ ] **Step 3:** Same three on strixy2 (`ssh` + the repo's copy). strixy2 must end in `coding`, its `/v1/models` answering as `default`, and survive a reboot into it (`sudo reboot`, wait, re-probe — the operator's call on timing).
- [ ] **Step 4:** Extend `Conflicts=` to the arms that lack it (`27b-collm`, `gemma-collm`, `sos-collm` vs `gufo-serve`/`qwen-image-test`) so the old cluster and the new arms cannot coexist by accident. `daemon-reload`, then prove it: with `gufo-serve` active, `systemctl --user start 27b-collm` must take `gufo-serve` down.
- [ ] **Step 5:** Lab profiles one at a time, gated, in this order: `lab-image`, `lab-audio`, `lab-video`, then `lab-all`. A FAIL on `lab-all` is a legitimate result — record it in the evidence and in AGENTS.md's lab section, do not "fix" the gate to make it pass.
- [ ] **Step 6:** Update AGENTS.md: the LAN inventory (unchanged ports), the arms list (which profile owns which arm), and delete the prose co-residency rules that the profiles now enforce — leaving both is how the next agent reads a stale sentence as truth.

---

## Self-Review Notes

- **Spec coverage:** §2 loader/stamp/evidence → Tasks 1-2, 6. §3 profile table → Task 2. §4 apply/rollback/`Conflicts=` → Tasks 3, 11. §5 gate + sabotage → Tasks 4-6. §6 webui → Tasks 7-8. §7 collector + re-prove cadence → Tasks 9-10. §9 rollout → Tasks 1-11 in order. §12 decisions → Seal Gates table. No spec requirement is unassigned.
- **Proportion:** the plan is shorter than the spec it implements; bodies are signatures plus assertions, and the only long block is the evidence schema, which three components must agree on verbatim.
- **Type consistency:** `gate_verdict(box, profile) -> dict | None` is defined in Task 6 and consumed by Tasks 3, 7, 9 with that name and shape; `drift()` returns the same `missing`/`extra`/`text_arm_up` keys in Tasks 1, 7, 9; `unit_hash` is defined once (Task 6) and consumed by Task 9.
- **Deliberate omissions:** no systemd targets, no admission control via slices, no automatic profile selection, no auth, no database — per spec §10. The slice-based `MemoryMax` enforcement is the named upgrade path once the gate's measured peaks exist as data.
