#!/usr/bin/env python3
"""The SWAP card: the number the bar reads must survive the zswap suffix.

Why this exists (260930): the card body is built from ram_disk_cpu()'s swap string
with .replace(' GiB',''), and its bar parses float(st.split('/')[0]). Appending
"· 1.1 in zswap" is only safe while that parse still sees the leading number —
and htop-vs-free disagree on this box precisely because Zswapped is swap slots
that never reached the NVMe, so the split has to be shown, not hidden.

    uv run --no-project python tests/swap_card_check.py
"""
import builtins
import importlib.machinery
import importlib.util
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMINFO = """MemTotal: 130000000 kB
MemFree: 95000000 kB
MemAvailable: 103000000 kB
SwapTotal: 33554428 kB
SwapFree: 32057988 kB
SwapCached: 196236 kB
Zswapped: 1175104 kB
"""

loader = importlib.machinery.SourceFileLoader("d", os.path.join(ROOT, "doctor", "Doctor.py"))
spec = importlib.util.spec_from_loader("d", loader)
mod = importlib.util.module_from_spec(spec)
sys.modules["d"] = mod
loader.exec_module(mod)

real_open = builtins.open
builtins.open = lambda p, *a, **k: io.StringIO(MEMINFO) if p == "/proc/meminfo" else real_open(p, *a, **k)
try:
    pct, size = mod.ram_disk_cpu()[-2:]
finally:
    builtins.open = real_open

# free's own figure for these numbers: SwapTotal - SwapFree
committed = (33554428 - 32057988) / 1048576          # 1.42 GiB
assert size.startswith(f"{committed - 196236/1048576:.1f}/"), size   # swapcache excluded, as before
assert "1.1 in zswap" in size, size                                  # the htop delta, named
assert float(size.replace(" GiB", "").split("/")[0]) == 1.2, size    # the bar still parses
assert pct == "4%", pct                                              # 1269 MiB of 32 GiB

# below 50 MiB the share is noise and must not render as "0.0 in zswap"
builtins.open = lambda p, *a, **k: (io.StringIO(MEMINFO.replace("Zswapped: 1175104 kB", "Zswapped: 4096 kB"))
                                    if p == "/proc/meminfo" else real_open(p, *a, **k))
try:
    small = mod.ram_disk_cpu()[-1]
finally:
    builtins.open = real_open
assert "zswap" not in small, small

# The in/out rate must never render as a zero pair (operator 261001): the gate used to be
# `if si or so`, which a trickle satisfies, and 0.3 MB/s printed "in/out 0/0 MB/s".
for _si, _so in [(0.0, 0.0), (0.2, 0.4), (0.49, 0.49), (0.5, 0.5)]:
    assert "0/0" not in mod.swap_body("1.2/32 GiB", _si, _so), (_si, _so)
assert "in/out" not in mod.swap_body("1.2/32 GiB", 0.2, 0.4)
# ...but a real one-sided rate still shows, on either side
assert mod.swap_body("1.2/32 GiB", 1.4, 0.0).endswith("in/out 1/0 MB/s")
assert mod.swap_body("1.2/32 GiB", 0.0, 12.0).endswith("in/out 0/12 MB/s")

print("swap_card_check: PASS —", size)
