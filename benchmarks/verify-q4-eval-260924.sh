#!/bin/bash
# verify-q4-eval-260924.sh — external re-runnable acceptance gate for the Flash-Next Q4+MTP
# evaluation (260924). Read-only: touches nothing, kills nothing. Exit 0 = all gates pass.
#
#   bash benchmarks/verify-q4-eval-260924.sh
#
# Environment: run from the repo root (or anywhere — paths are absolute). Needs ssh
# BatchMode access to strixy2.local. Swap/RAM thresholds are the operator's 260924 rule.
set -u
W=/home/piero/Piero/Work/Qwen38/reruns-260919/q6-low-row
BB=/home/piero/Piero/Work/Strix_AI_Server/benchmarks
S="ssh -o ConnectTimeout=8 -o BatchMode=yes strixy2.local"
fails=0
chk(){ # chk <label> <expected-substring> <file>
  if grep -qa -- "$2" "$3" 2>/dev/null; then echo "PASS  $1"; else echo "FAIL  $1  (no '$2' in $3)"; fails=$((fails+1)); fi
}
num(){ # num <label> <value> <max>
  if [ -n "${2:-}" ] && [ "$2" -le "$3" ] 2>/dev/null; then echo "PASS  $1 = $2 (<= $3)"; else echo "FAIL  $1 = ${2:-none} (> $3 or unreadable)"; fails=$((fails+1)); fi
}

echo "== 1. artifacts =="
for f in "$BB/q4-vs-q5-report-260924.md" "$W/q4-mtp-ab.log" "$W/iten12-q4.jsonl" \
         "$W/fcb15-q4.txt" "$W/fcb15-q5-260924.txt" "$BB/results.json"; do
  [ -s "$f" ] && echo "PASS  exists: $f" || { echo "FAIL  missing/empty: $f"; fails=$((fails+1)); }
done
chk "A/B phase A measured"      "q4-A-speed-tg2048: " "$W/q4-mtp-ab.log"
chk "A/B phase B measured"      "q4-B-speed-tg2048: " "$W/q4-mtp-ab.log"
chk "both phases echoed"        "q4-B-echo: "        "$W/q4-mtp-ab.log"
chk "draft acceptance captured" "draft acceptance"   "$W/q4-mtp-ab.log"
chk "A/B self-restored q5-serve" "q5-serve restored" "$W/q4-mtp-ab.log"
chk "iten12 12/12 for Q4"       "SCORE: 12/12"       "$W/q4-mtp-ab.log"
chk "iten12 raw rows = 12"      '"item": 11'         "$W/iten12-q4.jsonl"
chk "fcb15 Q4 census"           "greedy 14/15"       "$W/fcb15-q4.txt"
chk "fcb15 Q5 same-day census"  "greedy 12/15"       "$W/fcb15-q5-260924.txt"
chk "results.json carries the day's cells" "q4_xl_mtp_260924" "$BB/results.json"

echo "== 2. published =="
cd "$BB/.." || exit 1
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] \
  && echo "PASS  HEAD == origin/main ($(git rev-parse --short HEAD))" \
  || { echo "FAIL  HEAD not pushed"; fails=$((fails+1)); }
git ls-files --error-unmatch benchmarks/q4-vs-q5-report-260924.md >/dev/null 2>&1 \
  && echo "PASS  report is tracked" || { echo "FAIL  report untracked"; fails=$((fails+1)); }

echo "== 3. strixy2 envelope + service =="
M=$($S 'free -m | sed -n 2,3p' 2>/dev/null)
RAMU=$(echo "$M" | awk '/^Mem:/{print $3}'); RAMT=$(echo "$M" | awk '/^Mem:/{print $2}'); SWU=$(echo "$M" | awk '/^Swap:/{print $3}')
PSIF=$($S 'head -2 /proc/pressure/memory | tail -1 | cut -d= -f2 | cut -d, -f1 | cut -d. -f1' 2>/dev/null)
ACT=$($S 'systemctl --user is-active q5-serve.service' 2>/dev/null)
HL=$($S 'curl -s --max-time 4 localhost:8080/health' 2>/dev/null)
num "strixy2 ram% (used/total)" "$(( ${RAMU:-0} * 100 / ${RAMT:-1} ))" 100
num "strixy2 swap MiB"          "${SWU:-9999}" 500
num "strixy2 psi-full avg10%%"  "${PSIF:-9999}" 5
echo "$ACT" | grep -qa active && echo "PASS  strixy2 q5-serve active" || { echo "FAIL  strixy2 q5-serve not active"; fails=$((fails+1)); }
echo "$HL" | grep -qa '"ok"' && echo "PASS  strixy2 :8080 healthy" || { echo "FAIL  strixy2 :8080 unhealthy ($HL)"; fails=$((fails+1)); }

echo "== 4. local box envelope + arm =="
L=$(free -m | awk '/^Mem/{printf "%d %d ", $3, $2} /^Swap/{printf "%d", $3}')
LPCT=$(( $(echo "$L" | awk '{print $1}') * 100 / $(echo "$L" | awk '{print $2}') ))
num "local ram%"        "$LPCT" 100
num "local swap MiB"    "$(echo "$L" | awk '{print $3}')" 600
num "local psi-full avg10 (%%)" "$(head -2 /proc/pressure/memory | tail -1 | cut -d= -f2 | cut -d, -f1 | cut -d. -f1)" 5
curl -s --max-time 5 localhost:8080/v1/models 2>/dev/null | grep -qa '"loaded"' \
  && echo "PASS  local :8080 has a loaded arm" || { echo "FAIL  local :8080 has no loaded arm"; fails=$((fails+1)); }

echo
if [ "$fails" -eq 0 ]; then echo "ALL GATES PASS"; else echo "$fails GATE(S) FAILED"; fi
exit $((fails > 0))
