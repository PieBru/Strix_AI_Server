# Proposal: ACE-Step 1.5 on strixy-9ad3 + Gradio UI on :7862

Status: **DRAFT — awaiting operator authorization.** Nothing below is executed.
Researched 260927 against the live Ciao/ACE-Step install on `192.168.50.150`
(SSH, read-only) and this box's live state. OBSERVED vs INFERRED labeled.

---

## 1. Goal

Serve ACE-Step 1.5 (music generation) on this box behind a REST endpoint, with
a **simple Gradio web app on `:7862`** (same pattern as `:7860` qwen-image and
`:7861` H3 video), LAN-reachable, fully offline. Bonus phase: the
`ciao-music-server` facade (`:8190`, spec 034) so the Ciao voice assistant can
use this box as its music GPU.

## 2. What the research found (OBSERVED 260927)

### On .150 (`~/Piero/Work/ACE-Step-1.5`, `~/Piero/Work/Ciao`)

- **ACE-Step 1.5 official repo**, Python 3.12.13, venv 7.7 GB with
  `torch 2.10.0+cu128` (4.3 GB of it is `site-packages/nvidia/*`).
- **Entry points** (pyproject): `acestep-api` = FastAPI REST server
  (`acestep.api_server:main`), default launcher `start_api_server.sh` →
  `127.0.0.1:8001`. Routes: `GET /health`, `POST /release_task`,
  `POST /query_result` (async task pattern). **`api_server.py` does not import
  gradio** (grep count 0) — the REST server is UI-free.
- **Checkpoints already downloaded** (`checkpoints/`, ~7.5 GB):
  `acestep-v15-turbo` 4.5 G (2B DiT), `acestep-5Hz-lm-0.6B` 1.3 G,
  `acestep-5Hz-lm-1.7B` 3.5 G, `Qwen3-Embedding-0.6B` 1.2 G (text encoder),
  `vae` 322 M.
- **Deps are portable Python**: transformers>=4.51,<4.58, diffusers,
  accelerate, einops, soundfile, loguru, fastapi, uvicorn, safetensors,
  matplotlib, scipy, diskcache. `gradio==6.2.0` is pinned **but only for their
  own UI**, which we are not deploying.
- **`flash_attn` is optional** — `init_service_catalog.py` imports it inside
  `try/except ImportError → False`; falls back to SDPA. No triton/liger/
  bitsandbytes hard imports found.
- **Device abstraction exists**: `gpu_config.py` handles
  `auto/cuda/mps/xpu/cpu`, bf16 capability checks via
  `torch.cuda.get_device_capability` (ROCm answers this), per-profile
  `compile_model_default` with an MPS "no torch.compile" precedent. There is
  an official **Intel XPU port** (`README-XPU.md`) → the codebase is proven
  non-CUDA-portable.
- **Ciao is only an httpx client** (`src/ciao/music.py`): POST
  `{prompt, lyrics, duration, language, model, thinking}` → WAV bytes to
  `server_url` (default `http://localhost:7860/generate`). The real target is
  a **`ciao-music-server` facade on `:8190`** — and Ciao's own `config.toml`
  says: *"the :8190 facade (spec 034) isn't deployed … skip until built"*.
  **The facade was specced but never built on .150.** The `thinking` flag maps
  to tiers: `true` = turbo+0.6B LM, `false` = turbo-only.
- Benchmark reference from Ciao's `scripts/cuban_dj.py`: **RTF ≈ 0.25 on the
  4090** (12 s gen per 60 s of audio). README: <10 s/song on RTX 3090,
  minimum <4 GB VRAM (quantized/offload), XL-4B needs 12–20 GB.
- ⚠️ `.150` currently reports **`nvidia-smi: No devices were found`** — its GPU
  is not visible right now (driver/state issue). Does not block this proposal
  (we serve here), but blocks any CUDA A/B comparison until fixed.
- `.150` is **offline too** (pypi unreachable).

### On this box

- ROCm nightly torch **2.15.0.dev20260924+rocm10.0 is in the local uv cache**
  (`archive-v0`, plus the 20260925 build and rocm7.1 stable) — the exact stack
  MiniMax-H3 runs on today (gfx1151, GTT).
- Disk: 529 G free. Needed ≈ 15 G (repo + checkpoints + venv).
- Ports `:8001` and `:7862` are free. Existing: `:8080` gemma-collm,
  `:8188` ComfyUI, `:7861` h3-ui, `:7860` qwen-image (backend stopped).
- Precedent for the exact architecture: `:7861 → :8188` (thin gradio UI →
  localhost engine) and `:7860 → :8081`.

## 3. Proposed architecture

```
LAN browser ──▶ :7862 acestep-ui (simple gradio, 0.0.0.0)
                   │  POST /release_task + poll /query_result
                   ▼
             :8001 acestep-serve (acestep-api, 127.0.0.1)   ← "llama-server for music"
                   │  in-process torch (ROCm nightly, SDPA bf16, GTT)
                   ▼
             ~/Piero/Work/ACE-Step-1.5/checkpoints (turbo 2B + lm-0.6B + qwen3-emb + vae)

(optional phase 5)  :8190 ciao-music-facade (127.0.0.1 or LAN) — sync POST /generate → WAV
```

Two systemd user units, matching the box's existing pattern:

| unit | binds | role |
|---|---|---|
| `acestep-serve.service` | `127.0.0.1:8001` | acestep-api; lazy model load (`ACESTEP_NO_INIT=true`), `CHECK_UPDATE=false`; `Restart=on-failure` |
| `acestep-ui.service` | `0.0.0.0:7862` | ~80-line gradio app (modeled on `simple_video_ui.py`): prompt, lyrics, duration, language, thinking-tier → audio player |
| phase 5: `ciao-music-facade.service` | `127.0.0.1:8190` | ~40-line sync wrapper: `POST /generate {prompt,lyrics,duration,language,model,thinking}` → release_task + poll + WAV passthrough (spec 034 contract, exactly what `music.py` sends) |

Why server+client instead of one gradio process: matches the box pattern,
model survives UI restarts, Ciao and any other client can reuse the engine,
queue lives in one place.

## 4. Offline install plan (the interesting part)

Both boxes are off-internet and this box's uv cache lacks ACE-Step's deps.
**Trick: the project lives at the same absolute path on both boxes**
(`/home/piero/Piero/Work/ACE-Step-1.5`), so a venv transplant keeps shebangs
valid.

1. **rsync repo + checkpoints** from .150 (exclude `.venv`, `gradio_outputs`,
   `__pycache__`): ~7.6 GB, one rsync.
2. **rsync `.venv` too** (7.7 GB, path-identical → no shebang repair).
3. **Strip CUDA**: delete `site-packages/{torch,torchvision,torchaudio,
   nvidia*,cuda_kit*}` from the copied venv.
4. **Install ROCm torch from local cache**:
   `uv pip install --python .venv/bin/python --offline torch==2.15.0.dev20260924+rocm10.0`
   (+ its `rocm` meta-package; all present in this box's uv cache from the H3
   setup). Keep `torchvision/torchaudio` only if ACE-Step imports them
   (check at implementation; requirements list them for CUDA but the Linux
   ROCm nightly wheel ships without — H3 runs without them).
5. **Smoke**: `.venv/bin/python -c "import torch, acestep; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"`
   → must print `True` + `AMD Radeon ...` (HIP impersonates CUDA — this is
   what makes the whole "cuda" code path work unmodified).

Fallback if the transplanted venv misbehaves (e.g., a package compiled from
sdist on .150's glibc): fresh `uv venv` + `uv pip install --offline` per
package — but several deps (gradio 6.2.0, exact transformers range) are NOT in
this box's cache, so the transplant is strongly preferred; the fallback may
need a one-off online moment.

## 5. GPU / GTT budget and coexistence

| tenant | GTT estimate | basis |
|---|---|---|
| gemma-collm (`:8080`) | ~10 GB | OBSERVED (7.15 GB weights + ctx) |
| acestep-serve (turbo+0.6B) | ~10–12 GB | INFERRED: 7.3 GB weights bf16 + activations/VAE |
| MiniMax-H3 render | ~55 GB peak | OBSERVED 260926 (gemma+H3 PASS, 60 Gi free at peak) |
| **all three** | **~75–77 GB / 124 GB** | INFERRED — must be measured, see gate G5 |

Policy proposal: acestep-serve coexists with gemma-collm by default;
coexistence with an H3 render is **tested, not assumed** (gate G5). If it
fails: `Conflicts=` or stop-on-render, decided by the measurement.
The 27B-Q8 arm + ACE-Step + H3 is the known-bad combo (27B+H3 already OOMs) —
unchanged rule: video-render sessions use the gemma arm.

## 6. Performance expectation

- 3090 does <10 s/song (2B turbo); 4090 RTF 0.25. Strix Halo iGPU is below a
  3090 in fp16 density but has unlimited-ish GTT; H3 experience suggests
  large-DiT work at ~1×–3× slower than a mid dGPU.
- **Estimate: 20–60 s per 60 s track** (turbo, ~8 inference steps).
  INFERRED — first real generation replaces this number.
- `torch.compile` defaults ON for the "cuda" profile; ROCm nightly ships
  triton/inductor, but the safe first run is **compile OFF** (the codebase
  already has a no-compile path for MPS; exact flag/env located at
  implementation, worst case a one-line profile patch), then A/B it.

## 7. Risks

| # | risk | sev | mitigation |
|---|---|---|---|
| R1 | Some ACE-Step kernel/op unsupported on gfx1151 nightly (VAE convs, RoPE variants H3 doesn't exercise) | med | smoke → single short generation before anything else; failures are loud at first request |
| R2 | Transplanted venv has sdist-built package linked to .150's glibc/libs | med | import smoke test of every top-level dep; fallback = fresh venv (needs one online moment for uncached pins) |
| R3 | torch.compile on ROCm inductor crash | low | run compile-off first (§6) |
| R4 | Runtime tries an HF download (model-name mismatch → "not found locally" → hub fetch → offline hard-fail) | low | checkpoints copied verbatim; `CHECK_UPDATE=false`; verify `/health` + first gen with network already dead (it is) |
| R5 | GTT contention with H3 render | med | gate G5 measures it; Conflicts= if it fails |
| R6 | uv version drift (.150 0.12.15 vs here 0.12.19) affecting `--offline` cache reads | low | we install torch from THIS box's cache with THIS box's uv; transplant doesn't touch uv caches |
| R7 | gradio 6.2.0 pin vs this box's cached 6.28 | none | our UI is our own script on 6.28 (same as h3-video-ui); their server doesn't import gradio (verified) |

## 8. Success gates (binary, measured)

- **G1** venv smoke: `import torch, acestep` + `torch.cuda.is_available()` →
  exit 0, prints ROCm device.
- **G2** `acestep-serve` active, `GET :8001/health` → 200, **zero** outbound
  connection attempts (all non-localhost aborted).
- **G3** one 30 s generation via `curl /release_task` + `/query_result` →
  valid WAV (ffprobe duration 30±2 s), wall-time recorded.
- **G4** browser check (headless Chromium, every non-localhost request
  aborted): `:7862` renders, form submits, audio element gets a playable URL.
- **G5** coexistence: full H3 render while acestep-serve holds its models →
  no OOM in dmesg, both complete; GTT peak recorded. (If fail → policy
  decision returned to operator with numbers.)
- **G6** (phase 5) facade: `POST :8190/generate` with Ciao's exact payload →
  WAV bytes; Ciao `capability_probe` passes against it.

## 9. Rollback

Everything is additive: 2–3 new user units, one new project dir, one venv.
`systemctl --user disable --now acestep-* && rm -rf` the units + dir restores
the box exactly. Nothing existing is modified (no shared venv, no port
collision, no unit edits).

## 10. Effort

- Phase 0–1 (rsync + venv transplant + smoke): ~30–45 min (mostly the 15 GB
  rsync on LAN).
- Phase 2 (server unit + health): ~15 min.
- Phase 3 (gradio UI ~80 lines + unit): ~30 min.
- Phase 4 (gates G1–G5 incl. H3 coexistence render): ~30 min.
- Phase 5 (Ciao facade, optional): ~30 min + Ciao-side config pointer.
- **Total: ~2–2.5 h**, most of it waiting on generations.

## 11. Decisions for the operator

1. **Authorize phases 0–4?** (the :7862 lab service as specced)
2. **Phase 5 facade now or later?** (it's what finally unblocks Ciao's music
   skill — Ciao's config currently skips it as "not deployed")
3. Facade bind: `127.0.0.1:8190` (this box's clients only) or `0.0.0.0` so
   **Ciao on .150 can call it over LAN** (trusted-LAN no-auth policy would
   extend to it — consistent with your 260911 decision, but it's your call).
4. LM tier default in the UI: `turbo+0.6B` (better lyrics/structure, slower)
   vs `turbo-only` (fast). Proposal: expose the toggle, default 0.6B — the
   GTT budget comfortably fits both.
5. LM-1.7B (3.5 G, better musicality): copy it too while we're rsyncing
   anyway (disk is free), or keep the payload minimal?

## 12. RESULT — executed 260927, unattended

**The plan above was not the path taken.** Before rsyncing 15 GB, the local
`~/audio.cpp` build (Vulkan/RADV, `build-vk`) turned out to already serve ACE-Step
1.5 through its OpenAI-compatible server. That collapsed phases 0–2 to zero bytes of
download: the turbo GGUF is self-contained (DiT + planner LM + Qwen3-Embedding + VAE
+ tokenizers), so no Python ACE-Step repo, no kernels wheel, no venv transplant.

**What exists now** (all committed, all enabled at boot):

| unit | what | port |
|---|---|---|
| `acestep-serve.service` | `audiocpp_server --model acestep` (audio.cpp, Vulkan/RADV), config `acestep/acestep-server.json` | `127.0.0.1:8001` (loopback) |
| `acestep-ui.service` | `acestep/acestep_ui.py` — gradio, HTTP client only, no torch | `0.0.0.0:7862` (LAN, no auth per 260911) |

Weights: `~/audio.cpp/models/ACE-Step1.5-GGUF/turbo/` (5.9 G, already on disk).
Check: `uv run --no-project python acestep/check.py` → health + one real 5 s song.

**Measured on the 8060S** (OBSERVED, not vendor):

| gate | result |
|---|---|
| G1 20 s / 8 steps | 12.1 s, **RTF 0.60**, 3.84 MB wav, rms 7 800 |
| G2 30 s / 8 steps | 17.0 s, **RTF 0.57** — scales sub-linearly |
| G3 memory | ~13 GB resident; peak used 67.9 GB with gemma-collm up; no OOM |
| G4 UI | Playwright: real click → wav 200 / 983 KB, "5.1 s in 5.2 s (RTF 1.02)", **0 non-localhost requests** |
| G5 with full H3 render | H3 139 s (baseline ~125 s); ACE-Step 20 s song **also completes but in 78.8 s (RTF 3.94)**; min MemAvailable 49.8 GB |

**Answers to §11:** (1) done. (2)–(5) moot as specced — the LM tier is baked into the
GGUF (planner LM + Qwen3-Embedding ship inside `turbo/`), there is no separate
0.6B/1.7B file to choose, and the Ciao/OpenAI facade is audio.cpp's own
`/v1/audio/speech|lyrics|genres|caption` on `:8001`, currently loopback-only.
If Ciao on .150 should reach it, that is a bind change on `:8001`, not a new service.

**Known ceilings** (`ponytail`): UI exposes 7 of the ~40 engine params; no lyrics
rewrite / cover / repaint; no audio out of the box (gradio player + download only);
music is 6.5x slower while an H3 render holds the GPU — fine to coexist, slow to
share. `27b-collm` + ACE-Step + an H3 render at once is untested and 27B+H3 already
OOMs on its own (260927), so don't.
