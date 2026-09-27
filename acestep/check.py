"""Runnable check for the ACE-Step lab: engine health + one real 5 s song.

    uv run --no-project python acestep/check.py        # ~25 s after the first load
Exit 0 = engine healthy and the returned WAV is 5±1 s of non-silent stereo audio.
The browser-level gate (gradio :7862) is separate: see ACESTEP_PROPOSAL_260927.md G4.
"""
import base64, io, json, math, sys, urllib.request, wave

API = "http://127.0.0.1:8001"


def rms(wav: bytes) -> int:
    w = wave.open(io.BytesIO(wav))
    n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
    s = w.readframes(n)
    if not n:
        return 0, 0
    vals = [int.from_bytes(s[i:i + 2], "little", signed=True) for i in range(0, len(s), 2)]
    return math.sqrt(sum(v * v for v in vals) / len(vals)), n / sr


def main() -> int:
    h = json.load(urllib.request.urlopen(API + "/health", timeout=10))
    assert h["status"] == "ok", h
    req = {"model": "acestep", "request": {
        "text": "check tone: soft synth arpeggio", "lyrics": "",
        "duration_seconds": 5, "num_inference_steps": 4, "seed": 42,
        "language": "en", "route": "text2music", "options": {"thinking": False}}}
    r = json.load(urllib.request.urlopen(
        urllib.request.Request(API + "/v1/tasks/run", json.dumps(req).encode(),
                               {"Content-Type": "application/json"}), timeout=900))
    wav = base64.b64decode(r["audio"])
    level, dur = rms(wav)
    print(f"backend={h['backend']} dur={dur:.2f}s rms={level:.0f} "
          f"rtf={r.get('timing', {}).get('rtf', 0):.2f} bytes={len(wav)}")
    # rms floor 200: measured here 962 (5 s arpeggio) to 7800 (20 s song); digital silence is 0.
    ok = 4.0 <= dur <= 6.0 and level > 200 and len(wav) > 500_000
    print("CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
