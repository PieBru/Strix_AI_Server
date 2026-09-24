# Lab 260924 — halogen 0.13.8 (BYO-GGUF), Gufo + Qwen-Image-2.1

Both boxes dedicated to lab work (operator). Three questions, three answers.

## 1. halogen-flash-server 0.13.8 — "evolved a lot": confirmed

Same weights as today's engine A/B (**unsloth UD-Q4_K_XL GGUF**, loaded directly — the
0.7.0+ BYO-GGUF path), same box (strixy2, idle), same probe/corpus as the fork's cells.

| cell | halogen 0.13.8 | llama.cpp fork arm (260924) | halogen 0.5-era (260908) |
|---|---:|---:|---:|
| pp @4k | **980 t/s** | 865 | 339 @1.6k |
| pp @32k | **1297 t/s** | 909 | 925 @6.3k |
| pp @128k | **1252 t/s** (serves 262k ctx) | n/a (131k cap) | — |
| tg128 | 26.9 t/s | **33.5** | 30.9–41.9 |
| tg2048 | 22.8 t/s | **31.7** | — |
| fcb15 greedy / retry | 12/15 / 13/15 | **14/15 / 14/15** | **2/15** @4k |
| iten12-style wall-clock | 99–165 s/item (effort xhigh default) | 36–58 s/item | budget deaths |

**Reading.** halogen wins prefill by +13…+43 % and is the only engine here that serves a
262k context; the fork wins decode by ~+30 %. Quality: the 260908 collapse (thinking ate
the budget, 2/15) is **gone** — 12/15 greedy equals the Q5 incumbent's same-day cell,
though each item burns 2–3× the wall-clock at its default `reasoning_effort: xhigh`
(our cells ran sharp-low). Same two items fail as on Q5 (2, 13). Envelope: clean
(container, GTT bounded, swap 96 MiB, PSI 0).

## 2. Gufo + Qwen-Image-2.1 — generation *and* multi-reference editing, natively on HIP

`gufo serve image` loads the official pinned **Qwen/Qwen-Image-2.1** BF16 checkpoint
(30.9 GiB, revision-pinned downloader with byte-verified DONE marker) and speaks the
OpenAI Images API. Measured on strixy (:8081):

| operation | wall-clock | notes |
|---|---:|---|
| cold generation 1024² | 114 s | 40 steps; includes on-demand weight upload |
| warm generation 1024² | 111 s | denoise 110 s constant, prompt encode 84 ms |
| 2-reference edit 1024² | 200 s | "place the object from img1 in the room from img2" — valid PNG out |

Memory profile is the headline: weights are mapped and uploaded on demand — **RSS 31 GiB
while serving, 79 GiB host-available, PSI 0.00** — no conflict with a future co-resident
arm (gufo's own docs ship a llama-swap recipe for exactly that).

**Build notes (strixy, arch + rocm-nightly-gfx1151):** needed ROCm clang for host+HIP,
a one-line patch of GCC-16-git's `[[__gnu__::__noinline__]]` in
`/usr/include/c++/16/{format,stacktrace}` (backups `.bak-260924` beside them; both
compilers accept the `__attribute__` spelling), and `GUFO_SKIP_DS4=1` (env-gated in our
clone's CMakeLists + `stub.cpp`) because the nightly lld 24 crashes linking the ds4
device kernels (LTO CallGraph pass). Local clone: `~/Downloads/Git/gufo`.

## 3. The "Uncensored GGUF" repo — different runtime, be aware

`abenzerps/Qwen-Image-2.1-Uncensored-GGUF` is **ComfyUI packaging** (GGUF transformer +
separate qwen3vl text encoder + VAE, for ComfyUI-GGUF). Gufo does not read it — it runs
the official BF16 safetensors pinned by revision. If the uncensored fine-tune matters,
that is a ComfyUI stack (Python), separate from the gufo server; the gufo path is the
"simple CLI" one requested and the better webui backend.

## State left behind (lab mode)

| box | running | restore |
|---|---|---|
| strixy | gufo image server `:8081` (log `/tmp/gufo-image-serve.log`); router **stopped** | `systemctl --user start model-router-pwilkin.service` (after stopping gufo) |
| strixy2 | halogen container `:8731` (`docker rm -f halogen` to remove); `q5-serve` **stopped** | `systemctl --user start q5-serve.service` |

Artifacts: `/tmp/qimg/{img1.png,warm.json,room.png,edit.png}`,
`reruns-260919/q6-low-row/{halogen-probe-260924.log,fcb15-halogen-260924.txt,halogen-fcb15-260924.log}`.

**Webui pointer:** gufo's surface is OpenAI-compatible (`/v1/images/generations`,
`/v1/images/edits` multipart with up to 10 PNG/JPEG references, `seed`/`steps`/`size`
params, `/health`, `/v1/models`) — a thin client is enough to expose generate + edit +
multi-reference transforms.
