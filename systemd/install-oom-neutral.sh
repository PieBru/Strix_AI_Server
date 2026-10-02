#!/bin/bash
# Install the oom-neutral drop-in on the heavy GPU arms (see oom-neutral.conf).
# Idempotent; prints the resulting config vs live table.
#
# 260928: closes doctor P1 (opened 260922 — kernel OOM killed the serving router
# child because oom_score_adj 200 volunteered llama-server). The thin gradio UIs
# (h3-video-ui, qwen-image-test, whisper-stt) stay at the 200 default on purpose:
# under real pressure they should die before a 40 GB arm does.
set -eu
UNITS=(27b-collm gufo-serve acestep-serve comfyui-h3 gufo-llm sos-collm)
DEST="${1:-$HOME/.config/systemd/user}"
SRC="$(dirname "$(readlink -f "$0")")/oom-neutral.conf"

for u in "${UNITS[@]}"; do
  mkdir -p "$DEST/$u.service.d"
  install -m 644 "$SRC" "$DEST/$u.service.d/oom-neutral.conf"
done
[ "$DEST" = "$HOME/.config/systemd/user" ] && systemctl --user daemon-reload

worst=0
for u in "${UNITS[@]}"; do
  pid=$(systemctl --user show "$u.service" -p MainPID --value 2>/dev/null)
  live=dead
  [ -n "$pid" ] && live=$(cat "/proc/$pid/oom_score_adj" 2>/dev/null || echo gone)
  cfg=$(systemctl --user show "$u.service" -p OOMScoreAdjust --value 2>/dev/null)
  printf "%-14s cfg=%s live=%s\n" "$u" "$cfg" "$live"
  case "$live" in ''|dead|gone) ;; *) [ "$live" -ge 200 ] && worst=1 ;; esac
done

# 261002: this table printed cfg=0 live=100 on 260930 and the cfg column was read as
# "volunteering removed". The kernel only ever uses live, and a user manager cannot push a
# unit below its own score, so the script now exits non-zero while any unit still sits at the
# 200 default (drop-in missing, or the unit has not restarted since it was installed).
if [ "$worst" = 1 ]; then
  echo "NOT NEUTRAL: a unit is still at the 200 user-unit default. The drop-in takes effect on" >&2
  echo "the NEXT start -- restart the unit, then re-run. cfg= alone means nothing." >&2
  exit 1
fi
