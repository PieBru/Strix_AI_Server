#!/bin/bash
# mirror-check.sh [host] — fail if a repo mirror of a live unit has drifted.
# The repo's gufo-llm.service drifted from strixy2 in three ways (binary, -c, and
# WorkingDirectory back inside the repo) and nothing noticed until 260929. Comments
# are stripped: a mirror's prose is ours, its ExecStart/paths are the box's.
# Exit 0 = every mirror matches live. Needs ssh to the host (LAN only).
set -u
HOST=${1:-192.168.50.184}
REPO=$(cd "$(dirname "$0")/.." && pwd)
pairs="systemd/gufo-llm.service .config/systemd/user/gufo-llm.service
systemd/ctx256k.conf .config/systemd/user/gufo-llm.service.d/ctx256k.conf
systemd/zz-cache-disk.conf .config/systemd/user/gufo-llm.service.d/zz-cache-disk.conf"
# "$@" empty means read stdin; a named file otherwise. (A `grep -v | grep -v` body
# without "$@" silently ignored its argument and made every mirror look empty.)
strip() { sed -e '/^#/d' -e '/^[[:space:]]*$/d' "$@"; }
rc=0
while read -r local remote; do
  [ -z "${local:-}" ] && continue
  if [ ! -f "$REPO/$local" ]; then echo "MISSING $local"; rc=1; continue; fi
  if ! diff -q <(strip "$REPO/$local") <(ssh -n -o BatchMode=yes -o ConnectTimeout=5 "$HOST" "cat ~/$remote" 2>/dev/null | strip) >/dev/null; then
    echo "DRIFT $local vs $HOST:~/$remote"
    diff <(strip "$REPO/$local") <(ssh -n -o BatchMode=yes "$HOST" "cat ~/$remote" 2>/dev/null | strip) | head -6
    rc=1
  else
    echo "OK    $local"
  fi
done <<< "$pairs"
exit $rc
