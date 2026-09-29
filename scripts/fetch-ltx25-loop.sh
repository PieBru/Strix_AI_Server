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

ungated_missing() {
  bash scripts/fetch-ltx25.sh --verify 2>/dev/null | grep '^MISSING' | grep -vc 'video-vae-conv'
}

for pass in $(seq 1 $MAX_PASSES); do
  [ $(( $(date +%s) - START )) -gt "$CEILING_S" ] && { echo "12h ceiling reached"; break; }
  echo "=== pass $pass $(date -Is) ==="
  bash scripts/fetch-ltx25.sh
  n=$(ungated_missing)
  echo "=== pass $pass done: $n ungated file(s) still missing, $(du -sh ~/Downloads/LLM/LTX-2.5 2>/dev/null | cut -f1) on disk ==="
  [ "$n" = "0" ] && { echo "COMPLETE: ungated LTX-2.5 set verified"; break; }
  cur=$(du -sb ~/Downloads/LLM/LTX-2.5 2>/dev/null | cut -f1)
  if [ "$cur" = "$prev" ]; then stall=$((stall + 1)); else stall=0; fi
  prev=$cur
  [ "$stall" -ge 3 ] && { echo "no byte progress across 3 passes - uplink down, giving up for tonight"; break; }
  sleep 90
done
