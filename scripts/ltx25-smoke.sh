#!/bin/bash
# ltx25-smoke.sh — render ONE tiny real LTX-2.5 clip and prove the file is a video.
#
# Why this exists: the weights arrive overnight from a mirror and the renderer has never
# run on this box. Every claim about tomorrow (does it load, does the GPU path work, how
# long does a clip take) starts here, and it must fail loudly rather than render garbage.
#
# Exit codes (binary, so the orchestrator can branch):
#   0 rendered and verified   1 preflight (weights/ffmpeg/RAM)   2 renderer refused
#   3 renderer "succeeded" but the output is not a decodable video
#
# The two decisions this script encodes, both read from the source rather than guessed:
#   * --encoder-config is MANDATORY for our text encoder. vonkaiser's
#     gemma4-12b-with-proj-nvfp4-torchao carries no __metadata__ at all; the engine
#     refuses it without a config (ltx2_video.cpp:2061) because layer_types /
#     global_head_dim / attention_k_eq_v resolve a DIFFERENT tower from a byte-identical
#     tensor set. The config is the one checked into vllm.cpp for this exact checkpoint.
#   * --dit-config must NOT be passed. Our DiT declares __metadata__["config"] and the
#     loader refuses a config beside a checkpoint that already declares one (:1440).
#   * --device cuda is a device INDEX (main.cpp:517 -> mp.device = 1), not a CUDA call,
#     and this tree is built with VLLM_CPP_VULKAN=ON / CMAKE_CUDA_COMPILER=NOTFOUND.
#     Whether it means "the Vulkan GPU" or dies here is what DEV=cuda|cpu measures.
set -u

LTX=${LTX:-$HOME/Downloads/LLM/LTX-2.5}
REPO=${REPO:-$HOME/Downloads/Git/vllm.cpp}
BIN=$REPO/build-vulkan/examples/ltx2-gen
GEMMA_CFG=$REPO/tests/vllm/models/ltx2_gemma4_text_config.json
# No ffmpeg on this box and no internet to install one; imageio-ffmpeg ships a static
# build with libx264, and ltx2-gen takes an explicit --ffmpeg path.
FF=${FF:-$(ls "$HOME"/.cache/uv/archive-v0/*/imageio_ffmpeg/binaries/ffmpeg-linux-* 2>/dev/null | head -1)}
OUT=${OUT:-/tmp/ltx25-smoke}
DEV=${DEV:-cuda}
FRAMES=${FRAMES:-9}          # LTX wants 8n+1
W=${W:-256}
H=${H:-256}
SEED=${SEED:-1}
PROMPT=${PROMPT:-"a red fox shaking snow off its fur in slow motion, forest, cinematic"}
# The tower is ~24 GB of host bf16 at the shipped 12B (docs/models/ltx-2-5.md:96) and the
# nvfp4 DiT is 17.4 GiB on disk; refuse rather than invite the OOM killer next to a
# download that is still running.
RAM_FLOOR_GB=${RAM_FLOOR_GB:-48}

fail() { echo "PREFLIGHT FAIL: $*"; exit 1; }

echo "=== preflight ==="
[ -x "$BIN" ] || fail "renderer not executable: $BIN"
[ -r "$GEMMA_CFG" ] || fail "gemma config missing: $GEMMA_CFG"
[ -n "$FF" ] && [ -x "$FF" ] || fail "no static ffmpeg found under ~/.cache/uv (imageio_ffmpeg)"
echo "renderer   $BIN"
echo "ffmpeg     $FF"
echo "cfg        $GEMMA_CFG"

missing=0
for f in diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors \
         text_encoders/gemma4-12b-with-proj-nvfp4-torchao.safetensors \
         vae/ltx-2.5-audio-vae-bf16.safetensors \
         latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors; do
  [ -f "$LTX/$f" ] || { echo "  MISSING $f"; missing=1; }
done
[ "$missing" = 0 ] || fail "weights incomplete (see MISSING above); fetch-ltx25-loop still running?"

# The pinned video VAE is the -conv- build and it is gated; the mirror's plain build is a
# different artifact. Use the pinned one when we have it, otherwise say out loud that the
# result is conditioned on a stand-in.
VAE=$LTX/vae/ltx-2.5-video-vae-conv-bf16.safetensors
if [ -f "$VAE" ]; then
  echo "video VAE  conv (the pinned build)"
else
  VAE=$LTX/vae/ltx-2.5-video-vae-bf16.safetensors
  [ -f "$VAE" ] || fail "no video VAE at all"
  echo "video VAE  NON-conv stand-in ($VAE) -- NOT the pinned build; a refusal here is expected company"
fi

avail=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)
echo "memory     ${avail} GiB available (floor ${RAM_FLOOR_GB})"
[ "$avail" -ge "$RAM_FLOOR_GB" ] || fail "only ${avail} GiB available; stop another arm first (27b-collm / comfyui-h3 / acestep-serve)"

mkdir -p "$OUT"
clip="$OUT/clip.mp4"
rm -f "$clip"

echo "=== render (device=$DEV ${W}x${H} frames=$FRAMES seed=$SEED) ==="
start=$(date +%s)
log="$OUT/renderer.log"
"$BIN" \
  --dit "$LTX/diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors" \
  --model-version 2.5 --checkpoint-class distilled \
  --video-vae "$VAE" \
  --audio-vae "$LTX/vae/ltx-2.5-audio-vae-bf16.safetensors" \
  --upsampler "$LTX/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" \
  --encoder "$LTX/text_encoders/gemma4-12b-with-proj-nvfp4-torchao.safetensors" \
  --encoder-config "$GEMMA_CFG" \
  --prompt "$PROMPT" \
  --frames "$FRAMES" --width "$W" --height "$H" --seed "$SEED" \
  --device "$DEV" --ffmpeg "$FF" --workdir "$OUT" --out "$clip" > "$log" 2>&1
rc=$?
tail -40 "$log"
wall=$(( $(date +%s) - start ))
echo "=== renderer exit=$rc in ${wall}s ==="
if [ "$rc" != 0 ]; then
  # Measured 260930, twice: the DiT and the Gemma tower load fine (106 s / 110 s, 13.75 GiB
  # host) and the load then dies here. Say WHY in one screen instead of leaving a C++ string.
  if grep -q "decoder_blocks is empty" "$log"; then
    echo "WHY  the only video VAE we hold is the DIFFUSION decoder (config.vae.decoder is"
    echo "     NADiffusionDecoder: stage_channels / diff_blocks). This engine refuses that class"
    echo "     BY NAME - ltx2_video_vae.h:8 'NOT ported', it needs the neighbourhood-attention"
    echo "     kernel. --allow-unported does NOT help: it is a DiT option (verified 260930, same"
    echo "     refusal, exit 1, after 110 s). The non-conv file is a stand-in for SIZE only."
    echo "FIX  the licence-gated conv build. Accept the terms at"
    echo "       https://huggingface.co/Lightricks/LTX-2.5"
    echo "     then:  HF_TOKEN=<token> bash scripts/fetch-ltx25.sh"
    echo "     (pinned rev 8a4ff96f581e72bedc1b44367581c49d544a05f1, 1452269922 B,"
    echo "      sha256 685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d)."
    echo "     This script picks the conv build up by itself the moment it is on disk."
  fi
  exit 2
fi

# No ffprobe in the static build; ffmpeg itself probes when given -i.
probe=$("$FF" -hide_banner -i "$clip" 2>&1)
if [ ! -s "$clip" ] || ! echo "$probe" | grep -q "Video:"; then
  echo "OUTPUT IS NOT A DECODABLE VIDEO:"; echo "$probe" | tail -6
  exit 3
fi
echo "$probe" | grep -E "Duration|Stream.*Video" | sed 's/^/  /'
echo "PASS  $clip  ($(stat -c %s "$clip") bytes, ${wall}s wall, device=$DEV, ${W}x${H}, ${FRAMES} frames)"
echo "NOTE  wall time above is the number tomorrow is planned around; the docs carry NO speed claim for a GPU arm (ltx-2-5.md:424)."
