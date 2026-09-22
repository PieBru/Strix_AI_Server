# Measuring — the ways this project measured itself wrong

Read this before trusting any number in this repo, including the podium's.
Every entry below cost real GPU-hours or produced a number that looked
true and wasn't. (Pattern borrowed with respect from
[rulith-dev/strixllama](https://github.com/rulith-dev/strixllama)'s
`docs/measuring.md` — the best measurement-culture document on this
hardware.)

## Confounds that fake results

- **The chat template is 2–3× on the headline bank and ~6× at depth.** The
  same model, same battery, same rung, only the template changed:
  27B-Q8+DFlash2 scored **2/15** (stock) vs **12/15** (sharp-low) on
  fcb15's deepest tier. No score is comparable across templates, and a
  deep-rung score without its template named is a random number.
- **A quiet box or no number.** The champion at `c=262144` left ~1 GiB of
  host headroom; a routine 26 GiB file copy evicted its cached weights and
  decode went **34 → 0.93 t/s** mid-battery. The result was a "291 s
  failure" that was pure page-cache thrash — we threw the pass away. Disk
  I/O during a measurement pass is measurement corruption.
- **Zero margin fails late and loud.** The same configuration later
  produced a 15-minute decode collapse and a kernel OOM kill at 03:54 —
  *after* we believed the margin was fixed (c=262144 → 200000). The fix
  that survives a night is the one that leaves headroom you can see in
  `free -g`, not the one that fits the arithmetic.
- **Read the refusal as physics, not failure.** Muse's pp@128k "cell" is
  `n/a` because its training context is 131072 and the server correctly
  caps the slot; a 160k-token window on code-dense corpus text needs
  `c ≥ 160k`. (We then sent a 154,913-token request at `c=131072` —
  **repeating a trap this file already documented.** Chars-per-token is
  ~3.1 on this corpus, not 4.)

## Noise floors that fake precision

- **±1 item at temperature 0.** Between two ladder rungs, one *unchanged*
  item flipped fail→pass. A 15-item bank has a real noise floor wider
  than it looks; single-rung deltas of one item are not signal.
- **Tier depth is not monotone.** The champion scored higher on the D+E
  rung than on D. Each rung is a measurement, not a difficulty scale.
- **Knob wins do not transfer.** Three examples in one day: DFlash2 n-max
  6 (27B: 28.0 vs 15.8 t/s) did nothing for Muse; strixllama's
  3-draft-tokens+n-gram-off (+62% on their box) tied our production
  config (35.8/26.4 vs 36.0/25.7). A knob is only a win where it was
  measured.

## Tooling that lies

- **`curl` without `Accept-Encoding: gzip` gets a 415** from this fork's
  web server and looks like "the WebUI is down" — browsers are unaffected.
  Verify web surfaces with a real browser (we use headless Chromium).
- **A health check tells you *something* answers the port**, not *what*.
  After a lab takeover, `:8080/health` returned "ok" from a leftover lab
  server while production had failed to bind — the dashboard said
  healthy, the box was not. Check `systemctl is-active` and the served
  model id, not just the port.
- **Process control is measurement infrastructure.** `pkill -f` with a
  pattern that matches your own invoking shell killed our own runner four
  times in one day, once mid-measurement, and once left a zombie server
  that poisoned the next run's config. Bracket the pattern
  (`"[g]efc-ladder"`), kill by explicit PID, and never put the pattern
  and the kill in the same command line.
- **Label drift:** a probe printed `nm7-tg128` while measuring n-max 6.
  Labels that are hardcoded in the tool outlive the truth. Parameterize
  or the artifact lies forever.
- **Schema drift:** our scorer read `bat`/`mode` fields that the runner
  never wrote (it writes `battery_version`/`phase`); every row silently
  tiered as "unknown" until we diffed the artifact against the parser.
  A parser must be pinned to the real artifact with a selfcheck that
  feeds it a known row.

## Process failures that cost hours

- **Two runs of the same benchmark against one endpoint** interleave,
  each takes double, and when one is killed its cleanup can take the
  model server down with it (the survivor then fails fast with
  connection-refused). One writer per box; queue, don't overlap.
- **A scripted README edit corrupted the podium table** (a footnote
  splice landed inside a row). Verify structure after every generated
  edit — grep the table's cell counts, don't trust the diff.
- **mDNS names in infra config:** `strixy-9ad3.local` advertises nine
  addresses (docker/CGNAT junk); a provider pointed at it hung for 30
  minutes and timed out the nightly doctor. `127.0.0.1` for local, a
  pinned `/etc/hosts` entry for LAN, never a discovery name in a
  unattended path.

## The honest-denominator file

The full per-item artifacts live in `gbench/results/` and
[benchmarks/results.json](results.json); when a number here and an
artifact disagree, the artifact wins and this file gains an entry.
