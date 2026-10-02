#!/usr/bin/env bash
# Is the halo-box/strix-llama.cpp NIGHTLY (releases/b1006) a viable serving binary here?
#   bash scripts/gate-llama-nightly.sh            # ~16 min, arms stopped, watchdog disabled
#   SKIP_BENCH=1 bash scripts/gate-llama-nightly.sh   # Q1 only (~1 min)
#
# WHY IT EXISTS. Our serving lineage (pwilkin/llama.cpp branch strix-halo) is dormant since
# b0f31f58 (260916) and building anything needs clang+libc++ (strixy2 lacks it). The fork now
# ships prebuilt gfx1151 ROCm nightlies, so the arms could move with no build at all.
#
# RESULT 261002 (b1006 = 0.5.0-dev build 11537 commit 0f36c46b, vs our pinned b0f31f58;
# 27B UD-Q8_K_XL + DFlash2 draft, -c 131072, arms stopped, GTT 0.0 GiB at start):
#   Q1 viability  PASS  loads at 131k, /health 200, 5/5 run_shell tool calls (gate-b1006.log)
#   Q2 speed      prefill +4.8..10.1 % nightly, decode -1.7..-2.2 % (bigger win deeper):
#                   pp4096        501.17 -> 531.50    pp4096 @ d32768  324.72 -> 357.51
#                   pp512         540.58 -> 566.78    pp512  @ d32768  340.34 -> 368.11
#                   tg128           7.23 ->   7.07    tg128  @ d32768    6.48 ->   6.37
#   Q3 the PR #91 "tuned" flags ( -lm dio -lzm on-direct -ctk/-ctv f16 -b 8192 -ub 1024 ) did
#      NOTHING on this model: 535.72 vs 540.58 pp512, inside noise. The 27B is arch qwen35;
#      #91 optimises qwen4exp (Flash-Next) QSA/GDN/PLE paths - and Flash-Next here is served by
#      gufo, not llama.cpp, so the +50 % is not reachable on this box today.
#   VERDICT: do not move a serving unit to a nightly for +5..10 % prefill and -2 % decode.
#     Re-run when halo-box tags a release, or when a Flash-Next-under-llama.cpp experiment runs.
#
# THE TRAP THIS SCRIPT EXISTS TO AVOID: llama-bench / llama-server resolve libllama.so through
# LD_LIBRARY_PATH, NOT through the directory they live in. With the pinned tree's lib on the
# path, the "nightly" binary ran the pinned engine and printed pinned numbers. Every leg resolves
# libllama.so with the same env the leg uses and is VOID if it does not come from that tree.
set -u
BIN=/home/piero/.local/share/qwen3.8-strix-halo/build/llama.cpp/bin
NIGHT=/home/piero/.local/share/llama-nightly/b1006
M=/home/piero/Downloads/LLM/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q8_K_XL-0000[1-3].gguf
DRAFT=/home/piero/Downloads/LLM/Qwen3.8-27B-GGUF/qwen3.8-27b-dflash2-model-q8_0.gguf
PIN=b0f31f58
NITE=0f36c46b
LOG=${LOG:-/tmp/gate-nightly.log}
: > "$LOG"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
# The unit's own environment, minus the model path: ROCm visible devices, HSA_ENABLE_SDMA=0.
eval "$(systemctl --user show strix-watchdog.service -p Environment --value | tr ' ' '\n' \
        | grep -E '^(HSA_|GALLIUM|ROC_|HIP_|OLLAMA_)' | sed 's/^/export /')"
restore() {
  # The disable stamp goes first: with it present the watchdog ignores a dead :8080 forever.
  rm -f "$HOME/.config/strix/watchdog.disable"
  for u in ${RESTORE[*]:-}; do systemctl --user start "$u" 2>>"$LOG"; done
  systemctl --user start strix-watchdog.service 2>>"$LOG"
  sleep 12
  say "RESTORED: $(systemctl --user is-active ${RESTORE[*]:-} | paste -sd' ') :8080=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health) watchdog=$(systemctl --user is-active strix-watchdog.timer)"
}
trap restore EXIT

# Capture what is actually up and restore exactly that. A hardcoded list is a trap: the arms are
# parked and started by hand (gemma = VRAM fallback, sos = emergency, comfyui = only during renders),
# so a fixed list would wake units the operator left down and leave the lab services asleep.
UNITS='^(27b-collm|gemma-collm|gufo-serve|sos-collm|acestep-ui|acestep-serve|whisper-stt|comfyui-h3|h3-video-ui|qwen-image-test)$'
mapfile -t RESTORE < <(systemctl --user list-units --type=service --state=active --plain --no-legend \
                       | awk '{print $1}' | sed 's/\.service$//' | grep -E "$UNITS")
say "will restore: ${RESTORE[*]}"
(( ${#RESTORE[@]} )) || { say "ABORT: captured nothing to restore - the query is broken, not the box"; exit 1; }
# The stamp, not just stopping the service: the timer re-starts the oneshot every ~2 min and a
# tick with :8080 down makes the watchdog act mid-gate. With the stamp present it stands down.
mkdir -p "$HOME/.config/strix"
touch "$HOME/.config/strix/watchdog.disable"
systemctl --user stop strix-watchdog.service   # it would restart the arms mid-gate
for u in "${RESTORE[@]}"; do systemctl --user stop "$u"; done
sleep 6
say "arms down (GTT $(awk '/GTT/ {print $2, $3}' /sys/class/drm/card0/device/mem_info_vram_used) GiB used); watchdog disabled"

# --- Q1: does the nightly serve the 27B at the unit's context, and call tools? -------------
PORT=8090
say "Q1: nightly serving at -c 131072 on :$PORT"
LD_LIBRARY_PATH="$NIGHT" "$NIGHT/llama-server" -m "$M" \
  --model-draft "$DRAFT" --spec-type draft-dflash --spec-draft-max-runs 2 --spec-draft-max-len 16 \
  --mmproj /home/piero/Downloads/LLM/Qwen3.8-27B-GGUF/mmproj-F16.gguf \
  -ngl 99 -c 131072 -np 1 -fa on --jinja --host 127.0.0.1 --port $PORT \
  --alias default > /tmp/gate-q1.log 2>&1 &
SRV=$!
for _ in $(seq 60); do [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/health)" = 200 ] && break; sleep 5; done
say "Q1 health=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/health) $(grep -m1 'running on port' /tmp/gate-q1.log | tr -s ' ')"
kill $SRV 2>/dev/null; wait $SRV 2>/dev/null

bench() { # $1=leg name  $2=lib dir  $3=extra flags
  local out rc resolved
  # Identity = the library that will actually load, NOT the binary's own --version string.
  resolved=$(LD_LIBRARY_PATH="/opt/rocm/lib:$2" ldd "$2/llama-bench" 2>/dev/null | awk '/libllama\.so/ {print $3}')
  case "$resolved" in
    *"$2"*) : ;;
    *) say "$1 VOID: libllama resolved to ${resolved:-nothing} (expected under $2)"; return ;;
  esac
  out=$(timeout 1500 env LD_LIBRARY_PATH="/opt/rocm/lib:$2" "$2/llama-bench" -m "$M" \
        -md "$DRAFT" -ngl 99 -fa 1 -c 8192 -np 1 -r 1 -p 512,4096 -n 128 -d 0,32768 $3 2>&1)
  rc=$?
  say "$1 -> $(basename "$2") $("$2/llama-bench" --version 2>/dev/null | grep -oE 'commit [0-9a-f]+' | awk '{print $2}') lib=$(dirname "$resolved") (rc=$rc)"
  echo "$out" | grep -E '^\| *qwen|error|Error' | sed 's/^/    /' >> "$LOG"
}
[ "${SKIP_BENCH:-0}" = 1 ] && exit 0

say "=== recipe A: serving-like flags ==="
bench "A/pinned"  "$BIN"   ""; bench "A/nightly" "$NIGHT" ""
say "=== recipe B: fork-tuned (PR #91 style) ==="
bench "B/pinned"  "$BIN"   "-lm dio -lzm on-direct -ctk f16 -ctv f16 -b 8192 -ub 1024"
bench "B/nightly" "$NIGHT" "-lm dio -lzm on-direct -ctk f16 -ctv f16 -b 8192 -ub 1024"
say "=== gate complete ==="
