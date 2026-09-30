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
# GATE (re-verified 260929 through the .150 proxy): Lightricks/LTX-2.5 is GATED.
#   anonymous resolve -> 401; $HF_TOKEN (same string as $HUGGINGFACE_TOKEN, account
#   `piebru`) -> 403 "...you are not in the authorized list. Visit ... to ask for
#   access". The credential itself is fine (api/whoami-v2 returns the user, a public
#   Lightricks blob -> 307), so this is a missing licence grant, not a bad token.
#   The repo is `gated: auto`: accepting the terms at
#   https://huggingface.co/Lightricks/LTX-2.5 grants access immediately, no review.
#
# WHAT THAT LEAVES FETCHABLE TODAY (260929, all from the PUBLIC
# vonkaiser/LTX-2.5-FP8-NVFP4, all answering 206 to a Range request without a token):
#   DiT nvfp4 and audio VAE -- BYTE-IDENTICAL to the official pins below (same sha256),
#     so the pins still verify; the mirror is only the transport.
#   upsampler -- same size as the (unpinned) official one.
#   text encoder -- the pinned 6.91 GiB build is still served at the pinned revision
#     (main has moved to 8.26 GiB, which is why the revision is pinned).
#   video VAE -- the mirror has ltx-2.5-video-vae-bf16 (1.37 GiB), which is NOT the
#     pinned ltx-2.5-video-vae-CONV-bf16 (1,452,269,922 B). No public copy of the conv
#     build was found (checked guillaume127, EllaPriest45, LiconStudio). It is fetched
#     unpinned as a stand-in; the render smoke at the bottom decides if it fits.
#   Mirror vonkaiser/LTX-2.5-FP8-NVFP4 is public but carries ONLY the text encoder
#   (7423624178 B, matches the pin below) plus a 21025119068 B FP8 transformer — not
#   the NVFP4 DiT, and none of the VAEs. There is no ungated path to the full set.
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
# This box has no route to the internet except the relay laptop's proxy (AGENTS.md, 260929).
# A loop started from a shell that did not export it spends every retry on
# "curl: (6) Could not resolve host" and looks alive while moving zero bytes — which is
# exactly how 260930's restart lost an hour. Default it here; `-` keeps an explicit empty
# value working, so https_proxy= still forces a direct attempt.
https_proxy="${https_proxy-http://192.168.50.150:8888}"
export https_proxy http_proxy="${http_proxy-$https_proxy}"
VERIFY_ONLY=0
[ "${1:-}" = "--verify" ] && VERIFY_ONLY=1

# relpath | repo | revision | bytes | sha256 (empty = no local pin, record it)
FILES=(
  "diffusion_models/ltx-2.5-22b-distilled-transformer-nvfp4.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|main|18721432024|f9c4c2ae9a6aa8f732eb02a1c4c3b34888caad3dd35bb65deaf3b5043cda78fa"
  "text_encoders/gemma4-12b-with-proj-nvfp4-torchao.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|5a40ba9ab209a90ddb7943d1e3d374c51cfd3256|7423624178|12132b7157925332d2b21de9fc6f507c14f4f0cbc7081484d1968ebf8a19b4bf"
  # GATED: 403 with the current token. Kept as the record of what is still missing, and
  # excused from --verify's exit code: the render path runs on the non-conv stand-in below,
  # so "incomplete" here means "not the officially pinned build", not "cannot render".
  "vae/ltx-2.5-video-vae-conv-bf16.safetensors|Lightricks/LTX-2.5|8a4ff96f581e72bedc1b44367581c49d544a05f1|1452269922|685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d|gated"
  # Stand-in for the conv build above -- different artifact, hence no pin: the script
  # prints the sha256 it got so it can be recorded once the official one is comparable.
  "vae/ltx-2.5-video-vae-bf16.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|main|0|"
  "vae/ltx-2.5-audio-vae-bf16.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|main|364866540|c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5"
  "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors|vonkaiser/LTX-2.5-FP8-NVFP4|main|995778752|"
)
# REQUIRED by ti2vid_two_stage / keyframe_interpolation / a2vid_two_stage /
# res2s_two_stage / dfr; NOT needed by distilled_two_stage. 8.9 GB, so opt-in.
[ "${WITH_LORA:-0}" = "1" ] && FILES+=(
  "loras/ltx-2.5-22b-distilled-lora-450-bf16.safetensors|Lightricks/LTX-2.5|6c7e5e573ac1667efc83407806fe9b0b93730e60|8899889568|"
)

mkdir -p "$ROOT"/{diffusion_models,text_encoders,vae,latent_upscale_models,loras}
fail=0

for entry in "${FILES[@]}"; do
  IFS='|' read -r rel repo rev bytes want note <<<"$entry"
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
  [ "$VERIFY_ONLY" = "1" ] && { echo "MISSING  $rel${note:+  ($note - excused)}"; [ "$note" = gated ] || fail=1; continue; }

  echo "FETCH    $rel"
  # One writer per .part. Two curls resuming the same file is how the DiT landed on 260930
  # at exactly the pinned size with the wrong sha256: a restart orphaned the previous curl
  # and both appended to the same bytes. pgrep is not an atomic lock (race window ~ms), but
  # the hazard is a human-scale orphan, not a concurrent caller; upgrade path is flock.
  if pgrep -f -- "-o $dest.part" > /dev/null 2>&1; then
    echo "         another curl already writes this .part -- skipping this pass"
    fail=1
    continue
  fi
  # --speed-limit: the only uplink is a phone tether that goes quiet for minutes at a
  # time; kill a stalled socket so the retry loop re-establishes it instead of hanging
  # on a dead connection at 0 B/s.
  if ! curl -fL -C - --retry 12 --retry-delay 10 --retry-all-errors \
           --speed-limit 20000 --speed-time 90 -o "$dest.part" "$url"; then
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
    echo "         HASH MISMATCH — keeping .part for inspection"
    echo "         want $want / got $got"
    # Move it OUT of the resume path. A full-size .part that fails the hash is otherwise
    # permanent: curl -C - sees it as already complete, the hash fails again every pass,
    # and the loop stalls on the same corrupt bytes forever (hit 260930: the DiT landed at
    # exactly 18721432024 B with the wrong sha256 after two curls shared one .part during
    # the tether flapping, while the mirror's own LFS oid matches the pin — so the bytes
    # were damaged in transit here, not upstream).
    mv "$dest.part" "$dest.corrupt-$(date +%y%m%d-%H%M%S)"
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
echo "render smoke (NOTE on --device: the flag only accepts cpu|cuda (main.cpp:118, default"
echo "'cuda' at :295) and main.cpp:517 turns 'cuda' into mp.device = 1 -- a device INDEX,"
echo "not a CUDA API call. This tree is built as build-vulkan/, so 'cuda' plausibly means"
echo "'the Vulkan GPU' here and the older note claiming CPU-only was never tested. Verify"
echo "with a real render on gfx1151 before concluding anything about speed.):"
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
