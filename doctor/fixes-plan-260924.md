# Doctor fixes plan — 260924 (from DOCTOR_REPORT_260924, findings F1–F4 + backlog)

Ordered by severity. Tiers: **A** = config-only, reversible in one command;
**B** = skill/collector code (one pass, all in doctor-dream); **C** = policy
decisions owed by the operator. F4 needs no fix (watch tags already set).

## F1 (P1) — stop volunteering the monitor; gate second-model loads

**A1. `Doctor.service`: drop `OOMScoreAdjust=200`, add a cap.** 8 MB process
died before the 4.2 G hog. Fix = neutral adj + MemoryHigh so it is capped, not
volunteered:
```ini
# drop:    OOMScoreAdjust=200
# add:     MemoryHigh=256M
```
`systemctl --user daemon-reload && systemctl --user restart Doctor.service`.
Verify: `systemctl --user show Doctor.service -p OOMScoreAdjust -p MemoryHigh`
→ `0` / `268435456`.

**A2. `pi-doctor-dream.service`: same one line.** The agent pass itself runs
adj 200 + memory.max=max (live-confirmed in the report's post-promotion note).
Drop `OOMScoreAdjust=200`; add `MemoryHigh=4G` (pi + model calls live here;
202 MB current, 4 G ceiling is generous).

**A3. Launch gate for any second full-model load.** Both OOM rounds happened
when a second model was loaded at the PLE steady state (~2–4 G free). Wrapper
`~/bin/llama-gate`:
```bash
#!/bin/bash
# llama-gate MIN_GB CMD... — refuse to run CMD unless MemAvailable >= MIN_GB
need=$1; shift
avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
[ "$avail" -lt "$need" ] && { echo "REFUSED: ${avail}G avail < ${need}G — unload the resident arm first (doctor F1)"; exit 75; }
exec "$@"
```
Usage habit: `llama-gate 45 llama-cli …` for full-model loads (45 G ≈ weights
+ KV + headroom). Wire into future lab scripts; no existing workflow changes.

**C1. Margin policy (owed since 260922, now in 3 shapes).** Options:
(a) per-arm host working-set table + hard reserve in models.ini comments;
(b) serialize heavy passes behind a lock (`flock /tmp/llama-lab.lock`);
(c) accept the risk and rely on A1–A3. Operator picks; A1–A3 make (c)
viable but (b) is 3 lines for lab scripts.

## F2 (P2) — make the digest non-misleading (all in `collectors/c_inference.py`)

**B1. Phantom arm-swaps: pair by PID.** Current bug: any `loading model`
line pairs with the NEXT `model loaded` — a failed Q6 load leaves a stale
`load_start` that the next Q5 success consumes (200 phantom Q6 credits).
Fix: capture the pid (`llama-server\[(\d+)\]`), credit an arm load only when
`model loaded` comes from the SAME pid and that pid has no
`exited with status 1` in between. ~6 lines in `analyze()`.

**B2. Storm alerts: stamp first→last + liveness.** The 299-failure alert read
live for a 22 h-dead corpse. While scanning failures, keep first/last
timestamps; emit
`arm-load failure storm: N failed loads (first MM-DD hh:mm → last MM-DD hh:mm, stopped Xh ago)`.
Requires parsing the journal timestamp prefix already present on the lines.

**B3. Bucket example = dominant signature, not last line.** Group error lines
by normalized signature (strip digits/paths), pick the most frequent for the
"e.g." example (the 1-in-2061 context-exceed must not headline 7×234
load-OOMs). Lives in the journal/digest formatting pass.

## F3 (P2) — collector budget + session windowing

**B4. `c_upstream.py`: fetch in parallel.** 19 sources × 15 s sequential =
285 s worst case > the 180 s budget → deterministic rc=124, 44 h stale.
Stdlib fix:
```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(8) as ex: results = dict(zip(srcs, ex.map(fetch_safe, srcs)))
```
Plus print stale age in the STALE marker (`state/upstream.json` mtime in h).

**B5. `c_sessions.py`: window the records, not the files.** mtime-file filter
counts one long-lived session's whole history (535 phantom "hard stops").
Session jsonl records carry timestamps — filter per record `ts >= cutoff`.
The 260923 closure of this item was never verified; re-verify in-window
numbers after the fix, re-open if they disagree with "0 new friction".

## Backlog (3) — wrong-file verify

**B6.** The arm-switch carry item greps `models-router.ini` (55 KB lab
library, never auto-closes) instead of the live `models.ini`. One-line edit
in `state/carry.json` verify field.

## Execution order (on go)
A1 → A2 → A3 (config, reversible, kills the P1 recurrence) →
B6 (one line) → B1 → B2 (same file) → B4 → B5 → B3.
Success gate: next nightly digest shows upstream refreshed, storms stamped
with first/last, no phantom swaps, in-window session counters; a manual
`systemctl --user show` check confirms both units' OOM policy.
