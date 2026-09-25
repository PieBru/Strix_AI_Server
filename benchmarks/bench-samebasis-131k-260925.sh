#!/bin/bash
# Companion to bench-samebasis-260925.sh — vanilla rows at the champion's
# SERVED context (131072): the 262k attempt answered pp128k (fork 747-761,
# vanilla HIP dies mid-deep-prefill); these stages give the vanilla row
# same-day Q4 cells at the fleet basis ctx.
set -u
Q4=~/Downloads/LLM/Qwen38/flash-next-unsloth/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf
MM=~/Downloads/LLM/Qwen38/flash-next-unsloth/mmproj-BF16.gguf
TPL=~/lab/templates/sharp-v22.5.0-low.jinja
VHIP=~/llama.cpp-fn-up/build-hip/bin/llama-server
VVK=~/llama.cpp-fn-up/build-vk/bin/llama-server
export HSA_OVERRIDE_GFX_VERSION=11.5.1
export GGML_HIP_ENABLE_UNIFIED_MEMORY=1

wait_up() { for i in $(seq 1 40); do curl -sf --max-time 2 "http://127.0.0.1:$1/v1/models" >/dev/null && return 0; sleep 5; done; return 1; }
kill_server() { pkill -9 -f "por[t] $1" 2>/dev/null; sleep 5; }

for st in "hip $VHIP 8092 vhip" "vk $VVK 8093 vvk"; do
  set -- $st; name=$1; bin=$2; port=$3; tag=$4
  echo "=== vanilla $name, Q4 DRAFTLESS, champion options, c=131072 ==="
  nohup "$bin" -m "$Q4" -ngl 999 -fa on --load-mode dio -ctk f16 -ctv f16 -c 131072 \
    -b 8192 -ub 4096 --parallel 1 --chat-template-file "$TPL" --jinja \
    -a default --mmproj "$MM" --host 127.0.0.1 --port $port > /tmp/$tag-q4-131k.log 2>&1 &
  wait_up $port || { echo "VANILLA-$name-131K FAILED TO LOAD"; kill_server $port; continue; }
  sleep 90
  cd ~/Piero/Work/Strix_AI_Server && \
    uv run python3 benchmarks/speed_probe.py --host 127.0.0.1:$port --model default --label $tag-q4-131k \
    > benchmarks/logs-260925/$tag-q4-131k-probe.log 2>&1
  cat benchmarks/logs-260925/$tag-q4-131k-probe.log | grep -v Traceback
  kill_server $port
done
echo "COMPANION-DONE"
