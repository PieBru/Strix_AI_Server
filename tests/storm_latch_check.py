"""Runnable check for the swap-storm latch in doctor/Doctor.py.

    uv run --no-project python tests/storm_latch_check.py

The operator's rule (260930): a storm must stay on the card until someone clears it, so a
past one can be investigated. Two properties matter and both are driven here through the
real `storm_tick` / `storm_html`:

  * it does not blink — a couple of over-threshold samples must NOT latch (the old badge
    followed the instantaneous 2 s rate and flashed rapidly on real paging);
  * it does not forget — once latched it survives the storm ending, and the file survives
    a Doctor restart.

Writes only to a temp latch file; nothing here touches the live sampler or :8080.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


D = _load("doctor_storm_under_test", REPO / "doctor" / "Doctor.py")

TMP = pathlib.Path(tempfile.mkdtemp()) / "storm.json"
D.STORM_FILE = str(TMP)
P0 = (1_000_000, 2_000_000)          # arbitrary cumulative vmstat pages at rest
HI = D.STORM_MBPS * 10                # comfortably over the line
STEP = 4096                           # pages moved per over-threshold sample


def reset():
    D.STORM.clear()
    D._SW["hits"] = 0
    D.CACHE["swio"] = (0.0, 0.0)
    D.storm_save()


def check_no_latch_no_badge():
    reset()
    assert D.STORM == {}, "fresh state should be empty"
    assert not pathlib.Path(D.STORM_FILE).exists() or json.loads(TMP.read_text()) == {}


def check_two_samples_do_not_latch():
    """Anti-flutter: below STORM_N consecutive samples, nothing is recorded."""
    reset()
    for i in range(D.STORM_N - 1):
        D.storm_tick(HI, (P0[0] + STEP * (i + 1), P0[1]))
    assert D.STORM == {}, f"latched after only {D.STORM_N - 1} samples: {D.STORM}"


def check_alternating_never_latches():
    """The exact failure the operator saw: rate above, below, above, below."""
    reset()
    for i in range(20):
        D.storm_tick(HI if i % 2 == 0 else 0.0, (P0[0] + STEP * (i // 2 + 1), P0[1]))
    assert D.STORM == {}, f"a blinking rate latched a storm: {D.STORM}"


def check_three_samples_latch_and_persist():
    reset()
    for i in range(D.STORM_N):
        D.storm_tick(HI, (P0[0] + STEP * (i + 1), P0[1]))
    assert D.STORM.get("t0"), f"did not latch after {D.STORM_N} samples"
    on_disk = json.loads(TMP.read_text())
    assert on_disk.get("t0") == D.STORM["t0"], "latch not persisted (a restart would forget)"
    assert on_disk["p0"] == [P0[0] + STEP * D.STORM_N, P0[1]], \
        "baseline should be the pages at the trip sample (traffic before the trip is not billed)"


def check_holds_after_the_storm_ends():
    """The point of the feature: quiet samples must not clear it."""
    for _ in range(50):
        D.storm_tick(0.0, (P0[0] + STEP * D.STORM_N + 99, P0[1]))
    assert D.STORM.get("t0"), "latch was cleared automatically"
    assert json.loads(TMP.read_text()).get("t0"), "latch lost from disk"


def check_moved_counts_swap_since_trip():
    """`moved` = pages since the trip, (in+out) * 4096 / 2**20; the peak follows the rate.
    Needs STORM_N samples again — the anti-blink guard applies to a continuing storm too."""
    base, t0 = D.STORM["p0"], D.STORM["t0"]
    for _ in range(D.STORM_N):
        D.storm_tick(HI * 2, (base[0] + 1024, base[1] + 1024))   # 2048 pages = 8 MiB
    assert abs(D.STORM["moved"] - 8.0) < 0.01, f"moved={D.STORM['moved']} MiB, expected 8.0"
    assert D.STORM["peak"] >= HI * 2, "peak did not follow the rate"
    assert D.STORM["t0"] == t0, "a later burst re-tripped the latch and lost the original start"


def check_manual_reset_clears_everything():
    D.STORM.clear()
    D.storm_save()
    assert D.STORM == {}
    assert json.loads(TMP.read_text()) == {}, "reset left evidence on disk"
    print("storm latch: 7/7 (no-latch silent, N-1 silent, blinking silent, latch+persist, "
          "holds when quiet, moved accounting, manual reset)")


if __name__ == "__main__":
    for fn in [check_no_latch_no_badge, check_two_samples_do_not_latch,
               check_alternating_never_latches, check_three_samples_latch_and_persist,
               check_holds_after_the_storm_ends, check_moved_counts_swap_since_trip,
               check_manual_reset_clears_everything]:
        fn()
    print("OK")
