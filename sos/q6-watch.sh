#!/bin/bash
# q6-watch.sh — unattended: wait for the .150 laptop's 3G download of the Spark Q6 to
# reach HF's exact content-length, then rsync it over LAN. Verifying the copy and
# swapping the symlink is a human/agent step, NOT automated here.
EXPECT=3612423424
LAP=piero@192.168.50.150
F=Downloads/LLM/Sharp-Spark-X2.5-4B-Q6_K_XL.gguf
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8"
prev=0
for i in $(seq 1 360); do
    sz=$($SSH $LAP "stat -c %s ~/$F 2>/dev/null")
    [ -z "$sz" ] && { echo "$(date +%H:%M:%S) laptop unreachable"; sleep 60; continue; }
    rate=$(( (sz - prev) / 60 ))
    echo "$(date +%H:%M:%S) $sz / $EXPECT  ($(( sz * 100 / EXPECT ))%, ${rate} B/s)"
    [ "$sz" = "$EXPECT" ] && break
    prev=$sz
    sleep 60
done
if [ "$sz" != "$EXPECT" ]; then echo "GIVEUP: still $sz after 6h"; exit 1; fi
echo "$(date +%H:%M:%S) download complete -> rsync over LAN"
rsync -a --partial --info=progress2 "$LAP:~/$F" ~/Downloads/LLM/ 2>&1 | tail -3
local_sz=$(stat -c %s ~/Downloads/LLM/Sharp-Spark-X2.5-4B-Q6_K_XL.gguf)
echo "RSYNC_DONE local=$local_sz expect=$EXPECT"
[ "$local_sz" = "$EXPECT" ] && echo "COPY_SIZE_OK" || echo "COPY_SIZE_MISMATCH"
