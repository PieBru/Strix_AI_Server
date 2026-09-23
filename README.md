# Is one Strix Halo enough for a dev? TL;DR Yes.

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/85b23c70-3e0b-4801-8a66-be50f6ded16b" />

<!-- toc -->

- [In a hurry? Look at these 2 tables](#in-a-hurry-look-at-these-2-tables)
- [Glossary](#glossary)
- [Hardware](#hardware)
- [Podium](#podium)
- [Champion vs cloud models — DeepSeek V4.1 Flash and GLM-5.3](#champion-vs-cloud-models--deepseek-v41-flash-and-glm-53)
- [Arch Linux minimal server — the base install](#arch-linux-minimal-server--the-base-install)
  - [Swap: answer **No** to zram — and why](#swap-answer-no-to-zram--and-why)
  - [After the install](#after-the-install)
- [Policy](#policy)
- [The "sharp" chat template](#the-sharp-chat-template)
- [RAM accounting](#ram-accounting)
- [Speed at depth — how much wall-time you actually wait](#speed-at-depth--how-much-wall-time-you-actually-wait)
- [Got a new model? Test it, then compare it to the podium](#got-a-new-model-test-it-then-compare-it-to-the-podium)
  - [1. Serve it](#1-serve-it)
  - [2. Quality — the batteries, with a confidence interval](#2-quality--the-batteries-with-a-confidence-interval)
  - [3. Speed — wall-clock, on this box](#3-speed--wall-clock-on-this-box)
  - [4. Compare](#4-compare)
- [Reproduce our tests](#reproduce-our-tests)
- [Podium — the details](#podium--the-details)
  - [Why Q5 wins](#why-q5-wins)
  - [Why not IQ4_NL? (also 12/12, faster decode, less RAM)](#why-not-iq4_nl-also-1212-faster-decode-less-ram)
  - [Why not Q6_K_XL? (also 12/12 — our preferred tier)](#why-not-q6_k_xl-also-1212--our-preferred-tier)
  - [Why not the 27B + Muse pair?](#why-not-the-27b--muse-pair)
- [Footnotes](#footnotes)
- [Italian (iten12)](#italian-iten12)
- [AIME-12 (reasoning)](#aime-12-reasoning)
- [sli — structured-list integrity (GBench)](#sli--structured-list-integrity-gbench)
- [Coding — GBench fcb15 (deterministic, unit-tested)](#coding--gbench-fcb15-deterministic-unit-tested)
  - [The tier ladder — where a model stops holding](#the-tier-ladder--where-a-model-stops-holding)
  - [Reasoning effort — measured](#reasoning-effort--measured)
  - [Quantization and coding/agentic quality — the honest note](#quantization-and-codingagentic-quality--the-honest-note)
- [Zebra — CSP logic ladder (GBench)](#zebra--csp-logic-ladder-gbench)
- [DeepSeek V4.1 Flash Q2 — tested, parked](#deepseek-v41-flash-q2--tested-parked)
- [The Doctor — 24/7 monitoring and the nightly auto-improve loop](#the-doctor--247-monitoring-and-the-nightly-auto-improve-loop)
  - [The WebUI (:8667)](#the-webui-8667)
  - [The nightly job (03:00, unattended, read-only)](#the-nightly-job-0300-unattended-read-only)
  - [The loop it enables — proposals out, human seal on every change](#the-loop-it-enables--proposals-out-human-seal-on-every-change)
- [Methodology](#methodology)
- [Acknowledgements](#acknowledgements)
- [License](#license)

<!-- /toc -->

## In a hurry? Look at these 2 tables

The whole README distils into two tables:
[**the podium**](#podium) — which local model this fleet serves and why
(speed × quality × RAM, every cell wall-clock and re-measured), and
[**the champion vs the cloud**](#champion-vs-cloud-models--deepseek-v41-flash-and-glm-53) — the same batteries run
against DeepSeek V4.1 Flash and both GLM-5.3 variants, so you can see
what staying local costs or saves. Everything else in this file is
evidence, method, or operations.

## Glossary

Skip this if the terms are already yours. They are used throughout the
tables, so they are worth one screen.

| term | meaning |
|---|---|
| **pp / tg** | prefill (prompt processing) and token generation, in tokens/s — the podium's `pp @4k/32k/128k` and `tg128/tg2048` columns |
| **GTT** | the GPU-visible memory window over the unified RAM pool (amdgpu's graphics translation table). On a UMA box this is where the model actually lives |
| **UMA** | unified memory architecture — one RAM pool shared by CPU and GPU, which is what lets a 128 GB box serve a 100+ GB model |
| **PLE** | per-layer embeddings — the part of this model family llama.cpp can stream from SSD instead of holding in RAM |
| **MTP / DFlash2** | the two speculative-decoding drafts we use: the model's own multi-token-prediction head (MTP) and the fork's DFlash2 draft |
| **nm** | n-max: how many draft tokens one speculation step proposes (`nm6` = 6) |
| **KV cache** | the attention key/value store the context lives in; grows with context length and quantisation (f16 here) |
| **arm** | one model instance in the router (`models.ini`); one arm is resident at a time |
| **row / cell** | a *row* is one model in a table; a *cell* is one measured number in it — a row holds one cell per battery |
| **tier** | a serving configuration's context size (`c=65536`, `c=131072`, …) — "the 64k tier". *Effort tiers* (low/medium) and *quant levels* are different axes |
| **UD- / Q5_K_XL / IQ4_NL / Q8** | quantisation levels; `UD-` is the unsloth dynamic quant |
| **template · effort** | the chat template and reasoning-effort level a cell was measured at — `sharp-low` = sharp template, low effort |
| **census / rung / ladder** | battery shapes: a *census* runs the whole item bank; the *ladder* adds harder *rungs* until a model stops solving them |
| **basis** | the template + effort + context a number was taken at. Two cells rank each other only on the same basis |
| **CI** | Wilson 95% confidence interval — the podium prints intervals because point estimates at n=12–20 rank nothing |
| **as-served / uniform** | as-served = the tier a model actually ships with here; uniform = every row re-cut at one template basis so the rows can be compared |
| `-c`, `-ub`, `-fa`, `-ngl`, `-ctk/-ctv` | llama.cpp flags: context size, micro-batch size, flash attention, layers offloaded to GPU, KV-cache type |

## Hardware

| | |
|---|---|
| APU | AMD Ryzen AI MAX+ 395 (Strix Halo) |
| iGPU | Radeon 8060S (gfx1151, RDNA 3.5) — integrated, no discrete GPU |
| Memory | 128 GB unified LPDDR5x (≈124 GiB usable) — shared CPU/GPU |
| Storage | NVMe SSD (also hosts the PLE lazy-streamed weights) |

**Software stack:** ROCm 10.2 nightly (`rocm-nightly-gfx1151-bin` from AUR,
gfx1151-only build) and Arch Linux installed as a **minimal headless
server** — no desktop environment. We access it mainly via SSH; a
[Cockpit](https://cockpit-project.org) daemon is optionally enabled for
browser-based monitoring. If you reproduce this, a headless setup keeps
~5 GiB of RAM free that a desktop would otherwise consume — that margin
is counted in the [RAM accounting](#ram-accounting) table.

## Podium

All wall-clock. Higher pp/tg is better; the Italian gate (iten12) is
pass/fail at 12 — not an overall quality verdict. The quality columns
(AIME / fcb15 / ladder / sli / zebra) are pointers: bases, CIs and
caveats live in [²⁵](#fn25), [¹⁰](#fn10) and each battery's chapter.
Each model cell names the **template · effort** its quality cells were
produced with (the as-served arm's basis, per [¹⁰](#fn10); Muse runs
its stock template by family design).

| model | pp @4k | pp @32k | pp @128k | tg128 | tg2048 | Italian (iten12)[¹](#fn1) | AIME [²⁵](#fn25) | fcb15 [¹⁰](#fn10) | ladder [²⁵](#fn25) | sli [²⁵](#fn25) | zebra [²⁵](#fn25) | RAM (weights) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Qwen3.8 Flash-Next Q5_K_XL + MTP** · sharp-low [¹²](#fn12) [¹⁴](#fn14) | **689** | **672** | **605** | **34.8** | **25.7** | **12/12** | **0.833** | **0.867** [¹⁰](#fn10) | **all rungs** | 10/10 | **0.65** | 97 GiB |
| Qwen3.8 Flash-Next Q6_K_XL + MTP · sharp-low [²](#fn2) | **730** | **699** | 199 [¹⁸](#fn18) | **34.3** | **22.3** | **12/12** | 0.750 | **0.867** [¹¹](#fn11) | — [¹¹](#fn11) | 10/10 [¹¹](#fn11) | — [¹¹](#fn11) | 107 GiB |
| Qwen3.8 27B Q8_K_XL + DFlash2 · sharp-medium (serves stock) [¹⁴](#fn14) | 486 | 409 | 192 | 20.5 | **28.0** | 11/12 | 0.500 | 0.800 [¹⁰](#fn10) | **all rungs** | — | 0.55 | 30 GiB |
| Muse-Glimmer-30B Q8 + DFlash2 · stock | 499 | 470 | — [¹⁶](#fn16) | 34.5 | 15.2 [¹⁷](#fn17) | **12/12** | 0.333 | 0.733 [¹⁰](#fn10) | — | — | 0.45 | 32 GiB |

## Champion vs cloud models — DeepSeek V4.1 Flash and GLM-5.3

The same batteries that grade our locals, run against commercial APIs
through the same probe harness (same items, same graders, same strict
format contract). Two caveats decide how to read this table, both from
footnote [⁷](#fn7): a cloud API that does not obey the one-code-block answer
contract scores as a *format* failure, so cloud cells are compatibility
checks first and capability signals second; and empty cells are
model/battery pairs **we have not measured** — they are not zeros.
Cloud cells were probed 2026-09-16 at the vendor default API config (no
effort/thinking tuning on our side).

| metric (battery) | **Q5_K_XL + MTP** (local, sharp-low) | DeepSeek V4.1 Flash (cloud) | GLM-5.3 (cloud) | GLM-5.3-flash (cloud) |
|---|---|---|---|---|
| Italian gate (iten12) | **12/12** (passes) | **12/12** (passes) [¹⁹](#fn19) | **12/12** (passes) [¹⁹](#fn19) | **11/12** (passes) [²⁰](#fn20) |
| AIME yearsplit-12 | **0.833** [0.55–0.95] | 0.667 [0.39–0.86] | 0.583 [0.32–0.81] [¹⁹](#fn19) | 0.333 [0.14–0.61] [²⁰](#fn20) |
| AIME-60 census | **0.533** low / 0.517 med | 0.483 [0.36–0.61] | 0.433 [0.32–0.56] [²³](#fn23) | 0.367 [0.26–0.49] [²³](#fn23) |
| Zebra CSP ladder | **0.65** [0.43–0.82] (n=20) [²¹](#fn21) | 0.42 [0.19–0.68] | 0.50 [0.25–0.75] [¹⁹](#fn19) | 0.417 [0.19–0.68] [²⁰](#fn20) |
| fcb15 coding | **0.867** low [0.62–0.96] / 0.667 med (n=15 census) | 0.533 [0.30–0.75] (n=15) [²²](#fn22) | 0.60 [0.36–0.80] (n=15) [²²](#fn22) | 0.667 [0.42–0.85] (n=15) [²²](#fn22) |
| sli structured-list | **10/10** | 0.8 [0.49–0.94] [²²](#fn22) | 10/10 [²²](#fn22) | 0.8 [0.49–0.94] [²²](#fn22) |
| decode tg128 / weights RAM | **34.8 t/s / 97 GiB, local** | n/a (API) | n/a (API) | n/a (API) |

Reading it honestly:

- **No cell here is a verdict.** Every shared cell has overlapping CIs at
these n, and the cloud column carries the format caveat. What the data
supports is "at least level, nominally ahead" — not "beats the frontier".
- **The heaviest shared cell is the AIME-60 census** (n=60, the only cell
where both sides have a tight interval): 0.533 vs 0.483 — a three-item
gap, i.e. a tie at this n.
- **The Italian gate no longer discriminates cloud from local.** Redone
2026-09-22 with artifacts on disk, both full cloud models **pass at 12/12**
(DeepSeek V4.1 Flash gated for the first time; GLM-5.3 corrected from the
stale 7/12 cell, which had no surviving artifact and was most plausibly a
format artifact of the kind footnote [⁷](#fn7) warns about). Only the
flash variant drops an item (11/12). The gate's remaining value is as a
regression tripwire, not a cloud separator.
- Cloud cells are cheap to add and cheap to keep: an API key and a probe
run per model. The table can grow a row per model without touching the
local test rig.

## Arch Linux minimal server — the base install

Everything in this file runs on a plain Arch install with **no desktop
environment**; the [hardware section](#hardware) already priced that choice
(~5 GiB of RAM a desktop session would hold, counted in the [RAM
accounting](#ram-accounting) table). This chapter is the reproducible
recipe, driven by [archinstall](https://github.com/archlinux/archinstall) in
its **guided ("human") mode** — the option names below are the labels the
installer puts in front of you, so the table can be followed in the menu.

| guided prompt | our answer | why |
|---|---|---|
| **Profile** → `Minimal`, or `Server` → `sshd` | Minimal (+ `sshd`) | headless; the Server profile adds nothing we want beyond `openssh` + `sshd.service` |
| **Kernels** | `linux` | the AMD/ROCm stack tracks current kernels — no LTS fallback to keep in sync |
| **Bootloader** | `Systemd-boot` | one EFI partition, no GRUB config to maintain |
| **Disk configuration** → best-effort default layout | single `ext4` root on the NVMe | one 1.9 TB disk with one job; snapshots buy nothing here |
| **Would you like to use swap on zram?** | **No** | measured — see below |
| **Network configuration** → copy the ISO configuration | `systemd-networkd` | no desktop, so no NetworkManager; `/etc/systemd/network/*.network` is a few lines per NIC |
| **Audio** | none | no `pipewire`/`wireplumber`/`alsa-firmware` on either box |
| **Additional packages** | `openssh`, `cockpit` | Cockpit (optional) is the browser dashboard for an otherwise GUI-less box |
| **Time zone / locale / keymap** | `Europe/Rome`, `en_US.UTF-8`, `it` | |
| **NTP** | enabled | `systemd-timesyncd` — the Doctor's timeline is only as good as the clock |

The same decisions as config JSON, for an `archinstall --config` run:
`"profile_config": {"profile": {"main": "Minimal"}}`,
`"bootloader_config": {"bootloader": "Systemd-boot"}`,
`"kernels": ["linux"]`, `"audio_config": {"audio": "none"}`,
`"swap": {"enabled": false}`, `"disk_config": {"config_type": "default_layout"}`.

### Swap: answer **No** to zram — and why

archinstall asks *"Would you like to use swap on zram?"* and its sample
config ships `"swap": {"enabled": true}`; both nodes came up with `zram0`
(zstd, priority `100`) from install day. We switched it off on both. The
reason is worth writing down, because that default is a good one — for a
different workload.

**What zram is for.** It is a compressed swap *device backed by RAM*: pages
the kernel evicts are compressed and kept in memory, so a later fault-in
costs a decompress instead of a disk read. On the workload it was designed
for — desktop anon, browsers, editors, build jobs, where pages are full of
text, pointers and repetition — it compresses 2–4× and turns slow paging
into cheap paging. The ordinary anon on our own box measures 2.1×, exactly
as advertised.

**Why it inverts here.** Under pressure, an inference server does not hand
the kernel ordinary anon. What floods out is model- and KV-class memory —
weights, their shmem-backed GPU mappings, activation buffers — high-entropy
data that measured **1.09×** (4.5 GiB of real storm content stored in
4.1 GiB of RAM). For this class the premise "swap is compressible" is
simply false, and every consequence of zram turns against us:

- **The reclaim target cannot be met, so reclaim never stops.** The kernel
  reclaims *bytes of RAM*. If evicting a page frees 9 % of it, it must evict
  roughly eleven pages to bank one, at full per-page cost. That is a
  treadmill rather than a one-way drain: `si≈so≈250 MB/s`, sustained, with
  decode collapsing from ~37 t/s to 1.7 t/s at the same tier. A disk swap
  frees 100 % per page, so the same pressure resolves and *ends*.
- **The wrong tier is used first.** `zram0` carries priority `100` against
  the swapfile's `-1`, so every squeeze hits the ~9 % device before the
  100 % device is touched at all — the effective tier only engages after
  zram is full (16–32 GiB of stored pages).
- **Every fault-in costs twice.** A zstd decompress on the way back, *plus*
  the amdgpu userptr restore stall for any page a GPU mapping needs — so the
  pages that stall inference are exactly the expensive ones to restore. On
  disk the same page is one read, and the kernel can page-cluster it.
- **It stays resident.** The compressed store keeps holding its RAM after
  the storm (4.5 GiB still held hours later), so the memory zram "freed" is
  not free, `avail` stays depressed, and the next pressure event arrives
  sooner.

| | zram, as the installer ships it | plain 32 GiB swapfile, what we run |
|---|---:|---:|
| compression on the pages that actually got swapped | **1.09×** (4.5 GiB → 4.1 GiB of RAM still held) | n/a |
| RAM freed per page swapped out | **≈9 %** | 100 % |
| price of a fault-in | zstd decompress **+** amdgpu userptr restore stall | one SSD read |
| behaviour under sustained pressure | 250 MB/s treadmill, decode 37 → 1.7 t/s | makes progress, then ends |

**What we run instead.** `swapoff /dev/zram0`; the zram generator disabled
in `/etc/systemd/zram-generator.conf`; a 32 GiB `swapfile` in `/etc/fstab`
(guided mode's swap step is zram-only — a swapfile is three commands
afterwards, or a swap partition in the manual disk layout); `vm.swappiness =
10` in `/etc/sysctl.d/`, so the kernel prefers dropping cache over pushing a
working set to swap. The number to watch is not swap *use* but swap *rate*:
`si`/`so` at zero with 106 GiB of GTT (the GPU-visible memory window) is healthy, either one pinned at
hundreds of MB/s is the failure mode this chapter exists to prevent.
`swapon --show` plus `cat /sys/block/zram0/mm_stat` (field 1 ÷ field 2 = the
real ratio) is the whole diagnosis: if that ratio is near 1, zram is a pure
cost on that box.

**Not a verdict on the default.** On a laptop or a general-purpose server
archinstall's answer is *yes* — compressible anon is the common case, and
none of the above applies. This is specifically a RAM-resident-model box,
where the pages that get swapped *are* the model, that should answer **No**.

### After the install

ROCm and the rest of the serving stack are one AUR package
(`rocm-nightly-gfx1151-bin`), a `uv` install for the harness, and a
Vulkan/ROCm build of llama.cpp — [the tooling chapter](#reproduce-our-tests)
has the exact commands. Cockpit, if enabled, is the box's only web surface
besides the model server itself.

## Policy

1. **Quality first** — within acceptable speed
2. **Speed floor** — gate: at least ~200 t/s prefill and ~20 t/s
 generation, then we measure wall-clock, not server-reported. See below,
 [Speed at depth](#speed-at-depth--how-much-wall-time-you-actually-wait)
3. **Q5+ quants only** — Q4 and below are deprecated here. This floor
 comes from enterprise-level experience and community expert consensus
 on MoE (mixture-of-experts) quantization robustness, not from a 12-item battery alone.
 Our battery *confirms* Q5 meets the quality gate; the floor itself is
 practitioner judgment. See below,
 [Why not IQ4_NL](#why-not-iq4_nl-also-1212-faster-decode-less-ram).
4. **llama.cpp first** — preferably the vanilla build (upstream master,
 easy updates); the tuned HIP fork is used where prefill speed demands.
 *Measured exception:* for this model family the fork is
 load-bearing — the MTP draft GGUF is fork-format (upstream rejects
 it), and an eager-load vanilla census hard-crashed the lab box
 (no lazy-PLE path). Vanilla stays preferred for models it can host;
 see the engine-axis note in `configs/q5-flash-next-winner.md`.
5. **Open source only** — closed engines are evaluated for reference,
 never adopted
6. **Solo-coder optimized** — one user, one GPU, no multi-tenant overhead
7. **Single model vs co-residency** — for the best quality at a
 good-enough speed, the primary goal is to serve a single
 all-purpose model on a single Strix-Halo, optionally routed by a
 fast classifier service (e.g. Laya, from any LAN node). At the cost
 of a service restart, one Halo node can be configured to serve
 multiple models via `models.ini` — either by swapping the single
 big model, or by co-hosting smaller models (e.g. Qwen 27B-Q8 +
 Qwen Image 2.1).

## The "sharp" chat template

The serve recipe doesn't use the stock Qwen3.8 template. It runs
[configs/templates/sharp-v22.5.0.jinja](configs/templates/sharp-v22.5.0.jinja)
(`qwen3.8-froggeric-v22.5.0`, from
[froggeric/Qwen-Fixed-Chat-Templates](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates)
on Hugging Face — attributed to its author and subject to their terms)
because it is the control surface for thinking:

- `enable_thinking` — default **true**: reasoning streams before the
 answer, which is why the champion runs as a thinking model in our cells
- `reasoning_effort` — `none`/`off` disables thinking outright;
 `low`/`medium`/`xhigh` pick a tier (default `medium`)
- `auto_disable_thinking_with_tools`, `preserve_reasoning` across turns,
 an XML tool-call format, and vision plumbing

Two honesty notes: every measured quality and speed cell ran through
this template — the numbers are template-specific, we have not run a
stock-vs-sharp battery A/B, and none of the published cells ran with
thinking off. `sha256 cdff39fb26b60dc90faa292e726655c6b21f62db497846e02e4c4bbab942a84a`.
The stock template is a drop-in swap of the `chat-template-file` line if
you prefer upstream-default behavior.

## RAM accounting

One method, applied to every candidate. All figures GiB.

The @262k columns are the *arithmetic* at the native ceiling — the
champion actually serves 200k (the measured-stable value; see *Why Q5
wins*), and Q6 ships at 64k (its sustained gate).

| component | Q5 @262k | Q6 @262k | Q6 @131k | IQ4_NL @262k |
|---|---:|---:|---:|---:|
| resident weights (file − PLE streamed to SSD) | 96.5 | 107.0 | 107.0 | 66.0 |
| KV cache, full-attention layers (f16) | 6.0 | 6.0 | 3.0 | 6.0 |
| MTP draft | 2.8 | 2.8 | 2.8 | 2.8 |
| mmproj vision projector (enabled in models.ini) | 0.9 | 0.9 | 0.9 | 0.9 |
| compute buffers + PLE row-reader (bounded by `-ub 4096`) | ~3.0 | ~3.0 | ~3.0 | ~3.0 |
| OS + system services | ~5.0 | ~5.0 | ~5.0 | ~5.0 |
| **total** | **114.2** | **124.7** | **121.7** | **83.7** |
| box limit | 124 | 124 | 124 | 124 |
| **headroom (theoretical)** | **9.8** | **−0.7 (doesn't fit)** | **2.3 (razor)** | **40.3** |

**Observed in practice:** with the full 262k KV pool allocated and the
server idle, the box reports ~121 of 124 GiB used (~3 GiB available) —
page cache and streaming working sets consume most of the theoretical
margin. The `MemoryMax=118G` systemd cap sits between: enough room for
the ~114 GiB footprint, tight enough that an OOM kill (which is what
killed the Q6 bench chain) is the failure mode, not silent swap.

Where the numbers come from:
- **KV cache** at 262k = 12 full-attention layers × 2 KV heads ×
 (256 key + 256 value) dims × 2 bytes × 262144 positions ≈ 6.0 GiB.
 The model is **hybrid-attention** (GGUF metadata: 48 layers,
 `full_attention_interval = 4` — only every 4th layer retains full KV;
 the rest are sparse/indexed with a bounded window), which is why the
 KV is so light for a 262k context.
- **PLE row-reader** is bounded by `-ub 4096`; larger micro-batches scale
 it linearly, and without the bound, 32k+ prefills amplify row reads past
 the RAM ceiling.
- **OS + buffers** = 5 GiB, applied uniformly to every candidate (earlier
 versions used a looser estimate — this table is the corrected one).

## Speed at depth — how much wall-time you actually wait

Real-text prompts actually filled (no synthetic filler). These are the
seconds from "send" to "reply complete."

**Why seconds, not tokens/second:** most speed talk quotes pp/tg —
tokens/second while filling or draining the context. Fine as kernel
diagnostics, but they say next to nothing about what you actually wait:
the wall-clock time to complete a task **successfully** — prefill at
real depth, retries, and re-generating artifacts that failed QA all
included. (An independent DeepSeek run posted healthy-looking completion
rates across 83 minutes of model wall time and delivered zero accepted
artifacts — the t/s looked fine, the task failed.) Reasoning models
sharpen the point further: our champion thinks before it answers, so a
task's token count is reasoning + answer, and decode t/s alone can't
tell you how many tokens you'll wait through. This table is in seconds
for that reason.

| prompt size | Q5 | Halogen | who wins |
|---|---:|---:|---|
| 4k | 6.4 s | 5.5 s | Halogen, slightly |
| 32k | **40.6 s** | 9.1 min | **Q5, 13.5×** |
| 128k | **3.3 min** | 29.5 min | **Q5, 8.9×** |

For context: a 32k prompt is roughly "a medium codebase plus your task."
A 128k prompt is "the whole monorepo." This is why prefill-at-depth is
the deciding axis for coding.

**Credit where due:** Halogen wins decode at depth (27.3/25.6 t/s at
2k/128k vs our 25.7 sustained) and wins prefill at 4k. Our re-measured
short decode (**34.8 t/s** tg128) now edges its 32.4. For
short-prompt chat it remains the faster engine; the collapse at depth
is what kills it for our workload. Its 128k cell completed at 1770s —
30s under our client timeout — real but with a thin margin; the
non-monotonic throughput
(60 → 71 t/s) is unexplained — the 32k cell matches nominal-size
arithmetic (32768/546 = 60.0) while the 128k cell reads 131072/1770 =
74, not 71; the probe's raw token counts will settle it.

**Evidence note:** the wall-clock probe behind this table — and the
pp/tg podium cells — is committed as
[benchmarks/speed_probe.py](benchmarks/speed_probe.py), and quality cells
reproduce from [benchmarks/](benchmarks/). What is still owed is the raw
per-cell console logs behind the individual podium numbers.

## Got a new model? Test it, then compare it to the podium

Everything the podium rows are made of is reproducible from this repo with
two committed tools. A full row takes about an hour of unattended GPU time
on this box; a first read on a new model takes ten minutes.

### 1. Serve it

Any OpenAI-compatible chat endpoint works, and all the commands below take
`--host`. Three common shapes:

```bash
# (a) add it as an arm to the router (one arm resident at a time)
#     ~/Piero/Work/Qwen38/models.ini — copy the champion's block, swap the
#     model/model-draft paths, set load-on-startup = false, reload the service
# (b) a one-off server on the lab box
llama-server -m <model.gguf> -md <draft.gguf> --host 0.0.0.0 --port 8080 \
    -c 65536 -ctk f16 -ctv f16 --jinja -fa on -ngl all
# (c) a remote or vendor endpoint
#     uv run python3 scripts/probe.py --host https://api.example.com --model <vendor-id>
#     (needs GEFC_API_KEY in the env; refuses before sending a byte without it)
```

Ask the endpoint what it is actually serving — never infer it from the
config you edited: `curl -s localhost:8080/v1/models`.

**Two settings decide whether the numbers mean anything**

- **Chat template.** The measured template effect on this family is 2–3×
  (IQ4_NL: 0.333 stock → 0.667 sharp, same quant, same battery). A stock
  template run is a valid measurement *of the stock template*, and is not
  comparable to the podium's sharp-family rows. State which one you ran.
- **Context.** Serve the context you intend to claim. Some models are
  trained short (Muse-Glimmer: 131072) and the server silently caps the
  slot — the 128k cell then legitimately reads `n/a`, and a claimed 262k
  would be a fiction.

### 2. Quality — the batteries, with a confidence interval

```bash
cd ~/Piero/Work/Qwen38/gbench

# the Italian pass/fail gate (the podium's Italian column) — a census, 12 items
uv run python3 scripts/probe.py --battery iten12 --budget 12 \
    --tag mysmodel-iten --model <arm> --host 127.0.0.1:8080 --hardware "Strix Halo (gfx1151)"

# coding: the 15-item deterministically-graded bank (census for a podium row)
uv run python3 scripts/probe.py --battery fcb15 --budget 15 \
    --tag mymodel-fcb15 --model <arm> --host 127.0.0.1:8080

# the pre-registered harder rungs — the threshold layer, where a saturating
# model stops being measurable (see docs/FCB15-CALIBRATION.md in GEFC)
uv run python3 scripts/fcb15_run.py --tag mymodel-v3d --model <arm> \
    --items-file batteries/fcb15_v3d.py
uv run python3 scripts/fcb15_run.py --tag mymodel-v3de --model <arm> \
    --items-file batteries/fcb15_v3de.py
uv run python3 scripts/threshold_scorer.py   # -> tier pass rates + break point

# reasoning tiers
uv run python3 scripts/probe.py --battery zebra --budget 20 --tag mymodel-zebra --model <arm>
uv run python3 scripts/probe.py --battery aime  --budget 30 --tag mymodel-aime  --model <arm>
```

Grading is deterministic and machine-only — a Python harness per item, no
LLM judge, no rubric prose. A wrong answer fails on an `assert`, so a
sabotaged grader shows up as a wrong number, not a loud bug.

Read the **CI**, not the point estimate. `--budget` below the battery size
spends exactly that many items and gives a Wilson 95% interval; a census is
labelled as such. Two rows whose intervals overlap are **not** ranked by
this suite — that is the whole reason the podium reports intervals.

### 3. Speed — wall-clock, on this box

```bash
uv run python3 benchmarks/speed_probe.py --model <arm>          # all five cells
uv run python3 benchmarks/speed_probe.py --model <arm> --tg-only # decode only
```

This is the probe the podium's `pp @4k/32k/128k` and `tg128/tg2048` columns
come from, and it measures the clock, not the server's own counters:

- **prefill** — one request per window, timed send → complete, distinct
  corpus offsets so no prompt cache flatters a cell
- **decode** — streamed, timed first content delta → last, so prompt
  processing is excluded; reasoning deltas count as output

Comparability rules: same corpus (`benchmarks/corpus/speed-corpus.txt`),
same offsets, temperature 0, **one client**. A cell measured while another
job shares the GPU is not a cell — rerun it.

Two traps that cost us a whole measurement pass, both worth knowing before
you trust a number:

- **Serve the context the cell needs, or read the refusal honestly.** A
  pp@128k request sends a ~160k-token window on code-dense text, so an arm
  served at `c=131072` refuses it with HTTP 400 — the probe prints
  `n/a`, which is the correct cell, not a zero. The probe prints the
  realised token count; that is the number to quote.
- **Keep the box quiet, including its disk.** The champion's serving
  config leaves ~1 GiB of host headroom, so any large file I/O evicts the
  model's cached weights and decode collapses: a 26 GiB transfer running
  beside one battery item took the arm from **34 t/s to 0.93 t/s** and
  produced a 291 s "failure" that was pure page-cache thrash. We threw
  that run away and re-ran it. Copy files *between* measurement passes,
  never during one.

### 4. Compare

| what | where |
|---|---|
| the podium table | [above](#podium) — the row format to match |
| the raw rows behind every cell | [benchmarks/results.json](benchmarks/results.json) |
| the per-item runs (resume-safe JSONL) | `gbench/results/fcb15-<tag>.jsonl` |
| how a claim gets promoted or retired | [Policy](#policy) |

A model earns a podium row when it clears: the Italian gate (12/12), a
fcb15 census, a real speed sweep, and a RAM figure — **all at the same
template and context you are claiming**. Until then it belongs in the
prose of the chapter it is challenging, with its CI, not in the table.

Before trusting any number — yours or ours — read
[benchmarks/measuring.md](benchmarks/measuring.md): the ways this project
measured itself wrong (template confounds, the quiet-box rule, noise
floors, and the tooling that lies). Two honest outcomes worth writing
down when you do this:

- **Saturation is a result too.** If a model caps the battery, that rung
  has stopped measuring it — run the next tier (`fcb15_v3d.py`) or the row
  says nothing the previous model's row didn't.
- **A negative A/B is a result.** This suite's most reused findings are
  negative: the draft-length setting that lifted the 27B did **not** lift
  Muse (14.4 vs 15.0 t/s), and a Strix-Halo neighbour project's best MTP
  tuning (3 draft tokens, n-gram off, +62% on their box) **tied** our
  production config here (35.8/26.4 vs 36.0/25.7). A knob win does not
  transfer between trunks or setups until it is measured on yours.

## Reproduce our tests

Everything is in the repo:

- [benchmarks/](benchmarks/) — **the batteries and runner behind our quality
 tables**: ITEN-12 v2, AIME-60, a deterministic runner, and our measured
 results (`results.json`). Three commands reproduce a score — see
 [benchmarks/README.md](benchmarks/README.md)
- [gbench/](gbench/) — the GBench coding/CSP probe (fcb15 + zebra
 batteries, Wilson-CI runner) behind the
 [coding](#coding--gbench-fcb15-deterministic-unit-tested) and
 [zebra](#zebra--csp-logic-ladder-gbench) tables
- [configs/](configs/) — exact serve commands, binary provenance (commits,
 digests, build recipes), full sha256 checksums, flag-by-flag explanations
- [models.ini](models.ini) — the single source of truth for all serving
 options
- [systemd/](systemd/) — the two unit files (HIP fast-prefill and Vulkan
 vanilla), switchable with one command
- [doctor/](doctor/) — the Doctor WebUI + its unit — 24/7 monitoring and
 the nightly auto-improve loop (see the chapter below)

## Podium — the details

### Why Q5 wins

**The standing decision:** the champion is
**Qwen3.8 Flash-Next UD-Q5_K_XL + the sharp template**, with the
promoted default effort tier **low** (sharp-low) — both boxes' serving
configs updated and verified. The evidence base: the podium
above, the template axis measured on Q5 itself (+0.40 coding / +0.25
reasoning vs stock), BF16-anchor parity across three batteries, the
effort matrix (low = better coding, flat elsewhere, strictly faster),
and the engine axis proving the tuned fork is load-bearing.

**The winner:** llama.cpp + Qwen3.8 Flash-Next Q5_K_XL (147 GiB) + its
MTP draft, on a single 128 GB Strix Halo.

- Passes the quality gate (12/12, tied with Q6 and IQ4_NL) **and** the
 speed floor
- Serves a **200k-token context** — whole codebases, no chunking —
 with real headroom ([the math](#ram-accounting)). The native 262k was
 deliberately walked back: at `c=262144` the arm allocates ~111.8 GiB of
 the box's 124 GiB and, under sustained load, the kernel enters a
 swap/refault storm that takes decode from ~35 t/s to **under 1 t/s**
 (measured twice). 200k is the value that survives a night of load
- A 32k-token prompt (a big file plus instructions) prefills in ~48
 seconds (**672 t/s** probe) — the axis that matters for
 coding, and the co-resident pair can't touch this
- One main model + draft = zero swap overhead, simplest operations
- All **quality** scores are reproducible from this repo — serve
 commands, checksums, unit files, the batteries, and the champion's raw
 JSONL runs in [benchmarks/](benchmarks/), [configs/](configs/), and
 [systemd/](systemd/). The wall-clock speed probe is committed as
 [benchmarks/speed_probe.py](benchmarks/speed_probe.py) — see
 [Speed at depth](#speed-at-depth--how-much-wall-time-you-actually-wait)

**The template confound is measured, not hypothetical:** IQ4_NL scored **0.333 on its stock template** overnight and
**0.667 with the sharp template** — same quant, battery, protocol,
hardware class; the template alone doubled the score. The
uniform-template re-cut of the Qwen-family cells is underway (IQ4
done, 27B in flight); Muse runs its stock template by family design.

### Why not IQ4_NL? (also 12/12, faster decode, less RAM)

Our Q5+ policy (principle 3). A 12-item battery can't discriminate within
the top tier — the floor itself comes from practitioner experience with
MoE quantization robustness. IQ4_NL is a strong candidate and we may
revisit; for now, Q5 is the tier we trust for production, until we find a
reliable way to run Q6.

### Why not Q6_K_XL? (also 12/12 — our preferred tier)

RAM arithmetic: 107 GiB resident + KV + draft ≈ 124 GiB on a 124 GiB box —
zero margin. We tested it: it loaded, passed the gate, then **died under
sustained load** when KV growth exceeded the remaining headroom
([the math](#ram-accounting)). **The reduced-context path is now measured,
not planned:** the catalog's 131k arm (`c = 131072`) ran the full overnight
re-run chain on a dedicated process — iten12 12/12 under the hardened
grader, then 3 h 04 m of continuous service at **GTT 125.0/133.1 GB** —
no MemoryMax crutch. The death was a 262k-config problem; at 131k the KV
pool is pre-allocated and cannot outgrow the margin. Q5 ships at 200k for
the same measured reason (see *Why Q5 wins*); Q6 at 131k is a
demonstrated fallback tier, not a hope.

**But there is a second, slower disease — measured:** sustained
decode *degrades* even at 131k. With n-gram speculation off (MTP-only,
`spec-type = draft-mtp`), fresh-load Q6 bursts at **35 t/s** — then decays
to **~2 t/s** once cumulative activated expert rows cross the ~14 GiB GTT
headroom (on strixy: after ~20–25k tokens of diverse generation; the
overnight "items run long" and the never-completing fcb15 census were
this same disease, unmeasured). Turning n-gram speculation off delays
this decay but does not cure it. The GPU sits at ~13% while it crawls:
the bottleneck is row eviction from disk, not compute. **Q6 quality
cells collected so far** (MTP-only): iten12 12/12, fcb15 0.50 [0.19–0.81]
at n=6, AIME partial (paused at ~2 t/s). **Both speed-cure arms ran and failed:** `--load-mode mmap --lazy-mode on`
turned into a kernel reclaim war (tg flat at 2.59 from the first token —
file-backed weights
and HIP unified memory fight over the same physical pages); `c=32768 +
KV q8_0` = loads but wedges on first real generation (GPU 0%, zero
timing prints, requests hang — a fork lazy-path bug). The cure is
fork-level (or a re-quant) for the *131k* tier — **but at c=65536 the
cliff disappears**: a 10-minute sustained gate measured **27.4 t/s
flat** (18k tokens, no decay; the ~1.5 GiB of extra KV headroom keeps
the eviction away). **Q6 at 64k is a working sustained tier** — a
single client with a whole-codebase prompt under 64k tokens gets Q6
quality at 27 t/s.

**Context ladder — measured end to end on 2026-09-22** (Q6 + MTP, lazy
`on-direct`, f16 KV, run under a `MemoryMax=118G` cap so the kernel keeps
a reserve instead of racing the GPU for pages):

| `c` | loads | decode | ~114k-token prefill | faults |
|---|---|---|---|---|
| 65536 (shipped) | ✓ | 27.4 t/s flat (gate) | not tried | 0 (8/8 census) |
| **131072** | ✓ | **24.9 / 25.1 t/s** | **726 t/s, then 25.1 t/s** | **0** |
| 196608 (`ub=4096`) | ✓ | 21.8 t/s | ✗ SIGABRT | 0 |
| **196608 (`ub=1024`)** | ✓ | **22.65 t/s** | **434.8 t/s, then 27.8 t/s** | **0** |
| 262144 | ✗ | — | — | — |

- **131k is the validated Q6 tier** — an 8000-token generation holds
  ~25 t/s and a **113,933-token prompt** prefills at **726 t/s** then
decodes at 25.1 t/s, with the reply demonstrably reading the prompt
  (it summarised its content). One run measured 14.9 t/s — the
  disk-streaming variance the *second disease* above describes.
- **192k loads and decodes, and its long-prefill abort has a cure: `ub`.**
  At the shipped `ub = 4096` a ~143k-token prefill aborts inside
  `ggml_cuda_flash_attn_ext_qsa` — the QSA attention workspace is
  allocated *per attention call* and scales with prompt/batch size, so it
  fails under the cap. With **`ub = 1024`** the same 192k tier prefills
  **163,199 tokens at 434.8 t/s** and decodes at 27.8 t/s, no abort
  (decode 22.65 t/s on a 3k-token generation). RAM was never the binding
  constraint — every failure above ran with **8.7–10.7 GB spare**.
- **256k is a fork limit, not a RAM limit**: with f16 KV the graph build
  asserts at `qwen4exp.cpp:1365` (`build_attn_qsa`, reached from
  `resolve_fused_ops`); with `fa = off` it fails to create the context
  and the router then retry-loops. KV quantisation cannot buy the room
  back — the same assert demands `k/v == F16`, so `ctk/ctv = q8_0` aborts
  the load. **Q6's honest ceiling today is 192k, validated in
  production** — wired as the `deep` arm on 2026-09-22 under
  `MemoryMax=120G`, where a **150,247-token prompt prefilled at
  472.8 t/s** end-to-end with the reply demonstrably reading it. The cap
  is the cliff, not the context: at the old 118G the same prefill
  crawled at ~147 t/s (GPU ~10% busy, disk-bound row eviction) and died
  mid-flight; at 120G the GPU runs well-loaded. 256k remains
  fork-refused.
- **The GPU page faults are a teardown/reclaim race, not a load killer.**
  Across every run in that table: **zero** `[gfxhub] page fault` events.
  The three seen on 2026-09-22 all hit lab servers *during teardown* or an
  uncapped census; under the cap `avail` held 2.5–3 GB where the uncapped
  run drove it to 71–112 MB. The driver is already the inbox `amdgpu` AMD
  recommends for gfx1151 (no DKMS installed).

### Why not the 27B + Muse pair?

Both components fail the speed floor (15.8 and ~18 t/s decode). And an
honest caveat: the pair was never benchmarked as a co-resident serving
unit — this is a component-level comparison. The pair's theoretical
advantage (62 GiB total weights, more room for context) is real but
untested as a serving configuration.

## Footnotes


<a id="fn1"></a>¹ **How "quality" is measured:** the iten12 battery — 12 Italian↔English
bidirectional translation items, graded deterministically by a Python
harness that asserts on content keywords AND false-friend discriminators
(*attendere* for *attend* = fail). Both natural rendering conventions are
accepted. Battery v3.1: exec-namespace fix, false-friend
rejections on four more items, sentence-shape rule (keyword salad no
longer passes). The Q5 cell is re-scored under v3.1 — still 12/12;
other models' re-runs are owed. A 12/12 is a **pass/fail gate** —
"meets our floor," not "best in class."

<a id="fn2"></a>² Q6's AIME cell is 8/11 (one item errored when the server died
mid-battery — the denominator silently changed). See [⁴](#fn4).

<a id="fn3"></a>³ Fails the 20 t/s decode floor at depth: Muse's tg2048 15.2 [¹⁷](#fn17)
(its tg128 34.5 clears it, as does the 27B's re-measured 20.5 [¹⁴](#fn14)), so
Muse is listed as a reference tier on sustained decode only.

<a id="fn4"></a>⁴ One item errored (INFRA — server died mid-battery), reducing the
denominator to 11. The 0.833 vs 0.727 gap is 1–2 items — within sampling
variance at temperature 1.0. Both models are in the same quality tier.

<a id="fn5"></a>⁵ Q6's prefill cells are now measured at its shipped `c=65536` (pp4k/pp32k
below) and its decode-at-depth gate held **27.4 t/s flat** over 18k tokens;
`c=131072` still decays (the fix is owed at fork level).

<a id="fn6"></a>⁶ Server-reported decode from the scored iten12 items (n=1 each; a 245-tok
and a ~9.3k-tok generation), not the wall-clock probe used for Q5's cells.
Honesty note: that 9.3k generation exceeds the documented 6000-token cap —
the journal of that window shows generations up to ~11.9k, so the cell ran
with a looser cap than the protocol states. Treat as indicative: same decode
tier as Q5, ±10%; the overnight v3.1 re-run under the fixed cap replaces
these cells.

<a id="fn7"></a>⁷ Cloud and streamed-local models must follow the same strict format
contract (ONE python code block printing the answer). A frontier cloud
model scoring 7/12 is more likely a format-compliance artifact of the
battery than a capability signal — treat cloud cells as format checks,
not quality verdicts. The DeepSeek local Q2's 10/12 is genuine (it runs
the same contract as the locals).

<a id="fn8"></a>⁸ The DeepSeek cloud cell was also run as a full 60-item census:
29/60 = 0.483. The 12-item seed-1300 subset scored 8/12 = 0.667 — the
subset ran easy for it. The census is the more reliable cloud number;
both are reported, none hidden.

<a id="fn10"></a>¹⁰ fcb15 cells are census scores under battery v3, uniform-template
(sharp) for the Qwen family, stock for Muse by family design — the
measured template effect is 2–3×, so template-uniform columns are the
only comparable ones. CIs and caveats live in
[the coding section](#coding--gbench-fcb15-deterministic-unit-tested).
Overlapping CIs throughout: no ranking claims.
 The champion's podium cell is its **promoted default tier (low,
 0.867)**; the medium-basis cell (0.667) for uniform-template ranking
 lives in the fcb15 chapter. Effort tiers are per-cell — see the census
 table: the 27B cell (0.800) is medium-basis (its only census; no low run
 exists), so the two rows are not effort-matched; the champion's low cell
 is the one cross-box replicated. Basis decision (2026-09-23, operator-
 delegated): podium shows as-shipped tiers, the chapter holds the uniform
 medium view.

<a id="fn11"></a>¹¹ **Q6 at the 64k sustained tier, measured 2026-09-23 on idle strixy2.**

- **fcb15, both effort tiers:** sharp-low **0.867 [0.62–0.96] (13/15) — an exact
  tie with the champion's shipped cell** — and sharp-medium 0.667 [0.42–0.85]
  (10/15), identical to the champion's medium cell. ~11 min per census, decode
  sustained ~32 t/s. The podium cell is the as-shipped low basis (the `deep` arm
  serves sharp-low), per [¹⁰](#fn10)'s rule.
- **sli:** 10/10 [0.72–1.0] — the canary saturates here too.
- **zebra and the ladder are not obtainable at this tier.** The 20 long-CSP items
  stormed the box (swap-out 388 MB/s, `avail` 2.0 GB, decode stalled, no timing
  prints for 4+ min) and had to be SIGKILLed. So 64k sustains ~6k-token census
  items and the sli canary, but not zebra's long thinking generations: cumulative
  activated expert rows cross the ~14 GB GTT headroom and trigger the row-eviction
  storm. Same disease as the 131k/192k decay, one tier lower — the 10-minute
  18k-token gate sat on the right side of the threshold, zebra on the wrong side.
- **Where the decay disease stands: tier-bound, not box-bound.** The same census
  aimed at the 192k tier on the same idle box 15 minutes earlier decayed to
  **1.5 t/s on the first item** (replicating the 2026-09-22 strixy decay
  13→7→3 t/s; 0 faults, so a speed disease rather than a crash). Q5 at 131k
  completes the census in 8 min; Q6 at 64k completes it; Q6 at 192k decays on
  both boxes. The cure remains fork-level (row residency).
- The earlier MTP-only budget-6 probe cell (0.50 [0.19–0.81]) is superseded.

**The 192k tier is a zero-headroom specialist** (measured the same night): a
nightly soak held 0.917 iten12 and 198.9 t/s prefill in its quiet window, but a
single co-resident 107 GB file copy tipped the box into a zram thrash storm
(prefill collapsed to 44.7 t/s). 192k serves alone or not at all — the 128k Q5
arm stays the daily driver. The mirrored arm on strixy2 (`q6-serve-192k.service`)
validated at 521 t/s @ 78k-token prefill, which also replicates the champion's
fcb15-low cell cross-box (0.867 [0.62–0.96], overlapping CIs).

<a id="fn12"></a>¹² Concurrent clients vs the 124 GiB box (f16 KV; the pool is
pre-allocated, so `c` = slots × ctx). Fixed cost ~108 GiB (weights
96.5 + MTP draft 2.8 + vision 0.9 + buffers 3.0 + OS 5.0); each
slot's KV is **6.0 GiB @256k** / 3.0 @128k / 2.25 @96k. Theoretical
slot ceilings: **2 @256k, 5 @128k, 7 @96k** — but observed page-cache
+ streaming working sets eat ~7 GiB, so **safe: 1 / 3 / 4**. Slots
also *share decode* (N clients ≈ 1/N the t/s each); KV-q8_0 would
halve slot cost but the fork refuses it outright — `qwen4exp.cpp:1365`
asserts `k/v == GGML_TYPE_F16`, so a q8_0 KV aborts the load (it also
wedged at 32k [⁵](#fn5); measured 2026-09-22, *Why not Q6*).

<a id="fn14"></a>¹⁴ Speed cells re-measured with one identical wall-clock
probe (real-text corpus, request-sent→complete; tg streamed
first→last incl. reasoning deltas; pp@128k cells ran at 159.9k real
tokens — code-dense corpus — and are mutually comparable at equal n).
n-max A/B for the 27B's DFlash2 draft at sustained decode (nm = draft
tokens per step): nm6 28.0 > nm5 16.7 ≈ nm7 15.8 t/s (tg2048) — the
grid's nm7 pick does not generalize past short benches, so nm6 stays.

<a id="fn16"></a>¹⁶ Muse's training context is **131072** tokens — the server caps the slot
(`n_ctx_seq 262144 > n_ctx_train 131072`), so a 128k-token prefill is out of
range by construction. Not a speed result; the cell is n/a.

<a id="fn17"></a>¹⁷ Muse's DFlash2 draft at n-max 7 gives tg2048 15.2 (tg128 34.5). The nm6
A/B that lifted the 27B (28.0 vs 15.8 [¹⁴](#fn14)) does **not** transfer: Muse at nm6
measured 14.4 t/s, so nm7 stays.

<a id="fn18"></a>¹⁸ No longer n/a: the Q6 arm was raised to a **192k tier** on
2026-09-22 (`c=196608, ub=1024`, see *Why not Q6*), so the pp@128k cell is now
measured — a 127,066-token prompt prefilled at **198.9 t/s**. Treat it as
the floor, not the mean: three other same-config runs the same day
measured 434.8 / 472.8 / 491.9 t/s (150k-class prompts), so deep prefill
at this tier is streaming-variance-heavy — the row-eviction disease the
Q6 section documents. The row's other speed cells (730 / 699 / 34.3 /
22.3) remain at the 64k-era basis from [⁸](#fn8).

<a id="fn19"></a>¹⁹ The GLM-5.3 gate/AIME/zebra cells and the DeepSeek V4.1 Flash
gate cell were **redone 2026-09-22** with artifacts on disk
(`probe-glm53r-*.json`, `probe-dsv4f-iten12.json`; same harness, seed and
n as the neighbouring rows). The redo matters: the 2026-09-16 GLM-5.3 cells
(7/12 gate, 0.25 zebra) left no surviving artifacts and are now believed
to be format artifacts, not capability — both corrected numbers are
higher. The 10/12 in the iten12 chapter remains the **parked local**
DeepSeek V4.1 Flash Q2 (the 340 GiB SSD-streamed MoE,
[*tested, parked*](#deepseek-v41-flash-q2--tested-parked)) — it runs the
same code-block contract as our locals; its cloud sibling now measures
12/12.

<a id="fn20"></a>²⁰ GLM-5.3-flash cells were probed 2026-09-22 via the z.ai coding-plan
endpoint with the same harness, seed and n=12 as the neighbouring rows
(artifacts: `probe-glm53f-{iten12,aime,zebra}.json`). The flash variant
**passes the Italian gate** that full GLM-5.3 failed (11/12 vs 7/12) —
but it is the weakest reasoner in the table (AIME 0.333, CI not
overlapping the champion's 0.833) and its zebra 0.417 ties DeepSeek's
cloud cell. Read it as: better instruction-following than its full
sibling, weaker reasoning than everything else measured here.

<a id="fn21"></a>²¹ The champion's zebra cell is the **n=20 sharp-low re-cut** from the
[zebra chapter](#zebra--csp-logic-ladder-gbench) (its own table lists n per row);
every other zebra cell in this table is an n=12 seed-1300 probe. Mixed n is
kept because the n=20 row is the champion's shipped-default measurement —
its CI is correspondingly tighter, and n is printed wherever it is not 12.

<a id="fn22"></a>²² Cloud coding and structured-list cells, filled 2026-09-22 (same harness;
fcb15 as full 15-item censuses, matching the champion's cells; artifacts
`probe-{fcb15,sli}-{glm-5-3,glm-5-3-flash,dsv4f}*.json`). The coding
picture is the sharpest separator in this table: the champion's
shipped-default 0.867 sits above every cloud census (0.533 / 0.60 /
0.667 — only the flash variant's CI brushes the champion's lower bound).
sli mostly saturates (GLM-5.3 matches the champion's 10/10; both flash
variants drop 2/10 — the first non-saturating sli results measured).

<a id="fn23"></a>²³ Cloud AIME-60 censuses (n=60, the tightest-CI cell in the table):
DeepSeek V4.1 Flash 0.483 (2026-09-16), GLM-5.3 0.433 and GLM-5.3-flash
0.367 (2026-09-22, `probe-aime60-glm-5-3{,-flash}.json`). At n=60 the CIs
still overlap pairwise, but the champion's 0.533 leads every cloud arm
nominally.

<a id="fn24"></a>²⁴ Cloud rows in the per-battery tables are the 2026-09-22 redo/fill cells
(the cloud chapter is the canonical table). The 2026-09-16 GLM-5.3 gate cell
(7/12) and zebra cell (0.25) were superseded — they left no artifacts and
the redo measured materially higher (12/12, 0.50); keeping the old cells
anywhere would contradict the artifact-backed ones.

<a id="fn25"></a>²⁵ Podium quality columns (2026-09-23): **AIME** = yearsplit-12 seed-1300
re-cut (sharp cells; Muse stock by family design; the 27B's stock cell
0.417 lives in the AIME chapter — its podium cell is the sharp basis,
consistent with its fcb15 cell). Pre-grader-fix † cells and contamination
caveats live in the AIME chapter. **ladder** = deepest fcb15 tier rung
held under greedy (`v3+D+E+F`); "all rungs" means the model holds every
rung drafted — Q5 and the 27B tie at every depth (tier-ladder chapter).
**sli** = structured-list canary, saturated at 10/10 for the champion at
both effort tiers — regression canary only, not a discriminator (never
run for the other rows). **zebra** = n=20 (Q5 sharp-low, 27B, Muse) or
n=12 cells, overlapping CIs throughout (zebra chapter). Q6's AIME cell
is the yearsplit re-cut (0.750); its fcb15/ladder/sli/zebra cells remain
owed (fcb15 census in flight on strixy2 2026-09-23).

## Italian (iten12)

This battery doesn't find "the best model" — it identifies which models
are **good enough** for our mission. Models that pass are then ranked by
speed, RAM, and context headroom.

| model | score |
|---|---:|
| Flash-Next Q5_K_XL | **12/12** |
| Flash-Next IQ4_NL | **12/12** |
| Flash-Next Q6_K_XL | **12/12** |
| Muse-Glimmer Q8 | **12/12** |
| Qwen3.8 27B Q8 | 10/12 |
| DeepSeek V4.1 Flash Q2 (local, SSD-streamed) [⁷](#fn7) | 10/12 |
| GLM-5.3 (cloud) [²⁴](#fn24) | **12/12** |
| GLM-5.3-flash (cloud) [²⁴](#fn24) | 11/12 |
| DeepSeek V4.1 Flash (cloud) [²⁴](#fn24) | **12/12** |

All local cells ran the hardened **v3.1** grader (overnight re-run) — the battery is uniform across the table at last.
Muse-Glimmer moved 11/12 (v2) → **12/12** under the hardened grader.

**Honest caveat:** at n=12, a one-item difference is within sampling noise
(Fisher's exact p ≈ 0.49 for 12/12 vs 10/12). The battery is a floor
check, not a top-tier discriminator. Coding is now covered separately
([GBench fcb15](#coding--gbench-fcb15-deterministic-unit-tested) and
[zebra](#zebra--csp-logic-ladder-gbench)); long-context retrieval is
still planned.

## AIME-12 (reasoning)

The AIME surface is now a single **year-stratified 12-item selection**
(6×AIME 2025 + 6×AIME 2026, seed 1300, same graders) — the contamination-correct
cut that replaced the original stratified-random one. At n=12 it is a pointer,
not a verdict: every interval below overlaps the champion's except where noted.

| model | template basis | yearsplit | CI95 | n |
|---|---|---:|---|---:|
| **Flash-Next Q5_K_XL** (champion) | sharp | **0.833** | 0.55–0.95 | 12 |
| Flash-Next Q6_K_XL | sharp | 0.750 | 0.47–0.91 | 12 |
| 27B BF16 anchor | sharp-medium | 0.750 | 0.47–0.91 | 12 |
| Qwen3.8 27B Q8 | sharp-medium | 0.500 | 0.25–0.75 | 12 |
| Flash-Next IQ4_NL | stock | 0.417 | 0.19–0.68 | 12 |
| Qwen3.8 27B Q8 | stock | 0.417 | 0.19–0.68 | 12 |
| Muse-Glimmer Q8 | stock | 0.333 | 0.14–0.61 | 12 |

Two structural findings: the **27B BF16 anchor (0.750) lands BELOW the
Q5-quantized champion (0.833)** and ties the Q6 quant — the flash MoE
architecture dominates reasoning regardless of quant tier; and the sharp
template lifts the 27B's reasoning too (0.417→0.500) but far less than it
lifted its coding score (0.267→0.800).

**Full-bank cross-check (n=60):** LOW **0.533** [0.41–0.65] vs MEDIUM
**0.517** [0.39–0.64], paired cross-box — a dead tie (one-item spread). AIME is
effort-flat at the largest n measured; the effort lever is coding-specific
(fcb15 +0.20 at low). The n=60 bank also contains harder unsolved-era items
that both tiers miss, which is why its level sits below the yearsplit cell.

**Retired — the original stratified-random cut.** Its local cells were Q5
0.833, Q6 0.727, IQ4_NL 0.667, 27B-Q8 0.667 and Muse 0.583. They are no longer
tabulated, for two measured reasons: four of the five ran under the **v1
grader** (exec-namespace bug — structured solutions raised `NameError` inside
the checker and were scored FAIL, so they skew low), and 8 of its 12 items came
from AIME 2025 (~18 months public at test time, contamination-likely for
locals). The year-stratified cut above fixes both, so that is the number to
quote. History and per-item artifacts: `grading_changelog` and
`aime_selection_split` in [results.json](benchmarks/results.json).

## sli — structured-list integrity (GBench)

First measurements (paired same-box): **10/10 at low = 10/10 at
medium** — the battery saturates at both tiers; no effort sensitivity.
Useful as a regression canary, not as a discriminator.

## Coding — GBench fcb15 (deterministic, unit-tested)

The iten12/AIME pair can't see coding ability, and both saturate by
design — they are pass/fail gates. **fcb15** is different on both counts:
15 short, deterministic, unit-tested coding tasks from the GBench battery
corpus of **[Good-Enough-For-Coding](https://github.com/PieBru/Good-Enough-For-Coding)** (GEFC)
(working copy in [PieBru/Qwen38_Strix](https://github.com/PieBru/Qwen38_Strix/tree/main/gbench);
minimal runner vendored in [gbench/](gbench/)). Grading is outcome-based —
behavioral unit tests written at grade time, no LLM judge, no gold-diff —
and the probe reports a **Wilson 95% CI** with every query accounted
(failed queries spend budget; a full run is labeled census).

On saturation, precisely: fcb15 is a *fixed bank* scored as a fraction,
with **pre-registered item swaps** as the anti-saturation stopgap when a
family hits the ceiling. The structural fix — scoring *at what difficulty
the model breaks* instead of *how many of N* — is GEFC's **non-saturating
measurement layer** (difficulty-threshold scoring; currently a
pre-development proposal). Until it lands, read census cells with the
Wilson ceiling in mind: two models at 15/15 are rank-indistinguishable.
Even so, a scoring cell discriminates wherever the gate saturates — which
is why fcb15 earns a podium column.

Uniform-template fcb15 column — sharp family, effort noted per cell
(**low is the promoted default**).

| model | template / effort | fcb15 | CI95 |
|---|---|---:|---|
| **Flash-Next Q5_K_XL (champion)** | sharp **low** | **0.867** (13/15, census) | 0.62–0.96 |
| Qwen3.8 27B Q8 + DFlash | sharp medium | **0.800** (12/15, census) | 0.55–0.93 |
| Muse-Glimmer Q8 | stock (family design) | 0.733 (11/15, census) | 0.48–0.89 |
| Flash-Next Q5_K_XL | sharp medium | 0.667 (10/15, census) | 0.42–0.85 |
| Flash-Next IQ4_NL | sharp medium | 0.667 (10/15, census) | 0.42–0.85 |
| Flash-Next Q6_K_XL | sharp **low** (64k tier [¹¹](#fn11)) | **0.867** (13/15, census) | 0.62–0.96 |
| Flash-Next Q6_K_XL | sharp medium (64k tier [¹¹](#fn11)) | 0.667 (10/15, census) | 0.42–0.85 |

The template is not cosmetics: measured on three arms it **doubled**
(IQ4 0.333 → 0.667), **tripled** (27B 0.267 → 0.800), and on the
champion itself runs 0.267 (stock embedded) → 0.667 (sharp medium) →
**0.867 (sharp low)** — the effort dial is the same lever again
(the full matrix lives in *Reasoning effort — measured*). Read the
ranking with the usual discipline — overlapping CIs, 2–3-item gaps at
n=15, and Muse runs a different family's template. Under uniform
templates the BF16-parity 27B-Q8 leads coding while the quantized
flash arms lead reasoning — the quantization cost is battery-dependent
(see the note below).

**Reproducing a cell (for agents).** Pin *both* the template file and
the effort tier or the number is garbage — a stock-template run reads
as a different model (that exact mislabel happened here: a stock-template
cell was recorded as `low` — corrected in the effort table below).

```bash
cd gbench && uv run python3 scripts/probe.py --battery fcb15 \
 --budget 15 --tag <model>-<template>-<effort> --model <arm> \
 --http-timeout 2700 --rdir <evidence-dir>
```

The arm's `chat-template-file` (now `sharp-v22.5.0-low.jinja` by
default) is set in the serving ini, not in the probe. `budget 15` =
census (every item attempted); failed queries **spend** budget — a
cell with `answered < budget` is an incident, not a score. Evidence
is the stamped `.jsonl` + Wilson `.json` pair in `--rdir`; the repo
copies live in `benchmarks/`.

**How to read it (uniform-template re-cut):** the disentangling runs are done —
IQ4-with-sharp doubled (0.333 → 0.667) and 27B-with-sharp tripled
(0.267 → 0.800), so the table above is uniform-template for the Qwen
family, and what remains is the honest residue: overlapping CIs and
2–3-item gaps at n=15 (no model is crowned by this), Muse runs its own family's
template by design, and fcb15 measures short, deterministic,
unit-tested tasks — not the agentic/real-world coding the community's
Qwen3.8-over-Muse consensus is about; that regime stays untested here.
Q6's cell is owed (items exceeded the 900 s HTTP budget — retry in
flight).

### The tier ladder — where a model stops holding

fcb15's fixed bank saturates for strong models, which is exactly when a
"how many of 15" score stops discriminating. The pre-registered answer
(GEFC's `docs/FCB15-CALIBRATION.md`, contract v3) is a **ladder of harder
tiers**: the solved-by-all items are swapped, rung by rung, for
constraint-stacked variants (tiers B, C, D, E — drafted and selfchecked
*before* anyone saturated). The swap into the headline battery fires only
when >=2 models saturate the current rung; until then the deeper rungs are
administered as a *measurement* (`scripts/fcb15_run.py --items-file
batteries/fcb15_v3d.py`), never as an activation. Greedy pass rates, both
models on the **same template** (sharp-low, the promoted default), one
box, one harness:

| model | v3 (headline) | v3 + D rung | v3 + D+E rung | + F rung | holds to |
|---|---:|---:|---:|---:|---|
| Qwen3.8 Flash-Next Q5_K_XL (champion) | 10/15 | 10/15 | 12/15 | **11/15** | every rung we have |
| Qwen3.8 27B Q8_K_XL + DFlash2 | 12/15 | **12/15** | **12/15** | **12/15** | every rung we have |

**The result is a tie at every depth, and that is the finding.** On a
template-uniform basis these two models do not separate — not at D, not at
D+E, and not at F (the rung drafted the same evening, after the uniform
data showed D/E didn't separate them; both models *solved* the F items).
Both models hold every rung we have; separating them needs a bigger
difficulty jump or different families, not more of the same stacking. The ladder's first discriminator turned out to be
the **template, not tier depth**, and it is a big one — the same 27B, the
same deepest rung, only the template changed:

| 27B Q8+DFlash2, v3+D+E rung | greedy |
|---|---:|
| stock template (its as-served arm) | **2/15** |
| sharp-low template | **12/15** |

A 2 → 12 swing is a 6× template effect at depth — much larger than the
2–3× already measured on the headline bank, because a weak template costs
*more* exactly where the constraints stack. Practical consequences: (1)
never quote a deep-rung score without naming its template; (2) the 27B's
serving arm runs stock **on purpose** (sharp makes it +46% slower), so its
*as-served* deep-rung ability genuinely is 2/15 — the speed decision buys
back the depth; (3) to separate these two models at all, the ladder needs
deeper tiers (F+) or more items per rung, which is the next GEFC step.

**One more model was run through the ladder the same day** — the 27B
**Q6_K_XL trunk + DFlash2 draft** (a combination with no arm before this;
stock template, so its cells are *not* comparable to the sharp rows):
iten12 **10/12** (fails the gate), fcb15 census **0.333**, ladder
**4/15 → 3/15**, zebra **0.55**, AIME-30 **0.30**, and on the second box
pp4k 348 / pp32k 297 / pp128k 197 / tg128 25.1 / tg2048 16.1. Tested,
parked: the Q8 trunk dominates it at every depth, and it misses the gate
the champion clears.

Three honest notes: tier depth is *not* monotone (the champion scored
higher on D+E than on D, and one unchanged item flipped fail→pass between
rungs at temperature 0 — treat single-rung deltas of ±1 as noise, the
per-rung CI is wider than n=15 suggests); the table is greedy-primary with
the full retry protocol in the artifacts; and the raw rows are
`gbench/results/fcb15-{q5,q8df}-v3{,d,dem}*.jsonl` (stock) and
`*-slow-2026-09-21.jsonl` (sharp-low). The scorer is
`gbench/scripts/threshold_scorer.py` (selfchecked).

### Reasoning effort — measured

The sharp template's effort dial is a real quality axis, not just a
speed knob. Champion Q5, same batteries, greedy census, only the
template default changed:

| effort | fcb15 | CI95 | iten12 | AIME yearsplit |
|---|---:|---|---|---|
| medium (all published cells) | 0.667 | 0.42–0.85 | 12/12 | 0.833 |
| **low** | **0.867** | 0.62–0.96 | 12/12 | **0.833** |
| none (thinking off) | 0.667 | 0.42–0.85 | 12/12 | **0.917** |
| xhigh | 0.267 | 0.07–0.56 | — | 0.667 |
| *(stock template, medium)* | *0.267* | *0.11–0.52* | — | *0.583* |

**The matrix is closed, and low is the unambiguous sweet spot.** On
fcb15 the effort curve is an inverted-U — xhigh 0.267 < medium/none
0.667 < low 0.867: *overthinking actively damages agentic coding*.
On AIME the family is flat (0.667–0.917, single-item spreads), with
nothink's 11/12 the best point estimate and xhigh the worst. Low
wins coding outright, ties reasoning, and is strictly fastest in
wall-clock — three batteries, cross-box, stamped evidence. **Promoted to the serving default; both boxes verified by live generation.** An earlier version of this table
recorded the stock-template cell (0.583) as "low" — a config slip,
corrected.

**The template is the champion's biggest single lever — measured on
Q5 itself** (same accidental controlled run): fcb15 **0.267 → 0.667**,
AIME **0.583 → 0.833**. The disentangler result first seen on IQ4 and
27B generalizes: the sharp template is worth +0.40 coding / +0.25
reasoning — larger than any quant-tier step we measured.

**Promotion question for the :** with no measured downside,
making `low` the default effort level is a live decision — the
remaining caution is generalization (n = 12–15 per battery, CIs wide;
fcb15 replication cross-box in flight).

### Quantization and coding/agentic quality — the honest note

The producer's benchmarks (reliable, but BF16-vs-BF16) show Flash-Next
beating the 27B on every benchmark, with the widest gap exactly on
agentic coding (DeepSWE 58.7 vs 42.2). Our table measures a different,
asymmetric matchup: the 27B at Q8 (≈ BF16-parity) against Flash-Next
at Q5/Q6 — a heavily quantized MoE. Two things we can say, one we owe:

- **Measured here, under uniform templates: battery-dependent.** The
 BF16-parity 27B-Q8 leads the coding battery (fcb15 0.800 vs the
 flash arms' 0.667 — overlapping CIs, 2 items), while the quantized
 flash arms lead reasoning decisively (AIME yearsplit 0.833/0.750
 vs 0.417). No external per-quant benchmark for the Flash-Next
 Q5/Q6 GGUFs exists to check against; community wisdom is
 qualitative (Q5 ≈ Q6 ≈ Q8 perceptually; "flash even in Q4/Q5 over
 the 27B" on this RAM class).
- **Degradation-vs-self is battery-dependent.** fcb15 is quant-flat
 (IQ4 = Q5 = 0.667 under the sharp template) while AIME shows IQ4
 bleeding to 0.417 — reasoning depth degrades before short-task
 codegen does. Saturated batteries cannot see this at all (iten12:
 everyone 12/12 — the floor gate is ceiling-blind to quant loss). The
 reasoning-effort dial interacts too (Q5's fcb15 rose 0.667 → 0.867 at
 low effort), so quant conclusions hold only at a stated effort
 level.
- **Owed: the unquantized anchor.** What we cannot yet say is how far
 Q5/Q6 sit from their BF16 selves in absolute terms — Flash-Next BF16
 (300+ GB) can never run on this box. The 27B's BF16 (~55 GB) can: a
 BF16-27B cell on our batteries anchors the ladder, and GEFC's
 [non-saturating threshold layer](https://github.com/PieBru/Good-Enough-For-Coding)
 is the definitive instrument (θ across the quant ladder — its design
 case).

## Zebra — CSP logic ladder (GBench)

30-item constraint-satisfaction ladder, grid-graded, same probe
methodology (subset cells at n=12 or n=20 as labeled; seed-1300
stratified):

| model | zebra | CI95 | n |
|---|---:|---|---:|
| 27B BF16 (anchor, sharp) | 0.65 | 0.43–0.82 | 20 |
| **Flash-Next Q5 (sharp-low, shipped default)** | **0.65** | 0.43–0.82 | 20 |
| **Flash-Next Q5 (sharp-low, full bank)** | **0.57** | 0.39–0.73 | 30 |
| Qwen3.8 27B Q8 + DFlash | 0.55 | 0.34–0.74 | 20 |
| Flash-Next Q5 (sharp-medium, full bank) | 0.53 | 0.36–0.70 | 30 |
| Muse-Glimmer Q8 | 0.45 | 0.26–0.66 | 20 |
| Flash-Next IQ4_NL | 0.42 | 0.19–0.68 | 12 |
| DeepSeek V4.1 Flash (cloud) [⁷](#fn7) | 0.42 | 0.19–0.68 | 12 |
| GLM-5.3 (cloud) [²⁴](#fn24) | 0.50 | 0.25–0.75 | 12 |
| GLM-5.3-flash (cloud) [²⁴](#fn24) | 0.42 | 0.19–0.68 | 12 |

**Zebra re-cut:** the BF16 anchor row landed (0.65 — the morning cell had died
silently on a port transition, re-run clean), and the champion's shipped-default
cell matches it exactly (0.65 at n=20, overlapping CIs throughout). The full-bank
re-score is the tighter measurement and the honest one to quote for the effort
axis: **sharp-low 0.567 vs sharp-medium 0.533** at n=30 both — low still leads,
but by one item, where the looser n=20-vs-n=12 pairing had suggested +0.15. An
earlier n=12 champion cell (0.50) is no longer listed: its template basis was
never recorded, so it is not comparable to any row above. Zebra remains
everyone's weakest battery — the CSP ladder is where headroom lives.

## DeepSeek V4.1 Flash Q2 — tested, parked

A 340.6 GiB MoE that streams experts from SSD: 4.4–4.9 t/s decode.
Below our speed floor and below our quant floor. Independently
replicated with the same verdict — parked
([tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo);
see the replication note in the recipe). Full recipe in
[configs/deepseek-v41-parked.md](configs/deepseek-v41-parked.md).

## The Doctor — 24/7 monitoring and the nightly auto-improve loop

The repo ships the monitoring layer exactly as it runs on the reference
box: [doctor/Doctor.py](doctor/Doctor.py) — a single-file, stdlib-only
web app (htmx, 2 s poll) — and its user unit
([doctor/Doctor.service](doctor/Doctor.service)).

### The WebUI (:8667)

- **System cards** — GPU (GTT counters — the real UMA numbers, not the
 1 GiB carve-out %), RAM, disk, CPU
- **Inference cards** — resident arm and recent loads, live tg and draft
 acceptance sparklines, service and `/health` state
- **Error banner** — health / service / journal / dmesg, minus
 known-benign patterns; **activity log** — live tail of the router
 journal
- **Resource links** (`/res/*`) — read-only excerpts: the router ini
 header, latest morning report, spec-sweep results, harvest stats, and
 `/res/doctor` — the latest nightly report
- **Read-only by design** — no ini writes, no arm swaps, no privileged
 calls; ~25 MB RSS (resident memory) flat, sub-1% of one core

Install — `ROUTER_UNITS` at the top of `Doctor.py` names the units it
watches (defaults are the reference box's `model-router-pwilkin`/
`-vanilla`; this repo's units are `llama-hip`/`llama-vulkan`):

```bash
cp doctor/Doctor.py ~/Doctor.py # edit ROUTER_UNITS if your units differ
install -Dm644 doctor/Doctor.service ~/.config/systemd/user/Doctor.service
systemctl --user daemon-reload && systemctl --user enable --now Doctor
```

`:8667` binds `0.0.0.0` without auth on the reference box — the same
trust decision as `:8080`. Bind loopback if that is not your threat
model.

### The nightly job (03:00, unattended, read-only)

Behind an idle gate, the doctor-dream skill (pi) runs a nightly checkup:
deterministic collectors digest the last 24 h — journal, inference,
resources, agent sessions, backlog, upstream — then an agent pass turns
the digest into a dated `DOCTOR_REPORT_*.md`, a human morning summary,
and panel data, served at `/res/doctor`. Upstream moves aren't just
recorded: the four engine repos — llama.cpp, pwilkin/strix-halo,
halo-box/strix-llama.cpp, antirez/ds4 — get a useful-to-us evaluation
against the champion recipe's axes (deep-prefill, decode, RAM/GTT,
PLE/lazy-load, speculation, gfx1151 correctness), with adopt-worthy
changes flagged as proposals; adoption itself stays human-finalized. It
never modifies the system.
Findings carry severity (P1–P3), evidence labeled OBSERVED vs INFERRED,
a proposed action, and a verify condition; carry items close only when a
later night's verify passes.

### The loop it enables — proposals out, human seal on every change

The doctor's findings feed an auto-improve loop (repo Principles #3):
findings and audits become *proposed* patches — to the serving stack,
the batteries, or the doctor itself — and a human authorizes each one
(`needs-human-authorization: yes` on anything touching config,
services, or policy). Two worked examples from the same day:

- **Loop working:** an audit caught the WebUI watching pre-rename
 unit names (`flash-router`) — showing a healthy router as down. Fixed,
 browser-verified, vendored into this repo the same day.
- **Loop correctly stopped at a human:** the 03:00 report's P1 "orphaned
 GTT leak" was an INFERRED misread — the GTT-vs-RSS gap is the PLE
 lazy-loading footprint; identical GTT/RAM after a clean reboot
 falsified the leak. The doctor proposed; the reboot's natural
 experiment disposed — no change landed on a wrong inference.

## Methodology

For those who want to check our work:

- **Wall-clock** (request sent → response complete), never server-reported
- **Prompts actually filled** — no empty-slot theater
- Same item-selection seed (1300); **scored cells ran greedy (temp 0.0)** —
 the serve recipe (temp 1.0, top_p 0.95, top_k 20) is the producer's
 recommendation for live traffic, while the batteries grade greedy for
 determinism; at temp 1.0 expect ±1–2 items variance at n=12
- **The champion is a thinking model** — reasoning tokens stream before
 the answer by default under our template (`reasoning_content`); the
 batteries grade the *last* python block after the thinking, and
 `max_tokens 6000` is sized to leave that thinking room
- Both natural translation conventions accepted (v2 battery; v1 had a
 10/12 ceiling by forcing one convention — fixed)
- All cells on identical hardware, same binary where noted
- Speed numbers from the pwilkin HIP binary; vanilla-VK serves Q5 at
 quality parity, but a fair speed comparison is owed (the vanilla config
 may need `-ngl 999` — testing pending)
- **Known limitation:** the iten12 battery measures translation quality,
 not coding ability — that is measured by the [GBench fcb15 and zebra
 cells](#coding--gbench-fcb15-deterministic-unit-tested); long-context
 retrieval items are planned.

## Acknowledgements

Standing on the shoulders of open-source giants:

- [llama.cpp](https://github.com/ggml-org/llama.cpp) — the foundation
- [unsloth](https://huggingface.co/unsloth) — the dynamic-quant GGUFs
- [pwilkin/strix-halo](https://github.com/pwilkin/strix-halo) — ROCm tuning
 and PLE lazy loading
- [halo-box/strix-llama.cpp](https://github.com/halo-box/strix-llama.cpp) —
 the community gfx1151 fork
- [antirez](https://github.com/antirez/ds4) — the [DS V4.1 inference
 engine](https://github.com/antirez/ds4) and [GGUF
 publication](https://huggingface.co/antirez/deepseek-v4.1-flash-gguf)
- [tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo) —
 independent Strix Halo benchmarks; shared methodology means shared
 assumptions — treat as a reproducibility reference, not independent
 validation; their run replicated our DeepSeek park verdict and
 supplied the ds4 host-sqrt patch
- [ROCm](https://github.com/ROCm/ROCm) — AMD's open compute stack
- [Arch Linux](https://archlinux.org) — the rolling-release distro

## License

All results, recipes, and configurations in this repository are released
under the [MIT License](LICENSE). The models and engines referenced are
subject to their own respective licenses.
