# DeepSeek V4.1 Flash Q2 — tested and parked

A 340.6 GiB (365.7 GB) MoE model that doesn't fit in RAM, so it streams experts from
SSD. We measured it, it works, but it's too slow for a solo coder on one
box. Here's the recipe if you want to try it yourself.

## What you need

| component | what | where |
|---|---|---|
| model | DeepSeek-V4.1-Flash-Q2.gguf (340.6 GiB) | [antirez/deepseek-v4.1-flash-gguf](https://huggingface.co/antirez/deepseek-v4.1-flash-gguf) |
| engine | ds4 (kyuz0 fork, commit `09f12d4`) | [kyuz0/ds4](https://github.com/kyuz0/ds4) |
| patch | host-sqrt portability fix (vendored, pinned to commit `3ab42146`) | [patches/ds4-host-sqrt.patch](patches/ds4-host-sqrt.patch) |
| ROCm | same 10.2 nightly as our Q5 setup | see q5-flash-next-winner.md |

**Verify the download before serving** — the file is large enough that
corruption is a real risk:

```
size:    365713686528 bytes
sha256:  1ce6a8f8806205c13330d7ca287bd198331dc5ca35ccc5d8a9a92a188a6f6f42
```

## Build the engine

```bash
git clone https://github.com/kyuz0/ds4 ~/ds4
cd ~/ds4
git checkout --detach 09f12d415bb42efc1887e9330b0aebe9c32902da
git apply configs/patches/ds4-host-sqrt.patch
PATH=/opt/rocm/bin:$PATH ROCM_PATH=/opt/rocm make strix-halo ROCM_ARCH=gfx1151
```

**Apply the vendored patch** (pinned, from commit `3ab42146` of
tomasreminek/strix-halo — also included at
[patches/ds4-host-sqrt.patch](patches/ds4-host-sqrt.patch)):

```bash
git apply configs/patches/ds4-host-sqrt.patch
```

The host-sqrt patch fixes a portability issue (device-only `rsqrtf`
replaced with `1.0f / sqrtf`) — without it, the build may succeed but
produce wrong results on some ROCm versions.

## Serve command

```bash
# Bind loopback by default — add auth before any wider exposure
./ds4-server --rocm \
  -m /path/to/DeepSeek-V4.1-Flash-Q2.gguf \
  --ssd-streaming \
  --ssd-streaming-cache-experts 24GB \
  --ctx 8192 --batched-session 1 \
  --host 127.0.0.1 --port 8000
```

### The flags that matter

- **`--ssd-streaming`** — routes MoE expert weights through SSD instead
  of trying to hold all 365 GiB in RAM (which is impossible on 124 GiB)
- **`--ssd-streaming-cache-experts 24GB`** — an in-RAM cache for the most
  recently used experts. 24 GiB is the sweet spot: larger values push the
  total past what a 124 GiB box can spare after the OS and static buffers
- **`--ctx 8192`** — keep the context small; the streamed model doesn't
  have RAM headroom for a large KV cache

## What we measured

| metric | value |
|---|---:|
| decode (streamed) | 4.4–4.9 t/s |
| RAM footprint | ~35 GiB resident (with 24G expert cache) |
| recommended ceiling | `MemoryMax=56G` in systemd (35G workload + 21G guard for SSD I/O buffers and driver overhead) |

## Independent replication — agrees

[tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo)
(docs/deepseek-v41-single-strix-halo.md, marker `DEEPSEEK_V41_COMMUNITY_20260917`)
ran the same experiment on the same APU — identical checkpoint (size +
sha256), same ds4 commit `09f12d4`, the vendored patch above originates
from their repo, and they converged on the same runtime posture (24G
expert cache after their 80G runs pressure-aborted, `MemoryMax=56G`, 8k
context). Their verdict matches ours: it runs, but no practical win —
the optimization pass closed with no replicated acceleration,
MTP/DSpark unsupported on this model path, and a model-authored coding
trial (Three.js game, 4 attempts, 83 min of model wall) ended with zero
accepted artifacts.

Their speeds reconcile with ours under their own don't-mix-tables rule:
end-to-end completion rates **3.9–4.2 t/s** (below our 4.4–4.9 decode,
as end-to-end must be); their headline **7.12 t/s** is an HTTP
completion-token rate including reasoning — explicitly not native
decode. Real populated-context runs passed at 7k/32k/64k prompts
(622/564/556 output tokens in 149/371/687 s total wall); 128k stayed
inconclusive under a 905 s timeout. One divergence: their build pins
ROCm 7.2.4 where we ran the 10.2 nightly — the patch is version-
agnostic C; both worked.

## Why we parked it

At ~4.5 t/s decode, generating a 1000-token response takes about 3.5
minutes. Our Q5 stack does it in 40 seconds at a speed floor (20 t/s tg) that
wasn't met. The bottleneck isn't the model — it's streaming 365 GiB of
MoE experts from a single NVMe. A two-box split (each box hosts half the
layers) is the natural next step, and ds4 supports it natively. That's
a future experiment.
