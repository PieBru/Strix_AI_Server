#!/bin/bash
# 260925 afternoon: same-basis engine re-measure (operator mandate)
# Q1: champion pp@128k — the fork at c=262144 (fn26 owed the cell: probe
#     window ~160k tokens > 131k served ctx)
# Q2: vanilla HIP + Vulkan with the CHAMPION's weights+options
#     (UD-Q4_K_XL + shared-Q4_K_M MTP where safe, f16 KV, b8192/ub4096,
#     sharp-low, fa on) — replacing the Q5 draftless proxy cells.
# SAFETY (fn28): vanilla + detached MTP draft = hard-crash class. Vanilla
# rows here are DRAFTLESS; the +draft variant is operator-gated.
# One GPU: stages run sequentially. Bench ports 8091-8093, killed+verified.
set -u
Q4=~/Downloads/LLM/Qwen38/flash-next-unsloth/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf
DRAFT=/tmp/fleet-bits/mtp-Qwen3.8-Flash-Next-shared-Q4_K_M.gguf
MM=~/Downloads/LLM/Qwen38/flash-next-unsloth/mmproj-BF16.gguf
TPL=~/lab/templates/sharp-v22.5.0-low.jinja
FORK=/tmp/llama-pw-bin/llama-server
VHIP=~/llama.cpp-fn-up/build-hip/bin/llama-server
VVK=~/llama.cpp-fn-up/build-vk/bin/llama-server
CTK=-ctk; CTV=-ctv   # placeholder to keep flags readable below
export HSA_OVERRIDE_GFX_VERSION=11.5.1
export GGML_HIP_ENABLE_UNIFIED_MEMORY=1
export LD_LIBRARY_PATH=/tmp/llama-pw-bin:$LD_LIBRARY_PATH

wait_up() { for i in $(seq 1 40); do curl -sf --max-time 2 "http://127.0.0.1:$1/v1/models" >/dev/null && return 0; sleep 5; done; return 1; }
kill_server() { pkill -9 -f "por[t] $1" 2>/dev/null; sleep 5; }

echo "=== stage 1: fork HIP, Q4+MTP, c=262144 (champion pp@128k cell) ==="
nohup "$FORK" -m "$Q4" -md "$DRAFT" -dev ROCm0 -ngl 999 -fa on -fit off \
  --load-mode none --lazy-mode on-direct -ctk f16 -ctv f16 -c 262144 \
  -b 8192 -ub 4096 --parallel 1 --chat-template-file "$TPL" --jinja \
  -a default --mmproj "$MM" --spec-type draft-mtp --spec-draft-device ROCm0 \
  --spec-draft-ngl 99 --spec-draft-n-min 0 --spec-draft-n-max 3 \
  --host 127.0.0.1 --port 8091 > /tmp/fork-q4-262k.log 2>&1 &
wait_up 8091 || { echo "FORK-262K FAILED TO LOAD"; tail -5 /tmp/fork-q4-262k.log; exit 1; }
sleep 90   # fn26 settle
cd ~/Piero/Work/Strix_AI_Server && \
  uv run python3 benchmarks/speed_probe.py --host 127.0.0.1:8091 --model default --label fork-q4-262k \
  > benchmarks/logs-260925/fork-q4-262k-probe.log 2>&1
cat benchmarks/logs-260925/fork-q4-262k-probe.log
kill_server 8091

echo "=== stage 2: vanilla HIP, Q4 DRAFTLESS, champion options, c=262144 ==="
nohup "$VHIP" -m "$Q4" -ngl 999 -fa on --load-mode dio -ctk f16 -ctv f16 -c 262144 \
  -b 8192 -ub 4096 --parallel 1 --chat-template-file "$TPL" --jinja \
  -a default --mmproj "$MM" --host 127.0.0.1 --port 8092 > /tmp/vhip-q4.log 2>&1 &
wait_up 8092 || { echo "VHIP-Q4 FAILED TO LOAD"; tail -5 /tmp/vhip-q4.log; exit 1; }
sleep 90
cd ~/Piero/Work/Strix_AI_Server && \
  uv run python3 benchmarks/speed_probe.py --host 127.0.0.1:8092 --model default --label vhip-q4 \
  > benchmarks/logs-260925/vhip-q4-probe.log 2>&1
cat benchmarks/logs-260925/vhip-q4-probe.log
kill_server 8092

echo "=== stage 3: vanilla Vulkan, Q4 DRAFTLESS, champion options, c=262144 ==="
nohup "$VVK" -m "$Q4" -ngl 999 -fa on --load-mode dio -ctk f16 -ctv f16 -c 262144 \
  -b 8192 -ub 4096 --parallel 1 --chat-template-file "$TPL" --jinja \
  -a default --mmproj "$MM" --host 127.0.0.1 --port 8093 > /tmp/vvk-q4.log 2>&1 &
wait_up 8093 || { echo "VVK-Q4 FAILED TO LOAD"; tail -5 /tmp/vvk-q4.log; exit 1; }
sleep 90
cd ~/Piero/Work/Strix_AI_Server && \
  uv run python3 benchmarks/speed_probe.py --host 127.0.0.1:8093 --model default --label vvk-q4 \
  > benchmarks/logs-260925/vvk-q4-probe.log 2>&1
cat benchmarks/logs-260925/vvk-q4-probe.log
kill_server 8093

echo "=== stage 4: fork HIP tg-only (stage-1 tg2048 disconnect re-run) ==="
nohup "$FORK" -m "$Q4" -md "$DRAFT" -dev ROCm0 -ngl 999 -fa on -fit off \
  --load-mode none --lazy-mode on-direct -ctk f16 -ctv f16 -c 262144 \
  -b 8192 -ub 4096 --parallel 1 --chat-template-file "$TPL" --jinja \
  -a default --mmproj "$MM" --spec-type draft-mtp --spec-draft-device ROCm0 \
  --spec-draft-ngl 99 --spec-draft-n-min 0 --spec-draft-n-max 3 \
  --host 127.0.0.1 --port 8091 > /tmp/fork-q4-262k-tg.log 2>&1 &
wait_up 8091 || { echo "FORK-TG FAILED TO LOAD"; exit 1; }
sleep 90
cd ~/Piero/Work/Strix_AI_Server && \
  uv run python3 benchmarks/speed_probe.py --tg-only --host 127.0.0.1:8091 --model default --label fork-q4-262k \
  >> benchmarks/logs-260925/fork-q4-262k-probe.log 2>&1
tail -3 benchmarks/logs-260925/fork-q4-262k-probe.log
kill_server 8091
echo "ALL-STAGES-DONE"
