#!/bin/bash
# fetch-ltx25-loop.sh — keep re-running fetch-ltx25.sh until the ungated set is on disk.
#
# WHY: the only uplink is a phone tether. fetch-ltx25.sh already resumes (-C -, .part)
# and retries 12x, which survives a blip but not a 40-minute dead window; without this
# wrapper a stall at 02:00 means the operator wakes up to a half-file and no error.
#
# Guards (AGENTS.md: every loop gets a ceiling AND a break-on-repeat):
#   - 20 passes and a 12 h wall-clock ceiling
#   - stop after 3 consecutive passes with zero byte progress
# Completion is measured by --verify on the hashes, not by log freshness, and ignores
# the gated video-vae-conv entry, which cannot succeed until the licence is accepted.
set -u
cd "$(dirname "$0")/.."
MAX_PASSES=20
CEILING_S=$((12 * 3600))
START=$(date +%s)
stall=0
prev=0

# Completion is proven by the OK lines, never by the absence of MISSING ones: on 260930 a
# `set -u` trip made --verify print nothing at all, the old counter saw zero MISSING, and
# the loop declared "COMPLETE: ungated LTX-2.5 set verified" with 6.9 GiB still absent.
OK_NEEDED=5 # DiT, text encoder, video vae, audio vae, upsampler (the gated conv VAE is out)
ok_count() {
  local out ok miss
  out=$(bash scripts/fetch-ltx25.sh --verify 2>&1)
  ok=$(printf '%s\n' "$out" | grep -c '^OK ')
  miss=$(printf '%s\n' "$out" | grep -c '^MISSING')
  if [ $((ok + miss)) -eq 0 ]; then
    echo "!! --verify printed neither OK nor MISSING - it crashed; NOT treating that as complete" >&2
    printf '0\n'
    return
  fi
  printf '%s\n' "$ok"
}

for pass in $(seq 1 $MAX_PASSES); do
  [ $(( $(date +%s) - START )) -gt "$CEILING_S" ] && { echo "12h ceiling reached"; break; }
  echo "=== pass $pass $(date -Is) ==="
  bash scripts/fetch-ltx25.sh
  n=$(ok_count)
  echo "=== pass $pass done: $n/$OK_NEEDED ungated files verified, $(du -sh ~/Downloads/LLM/LTX-2.5 2>/dev/null | cut -f1) on disk ==="
  [ "$n" -ge "$OK_NEEDED" ] && { echo "COMPLETE: ungated LTX-2.5 set verified"; break; }
  cur=$(du -sb ~/Downloads/LLM/LTX-2.5 2>/dev/null | cut -f1)
  if [ "$cur" = "$prev" ]; then stall=$((stall + 1)); else stall=0; fi
  prev=$cur
  [ "$stall" -ge 3 ] && { echo "no byte progress across 3 passes - uplink down, giving up for tonight"; break; }
  sleep 90
done
