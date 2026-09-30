# Unbreakable watchdog — the box must always answer a text request

Operator directive 260930: *"the emergency and sos model loading should be managed by a
dedicated 'unbreakable' (extremely reliable) systemd service that periodically monitors the
current availability of the 'default' model and, if it isn't provided or isn't replying in a
reasonable time, loads the emergency model then verifies it works and, if it doesn't work or
doesn't reply in a reasonable time, loads and verifies the 'sos' model as the last-chance
fallback."*

This is a design proposal, not an implementation. Nothing here is built yet.

## 1. What already exists (checked 260930, do not rebuild it)

| thing | state |
|---|---|
| `night-watchdog.service` + `.timer` (every 10 min → `~/.local/bin/watchdog.sh`, 47 lines) | **timer inactive**. Its first check is `is-active model-router-pwilkin \|\| model-router-vanilla`; both units are gone, so `ANOMALY` is set on **every** tick. Enabled as-is it escalates to a headless `pi` every 30 min forever. |
| its health test | `curl -m8 :8080/health \| grep '"ok"'` — liveness only. `/health` answers 200 on a wedged generation loop; this is the exact signal that lies. |
| escalation | `timeout 1200 pi -p "OVERNIGHT WATCHDOG ALERT …"` with a 30-min lockfile. An LLM as the *first* responder is the wrong order; it belongs last. |
| `emergency.ini` | `27b-collm` alone, `:8080`, `budget_gtt_gib = 100`. |
| `panic.ini` | `sos-collm` only, `:8082`, `budget_gtt_gib = 8`. |
| `sos-collm` | Spark-X2.5-4B Q4_K_M, `:8082`, aliases `sos`/`emergency`, loads < 5 s, 7 GB GTT, measured co-resident with `27b-collm` + the full lab stack. |
| `probe_text` (Task 5) | real chat completion **with a tool call**, proven on this box: gemma answered `run_shell({"command":"df -h /"})` in 5.36 s *while an H3 render held the GPU*. |
| `gate_verdict` / evidence JSON (Task 6) | per-box, per-profile PASS/FAIL with age. |
| `apply --force` | reaches an **ungated** profile (ac98974); a measured FAIL still refuses it. |

So the ladder the operator described is already expressible as: **restart the declared arm →
`apply emergency` → `apply panic`**, and the probe already exists. The new part is the
supervisor and its refusal rules.

## 2. The contract is the stamp, not ":8080 is up"

The single rule that keeps this from being a menace:

> **No stamp → the watchdog does nothing.**

`~/.config/strix/profile` is the operator's declaration of intent. Its absence means the box
was put into a shape by hand — image mode, an H3 render, an experiment eating the GPU — and a
watchdog that "helpfully" starts a 40 GiB arm at 03:00 is an OOM killer with good intentions.
(AGENTS.md, 260927: *never stack 27b-collm + ACE-Step + an H3 render*.)

With a stamp, "should be true" is read from the profile, never hardcoded:

- `profile.text_arm` answers on `profile.text_port`, **and**
- `GET :<port>/v1/models` lists the `default` alias (AGENTS.md: which arm answers is never
  recorded, ask the endpoint), **and**
- a functional probe completes inside budget.

`panic` is a legitimate steady state (`text_arm = sos-collm`, `:8082`), so the watchdog must be
able to hold *that* state too — it is not only a recovery mechanism, it is the enforcement
mechanism for whatever the stamp says.

## 3. Probe: functional, with a budget that survives a busy box

`/health` is a hint, not proof. The probe is `probe_text`: one chat completion that must
produce either non-empty content or a well-formed `tool_calls`, with a wall budget.

The budget is the hard part, because "slow" and "dead" look identical from one sample:

- a 40 k-token prompt prefill takes tens of seconds on the 27 B arm;
- a render in flight steals memory bandwidth (measured: ACE-Step RTF 0.60 solo → **3.94**
  during an H3 render, still completes);
- a cold arm answers nothing at all until the weights are mapped (tens of seconds; the gate
  learned this the hard way — systemd says `active` the instant it execs).

Rules, therefore:

1. **N consecutive failures before acting** (propose 3, one per tick, 3 min window). One slow
   sample is never an action.
2. **Never act while the ComfyUI queue is running** (`GET :8188/queue`, `queue_running`
   non-empty) *unless* the declared arm is fully absent (no listener). A slow arm during a
   render is expected; killing it mid-render is the bug we are trying to avoid.
3. **Distinguish "no listener" from "listener, no reply"**: the first is a dead unit (restart
   it), the second is a wedged process (restart it) or a saturated box (wait). `ss` for the
   port, then the probe.
4. **Budget scales with what is running**: `budget = base + (render_running ? k : 0)`.
   Concretely: base 60 s, 180 s while the GPU is busy. Numbers to be measured, not shipped as
   guesses — the first task is to record real p50/p95 completion times per arm, cold and warm,
   idle and mid-render.

## 4. The ladder

```
tier 0  declared arm answers on its port with the default alias        → nothing
tier 1  systemctl --user restart <declared arm>, wait for listener, re-probe
tier 2  strix-profile apply emergency --force     (champion alone, :8080)
tier 3  strix-profile apply panic --force         (sos-collm, :8082, loads < 5 s)
tier 4  give up: journal + Doctor banner + the existing headless-pi escalation (1 / 30 min)
```

Each tier is followed by the **same functional probe**; a tier that does not verify does not
count as done, it advances. Every action is journalled with the probe output that justified it.

**One open design question, and it matters.** `emergency.ini` is the *champion* (27 B, 100 GiB
budget). That is the right answer to "the box is contended but healthy" and the wrong answer to
"the box is out of memory / the GPU is wedged" — which is the failure a watchdog most often
meets. The documented capacity fallback is `gemma-collm` (measured: 27 B-Q8 **OOM** alongside a
MiniMax-H3 render, Gemma4 **PASS**, 60 Gi free at peak). Options:

- (a) pick the tier by failure mode: `no listener` / `restart failed` → gemma; `wedged but
  memory fine` → champion;
- (b) re-scope `emergency.ini` to `gemma-collm` and let the champion be what `coding`/`lab-*`
  already declare;
- (c) leave it and accept that tier 2 can fail on a memory-starved box (tier 3 still saves it).

Recommendation: **(b)** — `emergency` should be the shape that is *known to fit*, which is what
its own comment claims ("the shape that is known to fit and answers a coding question in
seconds"), and 27 B + 100 GiB is not that shape on a box that is already short. This is a
profile-semantics change, so it is the operator's seal, not mine.

## 5. Anti-thrash (this is where watchdogs go wrong)

- **One action per tick.** Never restart-and-apply in the same pass.
- **Cooldown after acting** (propose 15 min) before the next tier, so a load gets its chance.
- **No auto-restore.** After falling back, stay fallen back. Restoring the champion is an
  operator decision (or a separate, explicitly-timer'd "re-attempt primary at 07:00"), because
  a box that flaps between 27 B and 4 B every 10 minutes is worse than either.
- **Escalate the ceiling, not the frequency**: if the same tier is reached K times in a day,
  stop acting and shout (Doctor banner + journal `ERROR`), because the failure is structural.
- **Idempotent**: every action is `systemctl`/`apply`, both of which are safe to repeat; no
  hand-rolled stop-start sequences in the watchdog itself.
- **A wall-clock ceiling on the watchdog's own work** and break-on-repeat (AGENTS.md: unguarded
  loops hang the system).

## 6. Making the watchdog itself hard to break

The failure mode to design against is the one already recorded on this box: *a unit that has
only ever started with internet is untested* (`uv run --with X` re-resolves against pypi on a
cold start → `status=2/INVALIDARGUMENT` restart loop with the LAN down).

- **stdlib-only `python3`**, no `uv`, no `--with`, no venv, no network at start. The probe is
  `urllib`; the actions are `systemctl` and `strix-profile`.
- **`WorkingDirectory=/`** (or any path no checkout can remove) — the `acestep-ui` lesson: a
  unit whose cwd is inside the repo dies on `os.getcwd()` after a branch switch, while the site
  keeps serving from the deleted inode.
- `Restart=always`, `RestartSec=30`, and **`WatchdogSec=300`** with `sd_notify`
  (`Type=notify`) so systemd kills a watchdog that itself hangs. Without this the watchdog is
  just another process that can die quietly.
- Read the profile library by path (`importlib`, the trick already used by Doctor and the
  tests) rather than importing an installed package — one source of truth for `resolve`,
  `live_units`, `probe_text`.
- **Never write config destructively**: state in `~/.local/state/strix/watchdog.json`, temp +
  atomic replace.
- Its own failure must be visible: Doctor shows `watchdog: last tick <age>, actions: n` — a
  dead watchdog is exactly the thing nobody notices.
- It must survive the operator: an explicit **`STRIX_WATCHDOG=off`** env /
  `~/.config/strix/watchdog.disable` file, checked every tick, for the hours when the operator
  *wants* the box in a shape the stamp does not describe.

## 7. Interaction with the gate (the trap)

`apply` refuses without gate evidence. `--force` now reaches an ungated profile (ac98974) but
**still refuses a measured FAIL** — deliberately: force means "I know better than the absence
of a test", not "I know better than a measurement".

Consequences for the ladder:

- `panic` has never been gated on this box → tier 3 works via `--force`. Good.
- `emergency` (27 B) **has** a measured FAIL beside it: the sabotage run FAILed 27b-collm +
  comfyui-h3 with a swap storm. If `emergency.ini` keeps the champion *and* the box still runs
  ComfyUI, tier 2 is refused by evidence — correctly! That is the OOM we measured.
- Therefore the watchdog must **not** paper over a FAIL with force. If a tier is refused by
  evidence, it advances to the next tier instead of overriding.

## 8. Shape (as small as it can be)

One file, `scripts/strix-watchdog.py`, ~120 lines:

```
tick():
    if disabled(): return
    stamp = read_stamp();  if not stamp: return          # contract
    prof = resolve(stamp)
    if probe(prof.text_arm, prof.text_port, budget()):   reset_failures(); return
    failures += 1
    if failures < N: return
    if queue_running() and listener_up(prof): return     # slow ≠ dead
    act(next_tier())                                     # one action, journalled
```

plus `strix-watchdog.service` (`Type=notify`, `WatchdogSec=300`, `Restart=always`) reusing the
existing `night-watchdog.timer` cadence, and the headless-`pi` escalation kept as tier 4 with
its 30-min lockfile.

## 9. Tasks, in order

1. **Measure before tuning**: record completion times per arm (cold/warm × idle/mid-render) so
   the budget and N are numbers, not vibes. Pass/fail: a table in this file with real seconds.
2. `strix-watchdog.py` with the tick above + a `--dry-run` that prints the action it *would*
   take and never touches systemd. Tests: pure functions (`decide(state) → action`) with an
   injected clock/probe/spawn, including "stamp absent → nothing", "slow but queue busy →
   wait", "FAIL evidence → advance, never force".
3. Unit + timer, `WatchdogSec`, `WorkingDirectory=/`, stdlib only. Pass/fail: `systemctl
   --user start` with the LAN **down** and the repo on a branch without the file's directory.
4. Kill drills, in order of violence: `kill -9` the arm (expect tier 1), stop the arm and hold
   memory (expect tier 2/3), wedge it with a 40 k prompt (expect *no* action). Pass/fail: the
   journalled action table, not a log that looks alive.
5. Doctor: one line for the watchdog (last tick, current tier, actions today).

## 10. Explicitly out of scope

- Fixing anything the operator did by hand (no stamp → no action, forever).
- Auto-restoring the primary profile.
- Any network dependency, any auth, any cloud.
- Replacing the gate: the watchdog consumes gate evidence, it never produces it.
