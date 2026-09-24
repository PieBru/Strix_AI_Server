#!/bin/sh
# Q4 quality-cell marathon — 260925 — vs strixy2:8080 (fn26 basis, arm resident)
# Batteries: iten12, sli10, zebra20, aime12 (seed 1300), aime60 census, fcb15 D+E+F ladder
# Smoke-tested path: uv run --with requests, rdir must exist, budget>=3.
cd /home/piero/Piero/Work/Qwen38/gbench || exit 1
H=http://strixy2.local:8080
R=/home/piero/Piero/Work/Strix_AI_Server/benchmarks
LOG=/tmp/q4-marathon.log
mkdir -p "$R"
echo "MARATHON_START $(date -Is)" >> "$LOG"

run() {
  step=$1; shift
  echo "=== STEP $step START $(date -Is)" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then echo "STEP $step OK $(date -Is)" >> "$LOG";
  else echo "STEP $step FAIL $(date -Is)" >> "$LOG"; fi
}

run iten12 uv run --with requests python3 scripts/probe.py \
  --battery iten12 --budget 12 --tag q4-iten12-260925 \
  --host $H --model default --rdir $R
run sli10 uv run --with requests python3 scripts/probe.py \
  --battery sli --budget 10 --tag q4-sli10-260925 \
  --host $H --model default --rdir $R
run zebra20 uv run --with requests python3 scripts/probe.py \
  --battery zebra --budget 20 --tag q4-zebra20-260925 \
  --host $H --model default --rdir $R
run aime12 uv run --with requests python3 scripts/probe.py \
  --battery aime --budget 12 --seed 1300 --tag q4-aime12-260925 \
  --host $H --model default --rdir $R --http-timeout 900 --max-tokens 16384
run aime60 uv run --with requests python3 scripts/probe.py \
  --battery aime --budget 60 --tag q4-aime60-260925 \
  --host $H --model default --rdir $R --http-timeout 900 --max-tokens 16384
run ladder uv run --with requests python3 scripts/fcb15_run.py \
  --items-file batteries/fcb15_v3def.py --mode single --temp 0 \
  --tag q4-ladder-260925 --host $H --model default

echo "MARATHON_DONE $(date -Is)" >> "$LOG"
