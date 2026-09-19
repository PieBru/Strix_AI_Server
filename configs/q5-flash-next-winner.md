# Qwen3.8 Flash-Next Q5_K_XL — the winner

The best balance of quality, speed, and RAM on a single Strix Halo.
Serves the full 262k context with room to spare.

## What you need

| component | what | where |
|---|---|---|
| model | UD-Q5_K_XL (6 shards, 147.4 GiB) | [unsloth/Qwen3.8-Flash-Next-GGUF](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF) |
| MTP draft | shared-Q8 (2.8 GiB) | [same repo, MTP/ dir](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/main/MTP) |
| chat template | sharp v22.5.0 (`qwen3.8-froggeric-v22.5.0`) — the thinking control surface; [vendored here](templates/) | [froggeric/Qwen-Fixed-Chat-Templates](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates) |
| binary | pwilkin strix-halo, commit `b0f31f5876ef3856b55f5bb88072cc96e5effafe` | [pwilkin/strix-halo](https://github.com/pwilkin/strix-halo) |
| ROCm | 10.2 nightly, gfx1151-only | AUR: `rocm-nightly-gfx1151-bin` |

**Verify your download before serving** — 6 shards, 147.4 GiB total;
any mismatch means silent quality degradation. All sha256:

```
610922cdb1afe1094e95d7a3e86b12ee33317ebbf7320ac9344e21b6ae4bb69f  Qwen3.8-Flash-Next-UD-Q5_K_XL-00001-of-00006.gguf
494ca4ed3dbf97bc28da88af3890b8877b9032f909812d00c0526a9ca5e91d2e  Qwen3.8-Flash-Next-UD-Q5_K_XL-00002-of-00006.gguf
34efd79a80a1ce540a517a5d56171924b66ce1c38b04c904f17ad6d8ef17cf20  Qwen3.8-Flash-Next-UD-Q5_K_XL-00003-of-00006.gguf
9ee6bbe462e6830864382d629101490625b1c95afa15492b7ad550c7bed2dd13  Qwen3.8-Flash-Next-UD-Q5_K_XL-00004-of-00006.gguf
0b2437f661f584030cb5aeb8fb1bb70f6422518a6746bfcc0304167c7b6b8beb  Qwen3.8-Flash-Next-UD-Q5_K_XL-00005-of-00006.gguf
55dd96c5ad0863b06b6393151b9ad0ac727b8d58a62e02a296ca5d5ddbfee4a3  Qwen3.8-Flash-Next-UD-Q5_K_XL-00006-of-00006.gguf
2e788f8c511d8093c7b43cb87b2fd7e14228340318057f8fb20c86df2efe2355  mmproj-BF16.gguf
5ff54097406a905cf3a724c709124ceb0e3e10235ee862298969e91c96fa96e6  mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf
cdff39fb26b60dc90faa292e726655c6b21f62db497846e02e4c4bbab942a84a  sharp-v22.5.0.jinja
```

**Why this ROCm?** The monolithic nightly replaces ~20 split ROCm packages.
Remove old split packages first (`pacman -Rdd` the rocm/hip/hsa set) or
pacman will refuse to install.

**Note on the commit:** upstream has force-pushed since our build; the
commit above may not resolve via the GitHub web UI, but it is the exact
tree we built and serve from.

**[models.ini](../models.ini) is the canonical serve config** — the
commands below mirror it; when they disagree, the ini wins. The systemd
units read it from `/etc/llama/models.ini` — after editing the paths,
`sudo install -Dm644 models.ini /etc/llama/models.ini`.

**Build the binary:**

```bash
git clone https://github.com/pwilkin/strix-halo
cd strix-halo/src/llama.cpp
git checkout b0f31f5876ef3856b55f5bb88072cc96e5effafe   # pin to our build
```

```bash
git clone https://github.com/pwilkin/strix-halo
cd strix-halo/src/llama.cpp
PATH=/opt/rocm/bin:$PATH ROCM_PATH=/opt/rocm \
  cmake -B build -DGGML_HIP=ON -DGPU_TARGETS=gfx1151 \
  -DGGML_VULKAN=OFF -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF -G Ninja
PATH=/opt/rocm/bin:$PATH cmake --build build --parallel 16 --target llama-server
```

## Serve command (pwilkin binary, HIP)

> **Security:** bind to `127.0.0.1` by default. Only expose to your LAN
> if you understand the risks (unauthenticated completions, model metadata,
> slot manipulation). Use a reverse proxy with auth for any wider exposure.

```bash
llama-server \
  -m Qwen3.8-Flash-Next-UD-Q5_K_XL-00001-of-00006.gguf \
  -md mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  -dev ROCm0 -ngl 999 -fa on -fit off \
  --load-mode none --lazy-mode on-direct \
  -ctk f16 -ctv f16 -c 262144 -b 8192 -ub 4096 \
  --parallel 1 --jinja \
  --spec-type draft-mtp,ngram-mod --spec-draft-device ROCm0 --spec-draft-ngl 99 \
  --spec-draft-n-max 5 --spec-draft-n-min 0 \
  --host 127.0.0.1 --port 8080
```

### The flags that matter

- **`--load-mode none --lazy-mode on-direct`** — the 51 GiB PLE/n-gram
  table stays on disk. Each batch reads only the n-gram rows it needs
  via direct I/O (no mmap page faults). Without this, the 147 GiB model
  doesn't fit in 124 GiB.

- **`-ub 4096`** — caps the micro-batch to bound the PLE row-reader's
  memory. Without this bound, 32k+ real-text prefills exhaust RAM.

- **`-c 262144`** — full native context (262k tokens). KV cache ≈ 6 GiB
  at f16 (hybrid attention — 12 of 48 layers full-KV). Total ≈ 114 GiB —
  9.8 GiB theoretical headroom, ~3 GiB observed in practice (see the
  README's [RAM accounting](../README.md#ram-accounting)).

- **`--spec-draft-n-max 5`** — MTP draft width 5. This is the value our
  champion arm ran all its scored cells with (no flash-specific width
  sweep exists yet — a 3-vs-4-vs-5 comparison is on our todo list).

- **`-ngl 999`** — offload all layers to the GPU. Don't omit this.

- **`-fit off`** — disables in-fit tensor recomputation. We measured
  no quality or speed benefit on this model.

## Serve command (vanilla llama.cpp, Vulkan)

As of master `b23701f77` (PR #28136 merged), vanilla supports lazy loading:

```bash
llama-server \
  -m Qwen3.8-Flash-Next-UD-Q5_K_XL-00001-of-00006.gguf \
  -md mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  -ngl 999 -fa on -fit off \
  -lm dio -lzm on \
  -ctk f16 -ctv f16 -c 262144 -b 8192 -ub 4096 \
  --parallel 1 --jinja \
  --spec-type draft-mtp,ngram-mod --spec-draft-ngl 99 --spec-draft-n-max 5 --spec-draft-n-min 0 \
  --host 127.0.0.1 --port 8080
```

Quality is identical. The tradeoff is deep-prefill speed (currently ~3.5×
slower at 128k on Vulkan vs HIP — we're verifying whether some of this
gap is a missing flag or a real backend difference). Use vanilla for
upstream tracking; use HIP when prefill speed matters.
