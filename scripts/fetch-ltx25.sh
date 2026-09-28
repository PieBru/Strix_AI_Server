#!/bin/bash
# fetch-ltx25.sh — pull the LTX-2.5 weight set this box's native renderer needs.
#
# WHY THIS EXISTS (260928, off-internet):
#   This box already BUILT the native LTX-2.5 renderer
#   (~/Downloads/Git/vllm.cpp/build-vulkan/examples/ltx2-gen, Sep 15) but has ZERO
#   LTX weights on disk. The .150 laptop's /mnt/2TB/LLM/LTX23/ scaffold is LTX-2.3
#   GGUF for ComfyUI behind a CUDA-only venv (.diffusion, cu13) — it cannot run on
#   gfx1151 — and its 8 model files are dangling symlinks into HF cache dirs that
#   were deleted. Operator ruled 260928: drop 2.3, target 2.5 native. The laptop's
#   only uplink is a slow 3G tether, so nothing big goes through it; this script
#   runs on THIS box the moment the line returns.
#
# PINS are from ~/Downloads/Git/vllm.cpp/docs/USAGE.md (the registry that
# AGENTS.md names for "which weights, and from where"), read 260928. SHA-256 is
# authoritative over revision: Lightricks published TWO DIFFERENT FILES at
# diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors — the path
# at 6c7e5e57 is 18,721,548,408 B / 7877 tensors, while every measurement in that
# tree used 18,721,432,024 B / 7876 tensors from 8a4ff96f. Fetching by revision
# alone can silently hand you the wrong arm. See vllm.cpp#1723.
#
# Usage:
#   scripts/fetch-ltx25.sh              # fetch + verify (~28 GB default set)
#   WITH_LORA=1 scripts/fetch-ltx25.sh  # + the 8.9 GB distilled lora-450
#   scripts/fetch-ltx25.sh --verify     # re-hash what is on disk, fetch nothing
#
# Resume-safe (curl -C -, .part until the hash matches). Re-run freely.

set -u

ROOT="${LTX_ROOT:-$HOME/Downloads/LLM/LTX-2.5}"
VERIFY_ONLY=0
[ "${1:-}" = "--verify" ] && VERIFY_ONLY=1

# relpath | repo | revision | bytes | sha256 (empty = no local pin, record it)
FILES=(
  "diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors|Lightricks/LTX-2.5|8a4ff96f581e72bedc1b44367581c49d544a05f1|18721432024|f9c4c2ae9a6aa8f732eb02a1c4c3b34888caad3dd35bb65deaf3b5043cda78fa"
  "text_encoders/gemma4-12b-with-proj-nvfp4-torchao.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|5a40ba9ab209a90ddb7943d1e3d374c51cfd3256|7423624178|12132b7157925332d2b21de9fc6f507c14f4f0cbc7081484d1968ebf8a19b4bf"
  "vae/ltx-2.5-video-vae-conv-bf16.safetensors|Lightricks/LTX-2.5|8a4ff96f581e72bedc1b44367581c49d544a05f1|1452269922|685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d"
  "vae/ltx-2.5-audio-vae-bf16.safetensors|Lightricks/LTX-2.5|8a4ff96f581e72bedc1b44367581c49d544a05f1|364866540|c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5"
  "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors|Lightricks/LTX-2.5|8a4ff96f581e72bedc1b44367581c49d544a05f1|0|"
)
# REQUIRED by ti2vid_two_stage / keyframe_interpolation / a2vid_two_stage /
# res2s_two_stage / dfr; NOT needed by distilled_two_stage. 8.9 GB, so opt-in.
[ "${WITH_LORA:-0}" = "1" ] && FILES+=(
  "loras/ltx-2.5-22b-distilled-lora-450-bf16.safetensors|Lightricks/LTX-2.5|6c7e5e573ac1667efc83407806fe9b0b93730e60|8899889568|"
)

mkdir -p "$ROOT"/{diffusion_models,text_encoders,vae,latent_upscale_models,loras}
fail=0

for entry in "${FILES[@]}"; do
  IFS='|' read -r rel repo rev bytes want <<<"$entry"
  dest="$ROOT/$rel"
  url="https://huggingface.co/$repo/resolve/$rev/$rel"

  if [ -f "$dest" ]; then
    got=$(sha256sum "$dest" | cut -d' ' -f1)
    if [ -z "$want" ] || [ "$got" = "$want" ]; then
      echo "OK       $rel (${got:0:12})"
      continue
    fi
    echo "BAD HASH $rel"
    echo "         want $want"
    echo "         got  $got  — keeping the file, delete it to re-fetch"
    fail=1
    continue
  fi
  [ "$VERIFY_ONLY" = "1" ] && { echo "MISSING  $rel"; fail=1; continue; }

  echo "FETCH    $rel"
  if ! curl -fL -C - --retry 5 --retry-delay 5 -o "$dest.part" "$url"; then
    echo "         fetch failed (line down?); $dest.part kept for resume"
    fail=1
    continue
  fi
  if [ "$bytes" != "0" ]; then
    size=$(stat -c %s "$dest.part")
    if [ "$size" != "$bytes" ]; then
      echo "         SIZE MISMATCH $size != $bytes — keeping .part"
      fail=1
      continue
    fi
  fi
  got=$(sha256sum "$dest.part" | cut -d' ' -f1)
  if [ -n "$want" ] && [ "$got" != "$want" ]; then
    echo "         HASH MISMATCH — wrong arm? keeping .part for inspection"
    echo "         want $want / got $got"
    fail=1
    continue
  fi
  [ -z "$want" ] && echo "         no local pin; sha256 = $got (record it in vllm.cpp docs/USAGE.md)"
  mv "$dest.part" "$dest"
  echo "OK       $rel (${got:0:12})"
done

echo
echo "encoder-config (REQUIRED beside the torchao NVFP4 tower — it carries no __metadata__):"
echo "  \$HOME/Downloads/Git/vllm.cpp/tests/vllm/models/ltx2_gemma4_text_config.json"
echo
echo "render smoke (note: ltx2-gen accepts --device cpu|cuda ONLY, main.cpp:517-518;"
echo "on this box that means CPU unless a vulkan/rocm selection is added upstream):"
cat <<EOF
  ~/Downloads/Git/vllm.cpp/build-vulkan/examples/ltx2-gen \\
    --dit $ROOT/diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors \\
    --model-version 2.5 --checkpoint-class distilled \\
    --video-vae $ROOT/vae/ltx-2.5-video-vae-conv-bf16.safetensors \\
    --audio-vae $ROOT/vae/ltx-2.5-audio-vae-bf16.safetensors \\
    --upsampler $ROOT/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \\
    --encoder $ROOT/text_encoders/gemma4-12b-with-proj-nvfp4-torchao.safetensors \\
    --encoder-config \$HOME/Downloads/Git/vllm.cpp/tests/vllm/models/ltx2_gemma4_text_config.json \\
    --pipeline-kind distilled_two_stage --prompt "a red fox in snow" \\
    --frames 25 --width 320 --height 192 --steps 8 --seed 20260812 \\
    --device cpu --workdir /tmp/ltx25 --out /tmp/ltx25/video.mp4
EOF
exit "$fail"
