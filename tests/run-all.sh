#!/bin/sh
# Every check in tests/, one exit code. This is the "main stays green" command.
#
# uv --no-project: the checks are stdlib-only, and this pins the interpreter instead of
# picking up whatever python is first on PATH. --offline: this box usually has no internet,
# and a resolver stall looks exactly like a hanging test.
#
# Each check is the smallest thing that fails when its logic breaks (see the sabotage notes
# in each file). Nothing here starts a unit, touches :8080, or writes outside /tmp.
fail=0
for t in "$(dirname "$0")"/*_check.py; do
    name=$(basename "$t")
    printf '%-36s ' "$name"
    if uv run --offline --no-project python "$t" > "/tmp/strix-check-$name.log" 2>&1; then
        echo PASS
    else
        echo FAIL
        tail -4 "/tmp/strix-check-$name.log" | sed 's/^/    /'
        fail=1
    fi
done
[ "$fail" = 0 ] && echo "suite green"
exit "$fail"
