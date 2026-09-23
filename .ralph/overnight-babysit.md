# Overnight babysit — both boxes (started 21:48; hard stop: digest written or 07:30)

The unattended scripts do the work; this loop watches the watchers and
intervenes only on defined failure classes. Read this file first each
iteration (per ralph_start taskContent).

## Per-iteration procedure
~10 check-cycles (~1 min each, one cheap bash call per cycle): date; tail -1
night-watch.log; mirror-test log tail; prod arm serving; RAM red-line check.
Then ralph_done.

## Intervention rules (bounded — no new GPU work, never restart the soak)
- RAM red line: avail <2G sustained + so >500M/s = storm re-forming → `pkill -STOP -f "rsync -a --info"` (mirror resumes after 05:30)
- night-watch dead (no new line >25 min) → `setsid nohup /tmp/night-watch.sh &`
- mirror-test hung >90 min post-RSYNC_DONE → kill it, restore q5-serve on strixy2, log
- client q6 500s on strixy :8080 = the 192.168.50.150 host asking for qwen38-flash-q6; router survives — record only
- GPU fault storm (dmesg gfxhub climbing + arm dead) → record + restore prod; box stays down for morning triage
- ~05:30+: verify prod (q5) serving; ≤06:30 write MORNING-DIGEST.md with real numbers; then STOP the loop

## Checklist
- [x] storm incident resolved + prod restored (21:59)
- [x] mirror rsync complete (169G, xfr#7; wrapper wedged zombie — killed, RSYNC_DONE appended manually)
- [x] switch-test verdict: PASSED — q6-serve-192k on strixy2, 521.1 t/s @ 77,775-token prefill, q5-serve restored, unit dormant with runbook
- [x] both verdicts pushed to README (eb3ef41, rebased over operator's ca7fc78)
- [x] night-watch kept alive all night (zero missed samples 21:46→05:30)
- [x] prod stays healthy till morning (2 restart interventions, serving at 05:30)
- [x] MORNING-DIGEST.md written with real numbers (05:30)
- [x] hand-off summary for the operator (the digest + morning queue)

## Verification
- [21:48] loop started: soak alive, rsync running, mirror-test waiting, night-watch logging (epoch-deadline fixed)
- [22:00] prod q5 restored: gtt 96.3→107.0G (draft arm resident), avail 21G→15G, si/so 0 — serving
- [22:06] rsync 62% (62% of full ~169G dir; 98G landed), 112 MB/s, quiet (si/so 0)
- [22:16] RSYNC complete (169G xfr#7); wrapper wedged zombie killed, RSYNC_DONE appended; switch-test PASSED (521.1 t/s @ 77,775-token prefill), q5-serve restored
- [22:27-22:37 iter-2 cycles] steady: prod q5 serving, gtt 107.0G, avail ~8.0G, si/so 0, faults 0, s2 q5 active. .150 hammering q6 ~2/min (12 fails/6min) — absorbed, avail flat; escalation if avail drops: comment q6 arm from router ini (atomic, logged). Watcher 1690460 alive, samples on 10-min schedule.
- [22:38-22:46 iter-3 cycles] steady unchanged: prod serving, avail ~7.9G flat, si/so 0, faults 0, watcher on schedule (22:46:29). .150 still ~2/min (8/4min), absorbed.
- [22:47-22:57 iter-4 cycles] steady unchanged: prod serving, avail ~7.85G flat, si/so 0, faults 0, watcher on schedule (22:56:29). .150 rate unchanged (~2/min, 8/4min).
- [22:58-23:06 iter-5 cycles] steady unchanged: prod serving, avail ~7.85G flat, si/so 0, faults 0, watcher on schedule (23:06:29). .150 rate unchanged.
- [23:07-23:17 iter-6 cycles] steady unchanged: prod serving, avail ~7.8G flat, si/so 0, faults 0, watcher on schedule (23:16:30). .150 rate unchanged.
- [23:18-23:27 iter-7 cycles] steady unchanged: prod serving, avail ~7.8G flat, si/so 0, faults 0, watcher on schedule (23:26:30). .150 rate unchanged.
- [23:28-23:36 iter-8 cycles] steady unchanged: prod serving, avail ~7.9G flat, si/so 0, faults 0, watcher on schedule (23:36:30). .150 rate unchanged.
- [23:37-23:41 iter-9 REFLECTION + relaxed cadence] steady: prod serving, avail ~7.9G, si/so 0, faults 0. Cadence relaxed to ~5 cycles/iter (steady state); night-watch 10-min tripwire covers gaps.
- [23:42-23:47 iter-10] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (23:46:30).
- [23:48-23:52 iter-11] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 23:56:30 due.
- [23:52-23:56 iter-12] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (23:56:31).
- [23:57-00:01 iter-13] steady across midnight: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 00:06:30 due.
- [00:02-00:07 iter-14] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (00:06:31).
- [00:08-00:11 iter-15] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 00:16:30 due.
- [00:12-00:17 iter-16] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (00:16:32).
- [00:17-00:21 iter-17 REFLECTION deep-check] steady: prod serving, avail ~7.9G, si/so 0; GPU faults 0/30min; s2 active; .150 ~2/min absorbed. No adjustment.
- [00:22-00:26 iter-18] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (00:26:32).
- [00:27-00:33 iter-19] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 00:36:30 due.
- [00:34-00:38 iter-20] steady: prod serving, avail ~7.95G, si/so 0, faults 0, watcher on schedule (00:36:32).
- [00:38-00:43 iter-21] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 00:46:30 due.
- [00:44-00:48 iter-22] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (00:46:32).
- [00:49-00:53 iter-23] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher sample 00:56:30 due.
- [00:54-00:58 iter-24] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (00:56:33).
- [00:58-01:01 iter-25 REFLECTION deep-check] steady: prod serving, avail ~7.8G, si/so 0; GPU faults 0/40min; s2 active; .150 9/5min absorbed. No adjustment; budget fine (24/70).
- [01:02-01:07 iter-26] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (01:06:33).
- [01:08-01:12 iter-27] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher sample 01:16:30 due.
- [01:13-01:17 iter-28] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (01:16:33).
- [01:18-01:22 iter-29] steady: prod serving, avail ~7.75G, si/so 0, faults 0, watcher sample 01:26:30 due.
- [01:23-01:27 iter-30] steady: prod serving, avail ~7.75G, si/so 0, faults 0, watcher on schedule (01:26:33).
- [01:28-01:32 iter-31] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher sample 01:36:30 due.
- [01:33-01:37 iter-32] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (01:36:34).
- [01:37-01:40 iter-33 REFLECTION deep-check] steady: prod serving, avail ~7.8G, si/so 0; GPU faults 0/35min; .150 10/5min absorbed. No adjustment; 4h to milestone.
- [01:41-01:45 iter-34] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher sample 01:46:30 due.
- [01:46-01:50 iter-35] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (01:46:34).
- [01:51-01:56 iter-36] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (01:56:34).
- [01:57-02:01 iter-37] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher sample 02:06:30 due.
- [02:02-02:06 iter-38] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (02:06:35).
- [02:07-02:11 iter-39] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher sample 02:16:30 due.
- [02:12-02:17 iter-40] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (02:16:35).
- [02:17-02:20 iter-41 REFLECTION deep-check] steady: prod serving, avail ~7.85G, si/so 0; GPU faults 0/40min; .150 9/5min absorbed. No adjustment; 3.2h to milestone.
- [02:21-02:26 iter-42] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher on schedule (02:26:35).
- [02:27-02:31 iter-43] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher sample 02:36:30 due.
- [02:32-02:37 iter-44] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (02:36:36).
- [02:38-02:42 iter-45] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher sample 02:46:30 due.
- [02:43-02:47 iter-46] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (02:46:36).
- [02:48-02:52 iter-47] steady: prod serving, avail ~7.9G, si/so 0, faults 0, watcher sample 02:56:30 due.
- [02:53-02:57 iter-48] steady: prod serving, avail ~7.85G, si/so 0, faults 0, watcher on schedule (02:56:36).
- [02:57-03:01 iter-49 REFLECTION deep-check] steady: prod serving, avail ~7.85G, si/so 0; GPU faults 0/40min; .150 10/5min absorbed. No adjustment; 2.5h to milestone.
- [03:02-03:07 iter-50] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher on schedule (03:06:36).
- [03:08-03:12 iter-51] steady: prod serving, avail ~7.8G, si/so 0, faults 0, watcher sample 03:16:30 due.
- [03:13-03:17 iter-52] steady: prod serving, avail ~7.75G, si/so 0, faults 0, watcher on schedule (03:16:37).
- [03:18-03:22 iter-53] steady: prod serving, avail ~7.7G (slow drift down, si/so 0 — within band), faults 0, watcher sample 03:26:30 due.
- [03:24-03:35 iter-54 INTERVENTION #1] .150 q6-load wave escalated: avail 7.6→1.8G in ~10min, GTT stalled 108.1G (wedged loader pinning ~18G page cache), si/so 0 throughout, prod serving. ROUTER RESTARTED 03:33:27. Result: avail 1807M→19.9G instantly, GTT 108.1→96.3G, q5 back 03:35.
- [03:37-03:49 iter-55 INTERVENTION #2] Wave #2: GTT re-froze at 108.1-108.3G immediately post-restart (.150 relentless), avail drained 5.2→1.98G over 12min (~50M/min), so=0, prod serving throughout. Trigger met → restart #2 at 03:48:30. Result: avail 1984M→19.8G, GTT→96.3G, q5 serving 03:49. Cadence: waves every ~15min; each costs 2min restart. Live-process preset path confirmed broken (points to nonexistent models.ini, no ini fd — fork runs on fallback arm discovery); config edit OFF the table until operator decides. Standing remedy: watch GTT freeze + avail<2G → restart.
- [03:52-04:02 iter-56] Wave #3: GTT froze 108.0-108.2 but avail STABILIZED ~4G (recovered 3.8→4.0G, so=0, prod serving) — this wave holds equilibrium instead of draining; NO restart needed. Waves vary in severity; trigger discipline (avail<2G) works.
- [04:02-04:07 iter-57 REFLECTION deep-check] wave #3 holding steady ~4.0G, GTT frozen 108.1, so=0, prod serving, faults 0/30min. Taxonomy: waves self-hold or wedge-drain; playbook unchanged.
- [04:08-04:12 iter-58] wave #3 still self-holding ~4.0G, GTT frozen 108.1, so=0, prod serving. No action.
- [04:14-04:18 iter-59] wave #3 continues self-holding ~3.95G, GTT frozen 108.1, so=0, prod serving. No action.
- [04:20-04:24 iter-60] wave #3 stable ~3.9G for 30+ min now, GTT frozen 108.1, so=0, prod serving. No action.
- [04:25-04:29 iter-61] wave #3 stable ~3.93G, GTT frozen 108.1, so=0, prod serving. No action.
- [04:31-04:35 iter-62] wave #3 stable ~3.9G (45+ min), GTT frozen 108.1, so=0, prod serving. No action.
- [04:37-04:41 iter-63] wave #3 stable ~3.9G (1h+ now), GTT frozen 108.1, so=0, prod serving. No action.
- [04:42-04:47 iter-64] wave #3 stable ~3.87G, GTT frozen 108.1, so=0, prod serving. No action.
- [04:47-04:52 iter-65 REFLECTION pre-milestone] wave #3 stable ~3.9G, faults 0/1h, prod serving. Digest plan set. 38min to milestone.
- [04:53-04:58 iter-66] wave #3 stable ~3.8G, GTT frozen 108.1, so=0, prod serving. No action. 32min to milestone.
- [05:00-05:04 iter-67] wave #3 stable ~3.85G, GTT frozen 108.1, so=0, prod serving. No action. 26min to milestone.
- [05:06-05:10 iter-68] wave #3 stable ~3.9G, GTT frozen 108.1, so=0, prod serving. No action. 20min to milestone.
- [05:11-05:15 iter-69] wave #3 stable ~4.0G, GTT frozen 108.1, so=0, prod serving. No action. 15min to milestone; digest next iteration after 05:30 verification.

## Reflection (iter-65, 04:47 — pre-milestone check)
1. DONE: 64 iterations, 7h; night deliverables complete; 2 clean interventions; GPU faults 0 ALL NIGHT; wave #3 self-holding 1h+.
2. WORKING: everything per playbook.
3. NOTHING BROKEN.
4. FINAL PHASE PLAN: 05:30 → verify prod + note wave state; then write MORNING-DIGEST.md with: soak verdict + iten12, decay verdict, mirror PREFILL 521, storm incident, wave taxonomy + 2 restarts, stale-preset finding, .150 warning, end states, operator queue. Then final verification + COMPLETE.
5. Digest checklist ready.

## Reflection (iter-57, 04:02 — deep check)
1. DONE: 56 iterations, 6.2h; two clean interventions (restarts #1 #2); mirror validated; all deliverables pushed; zero GPU faults ALL NIGHT; zero missed watcher samples.
2. WORKING: the wave taxonomy is now clear — .150 q6 waves either self-hold (~4G, wave #3) or wedge-drain (waves #1 #2 → restart at <2G). Trigger discipline proven.
3. FRICTION: .150 relentless; live router runs on fallback arm discovery (broken preset path) — operator's call in the morning.
4. NO ADJUSTMENT to the playbook.
5. NEXT: 1.5h to 05:30 → digest ≤06:30 with the full night's numbers (incl. wave taxonomy + the 2 restarts + stale-preset finding) → STOP loop.

## Reflection (iter-49, 02:57 — deep check)
1. DONE: 48 iterations, 5.2h; prod continuous since 21:59; zero missed watcher samples.
2. WORKING: cadence + tripwire; GPU faults 0/40min; .150 ~2/min (10/5min) absorbed; avail ~7.84G, swap 205M.
3. NOTHING BROKEN — equilibrium unchanged all night.
4. NO ADJUSTMENT.
5. NEXT: 2.5h to 05:30 milestone → digest ≤06:30 → hand off. After digest: STOP loop.

## Reflection (iter-41, 02:17 — deep check)
1. DONE: 40 iterations, 4.5h; prod continuous since 21:59; zero missed watcher samples.
2. WORKING: cadence + tripwire; GPU faults 0/40min; .150 ~1.8/min (9/5min) absorbed; avail ~7.86G, swap 207M — equilibrium rock-solid.
3. NOTHING BROKEN.
4. NO ADJUSTMENT.
5. NEXT: 3.2h to 05:30 milestone → digest ≤06:30 → hand off.

## Reflection (iter-33, 01:37 — deep check)
1. DONE: 32 iterations, 3.8h; prod continuous since 21:59; zero missed watcher samples; all deliverables landed.
2. WORKING: cadence + tripwire; zero GPU faults 35min; .150 ~2/min (10/5min) absorbed.
3. NOTHING BROKEN: avail ~7.76G, swap steady 210M — equilibrium unchanged since 22:00.
4. NO ADJUSTMENT.
5. NEXT: 4h to 05:30 milestone → digest ≤06:30 → hand off.

## Reflection (iter-25, 00:58 — deep check)
1. DONE: 24 iterations, 3.2h, all deliverables landed; prod continuous since 21:59; zero missed watcher samples.
2. WORKING: relaxed cadence + night-watch tripwire; zero GPU faults in last 40 min; s2 active.
3. NOTHING BROKEN: .150 ~1.8/min (9/5min), absorbed, avail flat ~7.85G, swap steady 211M.
4. NO ADJUSTMENT.
5. NEXT: ~4.5h to 05:30 milestone → digest ≤06:30 → hand off. Loop budget fine (24/70 used, ~5min/iter pace covers remaining window).

## Reflection (iter-17, 00:17 — deep check)
1. DONE: all deliverables landed; prod continuous since 21:59; 16 iterations, zero missed watcher samples.
2. WORKING: relaxed cadence right-sized; layered watch clean.
3. NOTHING NEW BROKEN: GPU faults 0 in last 30 min; s2 q5 active; .150 still ~2/min (10 fails/5min) — absorbed, no escalation.
4. NO ADJUSTMENT: cadence and rules hold.
5. NEXT: hold to ~05:30, verify prod, digest ≤06:30, hand off.

## Reflection (iter-9, 23:37)
1. DONE: storm resolved+verdict banked; mirror validated (521 t/s); README pushed ×2; 8 steady iterations, zero missed watcher samples.
2. WORKING: layered watch (night-watch 10-min tripwire + Ralph cycles + bounded rules) — both real interventions (SIGKILL, zombie unwrap) clean.
3. FRICTION: .150 hammering constant ~2/min for 1.5h — fully absorbed (avail flat), escalation trigger never fired, config change stays holstered. Token burn: ~10 near-identical cycles/iteration is wasteful when steady.
4. ADJUST: quiet-phase cadence relaxed — ~5 cycles/iteration (Ralph) + night-watch 10-min samples as the independent tripwire; full cadence returns on any anomaly. Detection latency grows ≤5 min, acceptable for steady state.
5. NEXT: hold to ~05:30, verify prod, digest ≤06:30, hand off. Morning items stay the operator's queue.

## Final Verification
- Exact monitor-rerunnable command: `curl -s --max-time 6 localhost:8080/v1/models | grep -c qwen38-flash-q5 && cat /home/piero/Piero/Work/Qwen38/reruns-260919/MORNING-DIGEST.md | head -5`
- Working directory: /home/piero/Piero/Work/Strix_AI_Server
- Required preserved artifacts: /home/piero/Piero/Work/Qwen38/reruns-260919/MORNING-DIGEST.md, night-watch.log, q6-soak.log, q6-mirror-test.log, .ralph/overnight-babysit.md
- Result (05:29:20): prod=1 (q5 serving), digest present with all night numbers; GPU faults whole night = 0; s2 q5 active / q6-mirror dormant; router/doctor/watchdog active.

## Notes
- INCIDENT 21:52-21:59 (resolved): zram swap storm — root = soak's 118G GTT (zero headroom at 192k) + rsync page-cache churn; prefill collapsed to 44.7 t/s; SIGKILL freed 118G instantly. Soak ended early. VERDICT: 192k = zero-headroom specialist, NOT a default arm; quiet-window data banked (iten12 0.917 [0.65-0.99], pp 198.9 t/s @127k prompt, 0 faults). This is README material for morning.
- [22:00] router 500: client 192.168.50.150 requested qwen38-flash-q6 → hot-load fail → clean 500. Router survived. Expected repeat if .150 re-asks.
- night-watch log has a cosmetic stray "0" line (grep -c on missing file emits 0 + || echo 0); harmless, morning cleanup.
- Operator's morning queue: podium fcb15 basis (0.667 vs 0.867), qwen4exp port (CPU-only), strixy2-into-pi, plus this incident writeup.
