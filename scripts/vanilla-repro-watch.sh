#!/bin/bash
# vanilla-crash repro watcher: streams strixy2 dmesg + heartbeat to a LOCAL file
# (survives strixy2 hard-crash). Two guards: 30-min ceiling + dmesg-stream death.
LOG=/home/piero/Piero/Work/Qwen38/reruns-260919/q6-low-row/vanilla-crash-repro.log
echo "=== watcher start $(date -Is) pid=$$ ===" >> "$LOG"
ssh -o ConnectTimeout=5 -o BatchMode=yes strixy2.local 'journalctl -k -f -o short-precise --no-pager' >> "$LOG" 2>&1 &
DPID=$!
LAST_UP=""
for i in $(seq 1 360); do  # 360 x 5s = 30 min ceiling
  kill -0 $DPID 2>/dev/null || { echo "=== dmesg stream ended $(date -Is) ===" >> "$LOG"; break; }
  UP=$(ssh -o ConnectTimeout=4 -o BatchMode=yes strixy2.local 'uptime -s' 2>/dev/null || echo "SSH-DEAD")
  if [ "$UP" != "$LAST_UP" ]; then
    echo "[hb $(date -Is)] boot=$UP" >> "$LOG"
    LAST_UP="$UP"
    [ "$UP" = "SSH-DEAD" ] && { echo "[hb $(date -Is)] BOX DOWN" >> "$LOG"; sleep 10; }
  fi
  sleep 5
done
kill $DPID 2>/dev/null
echo "=== watcher end $(date -Is) ===" >> "$LOG"
