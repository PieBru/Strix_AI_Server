# Serving profiles — named shapes of service per box

Status: **PROPOSAL (pre-development)**. Author: pi, 260930, on operator request.
Nothing here is implemented; every number below is either measured (dated) or marked
**INFERRED** and is re-measured by the gate this document's centre of gravity is.

---

## 1. The problem, from live state

As I write this (260930 09:4x) `systemctl --user list-units --state=active` on
strix-9ad3 returns:

```
acestep-serve  acestep-ui  comfyui-h3  Doctor  gradio-v6-relay  gufo-serve
h3-video-ui  ltx25-ui  power-sampler  qwen-image-test  whisper-stt
```

**No text LLM is serving.** Not on `:8080`, not on `:8082` — both refuse the
connection (`curl http://127.0.0.1:8080/health` → exit non-zero, no HTTP response;
same for `:8082`, probed 260930 09:5x). The `default`-alias
invariant in AGENTS.md ("both boxes always serve a `default` LLM") is currently
false, and nothing anywhere noticed, because the thing that would notice — the
Doctor — reports the arm as `?` and nobody reads a `?` as an alarm.

That is the whole case for this work. We now have five model families (text,
image, video, music, STT) across two boxes, with real co-residency constraints
between them, and the only thing that decides what is loaded is *which buttons
someone pressed most recently*. The constraints themselves live in prose:

| relation | where it is encoded today |
|---|---|
| `llama-llm` ⇄ `gufo-llm` ⇄ `gufo-serve` ⇄ `qwen-image-*` | **`Conflicts=` in the unit files** (the old cluster — the only real enforcement we have) |
| `27b-collm` must not coexist with an H3 render | AGENTS.md prose + a habit |
| `gemma-collm` is the arm that *does* fit beside an H3 render | AGENTS.md prose (measured 260926) |
| never `27b-collm` + ACE-Step + an H3 render at once | operator directive 260927, in prose |
| LTX-2.5 peaks 17.4 GiB GTT, so it wants the arms down | AGENTS.md, measured 260929 |
| `sos-collm` is the exception that fits beside everything | AGENTS.md, measured 260928 |

Prose does not survive a reboot, a `git checkout`, or a month. The first thing
this proposal does is move that matrix from prose into data that is checked.

## 2. What a profile is

A profile is **data**: a named set of units, one designated text arm, a declared
memory budget, and a gate that must have passed for that exact set, on that box,
recently.

```ini
# configs/profiles/lab-video.ini          (stdlib configparser, same shape as models.ini)
name        = lab-video
summary     = H3 + LTX video bench, Gemma as the arm that survives a render
start       = comfyui-h3 h3-video-ui ltx25-ui gemma-collm   # ALLOW-list: the only managed
                                                              # units this shape may run
text_arm    = gemma-collm            # the invariant, made a field instead of a sentence
budget_gtt_gib = 96                  # GiB we expect to be resident at peak, all models loaded
workload    = video                  # what the gate drives through the set (see §5)
gate_max_age_h = 168                 # a PASS older than this is a FAIL (weekly re-prove)
verified    =                        # "<when> <commit> <evidence.json>", written by the gate
```

**`start` is an allow-list, not a start-list** (operator ruling 260930, after reading the
first draft of these files). There is no `stop` key: every managed unit that is running and
is *not* named here comes down with the profile. Two reasons, one of them decisive.

- It fails in the safe direction. A unit added to this box next month is stopped by every
  existing profile until someone puts it in one — annoying. Under a deny-list it would
  survive every profile silently and be the reason a budget is wrong, which is the failure
  this whole feature exists to prevent.
- It deletes a duplicate source of truth. `apply` already has to enumerate the live units to
  price the budget, so "what to stop" was being written twice: once by hand in eight files,
  once by the probe that cannot be wrong.

Two files of state, both tiny:

- `~/.config/strix/profile` — one word: the profile this box is *meant* to be in.
  Read by the Doctor, the gate, and `pi-resume.sh`.
- `state/profile-<box>-<profile>.json` — the gate's **evidence** (§5). This is the
  only thing that entitles a profile to claim "verified".

`current` is answered by **cross-checking both**, never by trusting either: stamp
says `lab-video`, live units say something else → that is *drift*, and drift is a
finding, not a silent state. (Sealed rule 260930: silence is not success; here the
inverse also holds — a stamp is not a state.)

## 3. The profiles

Base profiles are the ones that must work flawlessly; emergency profiles are the
ones that must work when nothing else does.

| profile | box | text arm | also loaded | intent |
|---|---|---|---|---|
| **`panic`** | both | `sos-collm` (4B Q4) | *nothing else* | The box is broken. One 2.4 GB model, boots in <5 s, 61.6 t/s, tool calls work. An agent can log in, read, think, and fix. |
| **`emergency`** | both | `27b-collm` (Q8 ≥ Q4 floor) | nothing else | Known-good big arm. Enough to keep working, and to repair into any other profile. |
| **`coding`** | strixy2 (primary) | flash-next Q4 + MTP + mmproj, 256k | nothing else | The boring serving shape. This is what strixy2 must boot into and stay in. |
| **`lab-image`** | strixy-9ad3 | `gemma-collm` | `gufo-serve` + `qwen-image-test` | Qwen-Image-2.1 work with a chat arm beside it. |
| **`lab-video`** | strixy-9ad3 | `gemma-collm` | `comfyui-h3` + `h3-video-ui` + `ltx25-ui` | The shape we have been doing by hand all week. |
| **`lab-audio`** | strixy-9ad3 | `gemma-collm` | `acestep-serve` + `acestep-ui` + `whisper-stt` | Music + STT. |
| **`lab-all`** | strixy-9ad3 | `gemma-collm` | everything above | **EXPERIMENTAL.** The de-facto state right now. Allowed only because the gate says so, and the gate will probably say no. |
| **`off`** | both | none | `Doctor` + `power-sampler` only | Maintenance, disk work, a flash. Deliberately violates the text-arm invariant, and says so. |

Rules the table encodes:

- **Every profile names a text arm** except `off`, which names its violation.
  `panic` is the floor: an agent must always be able to bootstrap the box.
- **`panic` and `emergency` are hardcoded in the tool**, not only in the file. If
  `profiles.ini` is corrupt, missing, or half-written, `strix-profile apply panic`
  must still work. A recovery path that depends on the config it is recovering
  from is not a recovery path.
- **`panic` binds `:8080`.** `sos-collm` lives on `:8082` today, which is correct
  for co-residency but wrong for panic: every client, pi config, and habit points
  at `:8080`. In `panic` it starts with a drop-in that moves it to `:8080` with
  `--alias default,sos,emergency`. (Open decision, §12.1.)
- **strixy2 keeps three profiles, maximum** (`coding`, `emergency`, `panic`). It is
  the reliable API; lab shapes do not go there.

## 4. Apply: `systemctl enable --now` / `disable --now`, nothing invented

`scripts/strix-profile` (one Python file, stdlib) is the only actor:

```
strix-profile current                 # stamp vs live, with drift called out
strix-profile list                    # profiles + last gate verdict + age per box
strix-profile apply lab-video         # the one that changes the system
strix-profile apply lab-video --dry-run
strix-profile rollback                # back to the previously applied profile
strix-profile verify lab-video        # run the gate (§5) without changing anything
```

`apply` does, in order:

1. **Refuse** if the profile has no PASSing gate newer than `gate_max_age_h`,
   unless `--i-know` — the gate is not advisory, it is the admission ticket. Also
   refuse if `verified` names an evidence file whose unit set differs from `start`:
   the stamp was earned by a different box-shape than the one being applied.
2. Snapshot the current unit set to `state/profile-previous.json` (rollback data).
3. `systemctl --user disable --now <live managed units not in start>`, then
   `enable --now <start list>`. The stop set is **computed from the probe**, never read
   from the file — there is no `stop` key to be wrong about (§2).
   `enable` is what makes the profile survive a reboot — no new systemd concept,
   no target units, no generator. The boot state *is* the profile.
4. Wait for the text arm's `/health` and its functional probe, ceiling 180 s.
5. Write the stamp **last**. A stamp written before the system agrees is a lie
   waiting to be believed.
6. Any step fails → roll back to the snapshot, leave the stamp pointing at the
   profile that is actually live, and exit non-zero with the failing check named.

Mutual exclusion stays where it already works — `Conflicts=` — and gets extended
to the newer arms so the old cluster and the new arms cannot be up together by
accident. Profiles do not replace `Conflicts=`; they are the human-facing layer
that decides *which* of the mutually exclusive things this box wants today.

## 5. The gate — this is the actual product

Everything above is a dropdown and a stamp file. The value is here, and the
operator's requirement is the sharp part: *run all loaded models at the same
time* to prove the profile fits.

**Loading is necessary but not sufficient.** A set can load at 60 % GTT and die
the moment the video model actually renders — ACE-Step is *eager* (13 GB resident
from unit start, 260927) and the LTX renderer peaks at 17.4 GiB only mid-render
(260929). So the gate drives a **real, tiny workload through every model
simultaneously**, and measures the machine, not the logs:

| phase | what happens | measured |
|---|---|---|
| 0 preflight | static budget: Σ declared `budget_gtt` vs `mem_info_gtt_total` minus headroom | binary |
| 1 load | start the set, wait for each model to report ready | per-model seconds, peak GTT during load |
| 2 **concurrent work** | text arm: a tool-call round-trip · image: one 512² generation · video: one 25-frame 320×192 clip · music: one 10 s clip · STT: one 10 s transcript — **all in flight at once** | peak GTT, peak RSS, `MemAvailable` at peak |
| 3 pressure | hold phase 2 for 60 s | `pswpout`/`pswpin` delta from `/proc/vmstat`, `gpu_busy_percent`, temp, power |
| 4 aftermath | — | `journalctl -k` OOM lines, `dmesg` amdgpu error/fault/hang, unit `NRestarts` delta |

### 5.1 Concurrency is the requirement, so it is measured, not assumed

Operator rule 260930: co-residency **must** be verified by running every candidate in the
allow-list **at the same time**, to bound the risk of OOM and swap storms. Two things make
that harder than "start them all and read a number", and the gate has to defeat both:

- **Started ≠ loaded.** `27b-collm` runs the fork's `--lazy-mode on-direct`: its weights are
  paged in on demand, so a freshly started arm reports ready while pinning almost nothing.
  A gate that measures GTT after `is-active` would watch thirteen units sit at ~400 MiB and
  certify a shape that OOMs on the first real request. So phase 1 ends with a **residency
  floor assertion**: after each model's warm-up request, its process RSS plus GTT must have
  grown past a per-family minimum, or the run is `INCONCLUSIVE`, not `PASS`.
- **Sequential probes are not concurrency.** Issuing the five probes one after another
  measures five separate peaks. Phase 2 launches them together and the evidence records the
  **overlap window** — the interval in which all probes were simultaneously in flight. If
  that window is empty (one probe finished before another started, or one timed out), the
  run cannot claim co-residency and is recorded as `INCONCLUSIVE`.

The counters are read from the machine, verified readable on this box 260930 (baseline with
the lab idle: `gtt_used` 385 MiB, `MemAvailable` 114.5 GiB, `SwapFree` 31.5 of 32 GiB,
`Committed_AS` 16.3 GiB):

| what | path | unit |
|---|---|---|
| GTT resident / ceiling | `/sys/class/drm/card0/device/mem_info_gtt_used` / `_gtt_total` | bytes (ceiling here: 124 GiB) |
| visible VRAM | `mem_info_vram_used` / `_vram_total` | bytes (1 GiB — the budget knob is GTT, not VRAM) |
| RAM headroom | `MemAvailable` in `/proc/meminfo` | kB |
| swap written / read | `pswpout` / `pswpin` in `/proc/vmstat` | 4 KiB pages, cumulative — use deltas |
| swap in use | `SwapTotal` − `SwapFree` in `/proc/meminfo` | kB |
| GPU load | `/sys/class/drm/card0/device/gpu_busy_percent` | % |

Sampled at 1 Hz for the whole run, not only at the end: a swap storm that resolves before
the final read is exactly the event that must fail the gate.

Pass is binary, thresholds in `doctor.config` (retunable without touching code):

- peak GTT ≤ **88 %** of `gtt_total`
- `MemAvailable` ≥ **8 GiB** at peak
- swap written during phase 3 < **16 MiB** (a swap storm is minutes of pages; 16 MiB in 60 s is noise)
- **zero** OOM-kill lines, **zero** amdgpu fault/hang lines, **zero** unit restarts
- every model's probe answered inside its own latency budget (a model that
  answers in 400 s under load has "passed" nothing)

Evidence, not adjectives: the gate writes `state/profile-<box>-<profile>.json`
with the measured numbers, the per-probe latencies, the unit set it tested, and
the git SHA of this repo. `apply` and the Doctor read *that file*. A gate that
cannot write its evidence is treated as failed — **positive evidence only**.

Sabotage guard, per the standing rule: the gate must be shown to FAIL. The
reference sabotage is `lab-all` with `27b-collm` added — 27B Q8 + an H3 render is
a measured OOM (260926), so a gate that passes that set is broken and we will
know it.

## 6. The webui: one dropdown in the title row

`doctor/Doctor.py` already has everything needed: an `<h1>` title row, a
fixed-argv POST action pattern (`/llmtoggle`, `/imgtoggle`), a resident-models
reader (`_resident()`, live from `/proc`), and a 2 s sampler. The change is small:

```html
<h1>__HOST__ · system + inference
  <select id="prof" onchange="fetch('/profile?name='+this.value,{method:'POST'})…">
    __PROFILE_OPTIONS__            <!-- from configs/profiles/*.ini, current marked -->
  </select>
  <span class="up">__UPTIME__</span> … </h1>
```

- `POST /profile?name=X` → `Popen` the same `strix-profile apply` the CLI runs,
  detached (never block the request; the gate takes minutes). Fixed argv, the name
  validated against the profile files that exist — same posture as the existing
  buttons, LAN-trusted per 260911.
- The **loaded-models card** gains one line, and it is the line that makes the
  dropdown honest:

  ```
  profile  lab-video · applied 09:41 · gate PASS 260930 (peak GTT 84%, swap 2 MiB)
  resident gemma:12B·MTPd3·c131k   gufo:Qwen-Image-2.1   [DRIFT: ltx25-ui not in profile]
  ```

  `DRIFT` in the card is the point: the profile is a claim, `/proc` is the truth,
  and the card shows both plus the difference.
- A `verify now` button on that card re-runs the gate detached and lands its
  evidence in the same card when it finishes.

## 7. Doctor: periodic verification, cheap by default

New collector `collectors/c_profiles.py` in the doctor-dream set (runs in the
03:00 unattended pass, next to `c_serving.py`):

1. **Stamp vs live** — the drift check, every night, free.
2. **Gate freshness** — PASS older than `gate_max_age_h` → finding.
3. **Gate validity** — the evidence's unit set or repo SHA no longer matches the
   profile → the PASS is stale even if the clock says otherwise. Someone edited a
   unit file at 22:00; the profile is unverified again as of that moment.
4. **Text-arm invariant** — the profile's `text_arm` is up, answering, and
   serving `default`. (Tonight's real failure: nothing was serving and the
   dashboard said `?`.)
5. **Budget headroom** — re-read the measured peaks against current free memory;
   a disk that filled or a new unit that crept into `WantedBy=default.target`
   changes the arithmetic.
6. **Heavy re-prove** — the concurrent-workload gate is *not* nightly (it costs
   minutes of a serving GPU). It runs: on `apply`, weekly (`pi-doctor-profile-gate.timer`),
   and on any change to a unit file or `configs/profiles/*`.

Findings land in the existing `state/findings-*.json` → morning report → the
Doctor's error box, so "reported in some reliable way" is the same channel the
operator already reads, not a new one.

## 8. Budget table — what we know, and how fast it rots

Measured on this box (124 GiB unified, gfx1151, no discrete VRAM; GTT is the only
truth — `rocm-smi`'s VRAM% reads the 1 GiB carve-out and always says ~90 %):

| model / unit | footprint | how known |
|---|---|---|
| `sos-collm` Spark-X2.5-4B Q4 | **7 GB GTT** co-resident with 27b-collm + full lab stack; 61.6 t/s; loads <5 s | measured 260928 |
| `gemma-collm` Gemma4-12B-QAT + MTP | **PASS** alongside a MiniMax-H3 render; 60 GiB free at peak | measured 260926 |
| `27b-collm` Q8 + DFlash | **OOM** alongside a MiniMax-H3 render | measured 260926 |
| LTX-2.5 renderer | peaks **17.4 GiB GTT** mid-render | measured 260929 |
| `acestep-serve` | **~13 GB GTT resident from unit start** (eager, operator 260927); RTF 0.60 solo → 3.94 during an H3 render | measured 260927 |
| `whisper-stt` | CPU-only, ~2.6 GB RAM, coexists with everything | measured 260928 |
| `gufo-serve` Qwen-Image-2.1 | **INFERRED ~10–14 GB**, never isolated | not measured |

Two consequences, and they are the reason the gate exists rather than a table in
a doc:

1. The only unknown in the matrix is the one nobody ever measured alone.
2. Every number above is 1–4 days old and describes a different build, kernel, or
   checkout. **A budget table in a document is a snapshot that starts rotting the
   hour it is written** (AGENTS.md). So the table lives in the profile files as an
   *expectation*, and the gate re-measures it as *fact* on every apply.

## 9. Rollout, with pass/fail per step

| step | deliverable | passes when |
|---|---|---|
| 1 | `configs/profiles/*.ini` + `strix-profile current/list/apply --dry-run` | `strix-profile current` on both boxes prints the stamp, the live set, and correctly calls tonight's "no text arm" state a violation |
| 2 | `panic` + `emergency` real, on both boxes | `apply panic` from a box with everything running → sos answering `:8080` with a tool call in <60 s; `apply emergency` → 27B answering; both survive a reboot |
| 3 | the gate, `strix-profile verify` | gate PASSES `panic`/`emergency`/`coding`; gate **FAILS** the sabotage set (27b + H3 render); evidence JSON written with numbers |
| 4 | Doctor dropdown + profile line in the loaded-models card | browser-driven check (Playwright, per the rules — `curl` is not a check): select → units change → card shows the new profile and resident set; a hand-started unit shows as DRIFT |
| 5 | `c_profiles.py` in the nightly pass | a planted drift (start `27b-collm` by hand in a `lab-video` box) appears in the next morning report unprompted |
| 6 | lab profiles, one at a time, each gated | each PASSes the concurrent-workload gate on this box; `lab-all` is allowed to fail and that is a legitimate result |

Steps 1–3 are the useful half. The dropdown without the gate is a button that
rearranges OOMs faster than a human does.

## 10. Explicitly not doing

- **No new daemon.** The Doctor already samples every 2 s and the gate is a script.
- **No systemd targets, generators, or slice-based admission control.**
  `enable`/`disable` + `Conflicts=` already express "this set, at boot, mutually
  exclusive". A slice with `MemoryMax` is the right answer *after* the gate exists
  and we want the kernel to enforce what the gate measured — noted as the upgrade
  path, not built now.
- **No dependency solver / no automatic profile choice.** The operator picks the
  shape; the system's job is to make the pick honest, reversible, and verified.
- **No web framework, no database.** Two files and a `<select>`.
- **No auth.** LAN-trusted posture (260911) unchanged; the dropdown is POST-only
  with a validated fixed argv, exactly like the buttons already in the page.

## 11. What this buys, stated as outcomes

- A box never wakes up serving nothing: the text-arm invariant is a field, checked
  nightly, and `panic` is one dropdown away from any state, including a broken one.
- "Can these five models run together?" has a dated, numeric answer instead of a
  memory and a paragraph in AGENTS.md.
- A profile that was never gated cannot be applied, so the unverified path stops
  being the default path.
- Co-residency knowledge stops living in prose and starts living in files that a
  timer re-proves.

## 12. Open decisions (operator's to make, not mine to assume)

1. **`panic` on `:8080`** — move sos there via drop-in (clients keep working) or
   keep `:8082` and accept that panic needs a client-side endpoint change?
2. **Gate strictness on apply** — hard block without `--i-know`, or warn-and-apply?
   I propose hard block: the whole point is that the unverified path is not the
   default path.
3. **`lab-all`** — is it a profile we want to exist at all, or does wanting
   everything at once mean wanting a second box?
4. **Who may apply** — the same no-auth LAN posture as everything else, or is a
   profile switch (which can take the coding API down) in a different class?
5. **strixy2's boot profile** — pin `coding` as the only thing it can boot into
   (`WantedBy` only, no lab units installed there), so the reliable box cannot
   drift into a lab shape at all?
