#!/bin/bash
# ltx25-overnight.sh — when the weights land, prove this box can render LTX-2.5.
#
# Runs unattended behind fetch-ltx25-loop.sh. Deliverables by morning: a real clip, the
# wall-clock number for it, and a verdict on whether --device cuda means anything on
# gfx1151 (it is a device INDEX in a VLLM_CPP_VULKAN=ON build with no CUDA compiler, so
# nobody knows until it is run). If the GPU path fails we still want the CPU number, and
# we want the renderer's own refusal text, not a summary of it.
#
# Lab discipline (operator 260926): an experiment runs with the other GPU arms stopped.
# The restore is on EXIT, so a crash here cannot leave the box with its services down.
#
# Guards: 10 h ceiling on the wait; the wait pattern is bracketed so pgrep cannot match
# this script's own command line and wait for itself forever.
set -u
cd "$(dirname "$0")/.."
UNITS=(comfyui-h3 acestep-serve gufo-serve)
stopped=()

restore() {
  for u in "${stopped[@]}"; do
    if systemctl --user start "$u"; then echo "restored $u"; else echo "FAILED to restore $u - start it by hand"; fi
  done
}
trap restore EXIT

CEILING_S=$((10 * 3600))
START=$(date +%s)
while pgrep -f "[f]etch-ltx25-loop.sh" > /dev/null; do
  [ $(( $(date +%s) - START )) -gt "$CEILING_S" ] && { echo "wait ceiling reached, fetcher still running"; break; }
  sleep 60
done
echo "=== fetcher finished or abandoned: $(date -Is) ==="
bash scripts/fetch-ltx25.sh --verify > /tmp/ltx25-verify.log 2>&1; vrc=$?
grep -E "^(OK|BAD|MISSING)" /tmp/ltx25-verify.log
# Do not stop the GPU arms for a render that preflight will refuse in 0.2 s: on the night
# of 260930 the fetcher gave up 6.9 GiB short, and this script still took ComfyUI,
# ACE-Step and gufo-serve down and back up for nothing. A write failure here must not be
# mistaken for "incomplete", so the rc is checked, not the text.
if [ "$vrc" -ne 0 ]; then
  echo "weights still incomplete (verify exit $vrc) - leaving the other arms running; re-run this script once the fetch completes"
  exit 1
fi

for u in "${UNITS[@]}"; do
  if systemctl --user is-active --quiet "$u"; then
    systemctl --user stop "$u" && { stopped+=("$u"); echo "stopped $u"; }
  fi
done

# Measured 261001 with the FULL weight set (conv VAE present, all six pins OK):
#   device=cuda  dies at the FIRST denoise step, after 205 s of encoder work:
#     "vt: ltx2: no device glue table registered for this backend (vt::OpId::kLtx2)"
#   device=cpu   OOM-killed during load.dit, before any step: anon-rss 67.3 GB,
#     total-vm 115.7 GB, kernel oom-kill at 11:02:03 (the kernel picked ltx2-gen, not
#     llama-server; the box and the other units survived).
# The reason is not our stale build: kLtx2 and kLtx2Vae are RegisterOp'd for DeviceType::
# kCPU and kCUDA only (src/vt/cpu/cpu_ltx2*.cpp, src/vt/cuda/cuda_ltx2*.cu) and neither
# src/vt/vulkan/ nor src/vt/rocm/ contains an ltx2 file — checked locally AND at upstream
# HEAD fce3673 (mudler/vllm.cpp). A gfx1151 box with no CUDA compiler therefore has no
# LTX-2.5 render path at all. The CPU leg is not a fallback here, it is a 222 s walk into
# the OOM killer, so it is opt-in: FORCE_CPU=1 (and raise the smoke floor above 48 GiB).
for dev in cuda ${FORCE_CPU:+cpu}; do
  echo "########## SMOKE device=$dev $(date -Is) ##########"
  if DEV=$dev OUT="/tmp/ltx25-smoke-$dev" bash scripts/ltx25-smoke.sh; then
    echo "RESULT device=$dev PASS"
    ls -l "/tmp/ltx25-smoke-$dev/clip.mp4"
    break
  else
    echo "RESULT device=$dev FAIL exit=$?"
    # The VAE refusal is not a device property: ltx2_video_vae.h rejects the diffusion-
    # decoder class by name during LOAD, before any compute. Measured twice on 260930 and
    # again 261001 — cuda and cpu die identically at ~110 s. Retrying the other device buys
    # 110 s of the same answer; stop and say what is actually missing.
    if grep -q "decoder_blocks is empty" "/tmp/ltx25-smoke-$dev/renderer.log" 2>/dev/null; then
      echo "STOP  licence-gated conv VAE missing — device-independent, see WHY above"
      break
    fi
  fi
done
echo "=== done $(date -Is) ==="
