# Halogen 0.11.0 — closed-engine evaluation

We tested the closed-source Halogen engine to see if it beats our open
llama.cpp stack. It doesn't — here's what we measured.

## What you need

| component | what | where |
|---|---|---|
| engine | Docker image — pull tag `0.11.0` and record your own digest before use | `ghcr.io/peonist-ai/halogen-flash-server:0.11.0` |
| model | native `.hgn` format (not GGUF) | [peonist-ai/halogen-qwen3.8-flash-next](https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next) |
| files | w4b main (124G) + overlay (2.6G) + vision (0.9G) + tokenizer dir | revision `b8dbb46d03f5d1d0e63b432c2ca763db7e8e0aa4` |

Download the tokenizer separately — the container won't start without it
and the error message is easy to miss:

```bash
mkdir -p ~/models/halogen/tokenizer
for f in chat_template.jinja generation_config.json merges.txt \
         tokenizer.json tokenizer_config.json vocab.json; do
  curl -L -o ~/models/halogen/tokenizer/$f \
    "https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next/resolve/b8dbb46d03f5d1d0e63b432c2ca763db7e8e0aa4/tokenizer/$f"
done
```

## Serve command

```bash
MODEL_DIR="$HOME/models/halogen"
VIDEO_GID="$(getent group video | cut -d: -f3)"
RENDER_GID="$(getent group render | cut -d: -f3)"

docker run --rm --name halogen-qwen38 \
  -p 127.0.0.1:8731:8731 \
  --device /dev/kfd --device /dev/dri \
  --group-add "$VIDEO_GID" --group-add "$RENDER_GID" \
  --ipc=host --ulimit memlock=-1:-1 \
  -e HALOGEN_CTX=131072 \
  -e HALOGEN_KV_POOL_POSITIONS=131072 \
  -e HALOGEN_KV_SLOTS=1 \
  -e HALOGEN_MAX_TOK=32768 \
  -e HALOGEN_PROMPT_CACHE=2 \
  -e HALOGEN_VISION_TOWER=1 \
  -e HALOGEN_VERBOSE=1 \
  -v "$MODEL_DIR:/models:ro" \
  ghcr.io/peonist-ai/halogen-flash-server:0.11.0 all
```

The port binds to localhost only — don't expose this unauthenticated to
your network. Use an SSH tunnel or a reverse proxy with auth.

## What we measured

| what | elapsed | wall-clock t/s |
|---|---:|---:|
| decode 256 tok, short prompt | 7.9 s | 32.4 |
| decode 256 tok, 32k prompt | 9.4 s | 27.3 |
| decode 256 tok, 126k prompt | 10.0 s | 25.6 |
| prefill 4k tokens | 5.5 s | 742 |
| prefill 32k tokens | **546 s (9.1 min)** | **60** |
| prefill 128k tokens | **1770 s (29.5 min)** | **71** |

Decode beats our open stack at every depth we measured (32.4 / 27.3 /
25.6 vs our 23.6–25.4 t/s) — we acknowledge that. But prefill collapses
at depth, and that's the deal-breaker for coding and agentic workloads
where you routinely send 30k+ token prompts. The 128k cell completed at
1770s — 30s under our client timeout — real, but with a thin margin.

## Why we didn't adopt it

1. **Prefill at depth is 9–13× slower** than our open stack (60 vs 807
   wall-clock t/s at 32k). A 32k codebase context takes 9 minutes vs 40
   seconds.
2. **Closed source** — we can't inspect, patch, or contribute. Bugs go
   through a vendor's timeline.
3. **Native `.hgn` format** — incompatible with the entire GGUF ecosystem.
   You can't swap quant tiers, mix drafts, or use llama.cpp tooling.
4. **Our decode gap is small and shrinking** — 32.4 vs 23.6 t/s at short
   range; upstream llama.cpp Vulkan/HIP kernels are closing in. The open
   stack's prefill advantage is structural and growing.

We keep the assets staged in case the engine opens or the prefill path
improves. But for now: open stack, decisively.

### Independent run reports higher decode — basis unresolved, verdict unchanged

[tomasreminek/strix-halo](https://github.com/tomasreminek/strix-halo)
reports the same engine (Halogen 0.11.0, ROCm) decoding Qwen3.8
Flash-Next at **44.66 t/s short / 40.08 @64k / 38.03 @~126k** with MTP
and their quality overlay — above our 32.4/27.3/25.6 plain wall-clock
cells. We haven't reconciled the basis (overlay and acceptance settings
vs our stock container defaults); their own caveat — the
serial-vs-MTP byte-identity gate failed review — also stands. It does
not move our verdict: their table measures decode only and never tests
deep prefill, the axis where Halogen collapses for coding workloads and
the reason we rejected it. No re-measure is planned to chase the decode
gap: our open-source-only policy (README, Policy 5) discards the engine
regardless of speed — the gap is recorded for completeness, not as a
to-do. The decision reopens only if the engine's source opens.
