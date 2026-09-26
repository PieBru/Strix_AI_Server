# MiniMax-H3 on strixy (lab box) — feasibility & build proposal

2026-09-26 · draft for operator decision · research: diffusers docs, HF repo,
Comfy-Org repack, community benchmarks (all links at bottom)

---

## 0. LEGAL GATE — read first, this is the only blocker

The **MiniMax H3 Community License excludes the EU, UK, Korea and the USA**
("Applicable Territory" = worldwide *except* those; §V.4: use outside it is
*not authorized*). This box is in Italy. Downloading/running H3 here is a
territory violation of the license unless MiniMax grants a license (they say
EU-deployment requests go to api@minimax.io, "MiniMax H3 licensing —
authorization request").

Personal/lab use, no distribution, outputs kept private = low practical risk,
but it is **your call to make explicitly**, not mine to assume. Everything
below is conditional on that ack. (Encoder Qwen3-VL-32B itself is Apache-2.0;
the restriction is on the H3 transformer + VAEs.)

## 1. What MiniMax-H3 is (OBSERVED from docs/repo, released 2026-08-02)

- **33B dense single-stream transformer**, jointly denoises **video + stereo
  audio** in one packed sequence (no vocoder, no post-hoc audio pass).
  Guidance-distilled: no CFG, no negative prompt, 1 forward/step.
- **3 workflows**: `t2va` (text→video+audio), `fl2va` (first/last keyframe),
  `ref2va` (up to 9 images + 3 videos + 3 audio refs, order-sensitive).
- **Constraints**: 24 fps fixed, 5–15 s (`17n+5` frames), 768 px short-edge
  canvas (multiples of 32; 960×544 ≈ 2.3× faster/step than trained 1344×768).
- **Weights**: repo 498 GB total. Transformer 61.7 GB bf16 per partition;
  Qwen3-VL-32B conditioner 62.1 GB bf16. Shared VAEs small.
- Official integration is **diffusers Modular-only** (no classic pipeline);
  **ComfyUI day-0 native support** (v0.31+) with repacked single files;
  DiffSynth-Studio NF4 also exists (min 7 GB VRAM w/ aggressive offload).
- Official prompt-rewrite pipeline (H3-Context-IR) is **closed** (API-only) —
  prompts must be hand-crafted; ComfyUI ships 10 style embeddings + templates.

## 2. Why this box can actually run it (OBSERVED local facts)

| Resource | strixy-9ad3 | H3 need |
|---|---|---|
| RAM (unified) | **124 GiB** | int8 recipe wants ~75 GB host — fits with arms parked |
| GPU | Radeon 8060S **gfx1151**, ROCm installed, `rocminfo` OK | ROCm 7.2.2 + gfx1151 nightly torch proven on this exact APU (community vLLM recipe) |
| **GTT (GPU-addressable)** | **124 GB** | the Strix-Halo play: model weights sit in GTT "VRAM" — no per-step host↔GPU streaming, unlike a 24 GB card |
| Disk | 639 GB free | minimal set ≈ 50 GB (ComfyUI) / ≈ 130 GB (diffusers bf16) |
| Current load | 88 GB used (27B + image 2.1) | video jobs need the box mostly to themselves |

**Speed expectation (INFERRED from measured anchors):** DGX Spark (same
bandwidth class, 273 vs 256 GB/s) does a 5 s 768×576 clip in ~9 min; RTX 3060
12 GB does 1344×768·124f in ~36 min; RTX 5090 does 5 s in 46 s (Turbo).
Strix estimate: **5 s @ 960×544 ≈ 8–20 min** (20 steps), **Turbo 4-step ≈
2–5 min**, 768p ≈ 2–3× that. Lab-usable, not interactive.

## 3. Engine decision (ladder: existing component before custom code)

**Recommended: ComfyUI + Comfy-Org repack.** Reasons: day-0 native H3
support, queue + REST API + web UI already built (we only write the thin
client), pruned checkpoints (modulation weights → lookup tables, ~40 % of
params, lossless per ComfyUI blog) that make the memory math trivial on a
unified-memory box, Turbo LoRAs for fast drafts, Fun ControlNet + embeddings
for later experiments.

**File set for ROCm (int8_convrot is CUDA-13-only — skip it):**

| File | ~Size | Role |
|---|---|---|
| `minimax_h3_fl2va_pruned_fp8_scaled.safetensors` | ~26 GB | transformer (RDNA3.5 has native FP8; fallback `pruned_bf16` ~37 GB also fits) |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | ~17 GB | conditioner ("does not require Blackwell" per repack README) |
| `minimax_h3_video_vae_int8_convrot` → use bf16 variant if kernel-less | ~2 GB | video VAE |
| `minimax_h3_audio_vae_fp32.safetensors` | ~2 GB | audio VAE |
| `minimax_h3_fl2v_turbo_4step` + `8step` LoRAs | ~2 GB | fast drafts |
| **Total** | **≈ 50 GB** | ref2va (+26 GB) later, only if the lab keeps it |

Working set ≈ 50 GB resident (GTT) + 10–20 GB activations @ 544p → **coexists
with the 27B arm (~28 GB)**; image 2.1 should park during renders (Conflicts).

**Fallback: diffusers Modular int8 recipe** (official docs) — torchao
Int8WeightOnly v2 + block-level offload, ~75 GB host. Heavier, needs
diffusers-main, but it is the *reference* path and the only one for `ref2va`
parity if ComfyUI's repack lags. Keep as plan B, not first build.

**Not proposed:** DiffSynth NF4 (extra framework, quality unverified),
original 498 GB repo download (YAGNI), SGLang/vLLM-Omni (serving stack we
don't need for a demo).

## 4. Demo app — mirror of the image-2.1 pattern

Same shape as `QImage21/tests/simple_gradio_ui.py` (thin HTTP client, zero
torch in the UI process):

```
gradio app :7861  ──POST workflow JSON──▶  ComfyUI :8188 (queue API)
   │  prompt · keyframe upload (optional) · duration 5/10/15s ·
   │  canvas preset (544p/768p) · steps (4 Turbo / 8 / 20) · seed
   └─ polls /history → shows rendered <video> (mp4 w/ stereo audio) + log
```

- **`comfyui-h3.service`** — manual start (NOT enabled at boot; lab box),
  `Conflicts=gufo-serve.service qwen-image-test.service`, memory gate in
  ExecStartPre (`free -g` ≥ 85 available or refuse with a clear log line).
- **`h3-test-app.service`** — gradio client, `Requires=comfyui-h3`,
  `server_name="0.0.0.0"` + a `gradio-v6-relay-7861` twin (same socat trick;
  the tailscale-v6 trap is real on this box).
- **Doctor**: add both units to the footer toggle + a "H3 idle/rendering"
  line (job count from `/queue`), so the panel tells the mode honestly.
- Renders land in `~/Piero/Work/H3/renders/` (dated names), served by
  ComfyUI's static route; the app embeds them.

## 5. Phased plan — each gate is a binary pass/fail

| Phase | Work | Pass criterion (rerunnable) |
|---|---|---|
| **P0** | Operator acks §0 territory risk | written ack |
| **P1** | Env: uv venv + ROCm nightly torch for gfx1151 (pin the ROCm 7.2.2 recipe proven on this APU) + ComfyUI ≥0.31 | `uv run python -c "import torch;print(torch.cuda.get_device_name(0))"` → gfx1151 + a 4k×4k matmul exits 0 |
| **P2** | Weights: `hf download Comfy-Org/MiniMax-H3` the §3 subset | `du -sh` ≈ 50 GB, files in ComfyUI model dirs |
| **P3** | Smoke render: t2v, 960×544, 125 f (5 s), Turbo 4-step, seed 42 | mp4 exists; `ffprobe` shows ~5 s video **and** an audio stream; wall-time recorded as the box's H3 baseline |
| **P4** | Demo app + units + v6 relay | Playwright: navigate :7861 → submit → rendered `<video>` visible; units survive `systemctl restart` |
| **P5** | Doctor awareness + memory-gate tuning + (optional) ref2va/Turbo matrix | Doctor footer shows H3 state; footer toggle starts/stops the stack |

Est. effort: P1–P3 one evening (download-bound), P4 half a day. P5 opportunistic.

## 6. Risks & mitigations

1. **gfx1151 torch wheels** — official ROCm PyTorch images lack gfx1151;
   AMD nightly index + the community ROCm-7.2.2 recipe (identical APU) is the
   known-good path; there are segfault reports on ROCm 7.1 → pin 7.2.2, smoke
   matmul before anything else. *(biggest risk, first gate)*
2. **fp8_scaled on RDNA3.5** — FP8 exists on gfx1151 but ComfyUI's fp8 path
   is mostly NVIDIA-tested; fallback ladder: fp8 → pruned bf16 (fits GTT) →
   diffusers int8 (plan B).
3. **Attention** — flash-attn is not built for gfx1151; ComfyUI falls back to
   SDPA automatically (small decode tax, fine).
4. **Memory contention** — hard Conflicts + ExecStartPre gate; worst case a
   render evicts swap → the 2.1 GB-swap lesson says watch PSI, park arms.
5. **First-unexercised-path class** (our own fault pattern) — every phase
   runs for real before the next is trusted; no "should work" claims.
6. **License updates** — MiniMax may extend territory terms; re-check before
   anything leaves the lab (sharing renders publicly needs the
   machine-generated disclosure per AUP §12 anyway).

## Sources

- diffusers H3 pipeline docs (fetched full): huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3
- model repo + license: huggingface.co/MiniMaxAI/MiniMax-H3 (LICENSE fetched full)
- ComfyUI repack + file table: huggingface.co/Comfy-Org/MiniMax-H3 · docs.comfy.org/tutorials/video/minimax/minimax-h3 · blog.comfy.org/p/minimax-h3-day-0-support-in-comfyui
- benchmarks: github.com/YHK-AI/MiniMax-H3-Benchmark · minimax-h3.wiki/local/minimax-h3-performance-benchmarks · blog.chaosyn.com (RTX 5090)
- gfx1151 ROCm: rocm.docs.amd.com RDNA3.5 optimization · github.com/LucRoot/Strix-Halo-Linux-VLLm-ROCm_72 · ROCm/TheRock issue 1364 (flash-attn gap)