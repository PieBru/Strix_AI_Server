#!/bin/sh
# End-to-end drive test for the SOS arm: can it actually run pi, not just answer a
# single /chat/completions request? sos/check.py fires requests; this hands a real
# agent task to a real pi session and asserts the file it produced passes tests.
#
#   sh sos/drive-test.sh [workdir]        (~2 min, needs the arm up on :8082)
#
# Why this exists: on 260929 the arm measured 10/12 clean tool calls at pi's operating
# point (temp 1.0, what pi sends because pi sends NO temperature) and 0/16 at temp 0,
# yet nothing in the repo had ever run an agent on it. An unexercised path is a broken
# path, and this arm is the one you start when everything else is down.
set -eu

D=${1:-/tmp/sos-drive}
MODEL=${SOS_PI_MODEL:-sos_8082/sos}
rm -rf "$D"; mkdir -p "$D"

cat > "$D/app.py" <<'PY'
def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)

def slugify(text):
    return text.replace(" ", "-")
PY

cat > "$D/test_app.py" <<'PY'
from app import average, slugify


def test_average():
    assert average([2, 4]) == 3


def test_slugify_lower():
    assert slugify("Hello World") == "hello-world"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
    print("ALL PASS")
PY

cd "$D"
if python3 test_app.py >/dev/null 2>&1; then
    echo "SEED ERROR: the task as written already passes - nothing to fix" >&2
    exit 2
fi

timeout 900 pi --model "$MODEL" -p \
  'Fix the bug in app.py so that `python3 test_app.py` passes. Do not change test_app.py.'

if python3 test_app.py >/dev/null 2>&1; then
    echo "DRIVE PASS: $MODEL fixed the task end to end"
else
    echo "DRIVE FAIL: $MODEL left the tests red" >&2
    exit 1
fi
