"""test_run.py — resume/protocol-stamping check for run.py (no network).

Stubs run.one and drives main(): (1) rows carry battery version + temp,
(2) same-protocol rows resume-skip, (3) a verdict scored under another
battery version is re-scored, not inherited, (4) a temperature change
re-scores everything. Run: python3 test_run.py
"""
import importlib.util, json, os, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("run", os.path.join(here, "run.py"))
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)


def drive(argv):
    calls = []

    def fake_one(idx, items, model, host, temp, max_tokens, tries=2, http_timeout=900):
        calls.append(idx)
        return {"ok": True, "wall": 0.1}

    run.one = fake_one
    old = sys.argv; sys.argv = ["run.py"] + argv
    try:
        run.main()
    finally:
        sys.argv = old
    return calls


with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, "r.jsonl")

    first = drive(["--battery", "iten12", "--model", "m1", "--out", out])
    assert len(first) == 12 and sorted(first) == list(range(12)), "first run scores all 12"
    rows = [json.loads(l) for l in open(out)]
    assert all(r.get("bat", "").startswith("iten12/") and "temp" in r for r in rows), \
        f"rows not protocol-stamped: {rows[0]}"

    assert drive(["--battery", "iten12", "--model", "m1", "--out", out]) == [], \
        "same protocol must resume-skip"

    # a verdict scored under an older grader must be re-scored, not inherited
    keep = [r for r in rows if r["item"] != 0]
    keep.append({"model": "m1", "item": 0, "bat": "iten12/v0-old", "temp": 0.0,
                 "ok": True, "wall": 9.9})
    with open(out, "w") as f:
        for r in keep:
            f.write(json.dumps(r) + "\n")
    assert drive(["--battery", "iten12", "--model", "m1", "--out", out]) == [0], \
        "stale-battery row must be re-scored"

    assert len(drive(["--battery", "iten12", "--model", "m1", "--temp", "1.0",
                      "--out", out])) == 12, \
        "temperature change must re-score all items"

print("test_run: SELF-CHECK OK")
