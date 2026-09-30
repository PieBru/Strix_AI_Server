#!/usr/bin/env python3
"""profile_probes — positive evidence that a model family actually works, not that a port opens.

    profile_probes.py music stt          # run these two against the live box

A probe returns `{"ok": bool, "s": float, "detail": str}`. `ok` requires the artifact: a
completion with non-empty content, an image with real PNG bytes, a WAV with non-zero RMS, a
ComfyUI job that reaches completion, a transcript that is not the empty string. A 200 with an
empty body is a FAIL — that is the whole reason this file exists.

`detail` is written for the operator who reads it at 3am: "no listener" and "timeout" are
different problems and must not print the same word.

Measured facts these probes encode (260929/260930, this box):
  - text: the fork's PEG parser throws HTTP 500 on ~3/12 tool calls at temp 1.0, so ONE sample
    reports green on a 58 % arm. A single probe is a smoke test; the gate runner (Task 7) is
    what repeats it. See sos/check.py.
  - music: real RMS is 962-7800; digital silence is 0. The floor is 200.
  - stt: the whisper unit IS the engine (faster-whisper in-process, no separate port), so the
    probe drives gradio's queue API: upload -> call -> SSE. Measured 4.9 s wall for 2.9 s of
    audio with large-v3-turbo.
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import random
import socket
import time
import urllib.error
import urllib.request
import uuid
import wave

REPO = pathlib.Path(__file__).resolve().parent.parent

# Per-family latency budget: a model that answers, but only after 400 s under load, has passed
# nothing, because that box is unusable while it is loaded. Over budget is ok=False.
PROBE_BUDGET_S = {"text": 60, "image": 180, "video": 600, "music": 300, "stt": 120}
DEFAULT_PORTS = {"text": 8080, "image": 8081, "video": 8188, "music": 8001, "stt": 7863}

TOOL = {"type": "function", "function": {
    "name": "run_shell",
    "description": "Run a read-only shell command on the server and return its stdout.",
    "parameters": {"type": "object",
                   "properties": {"command": {"type": "string", "description": "the command to run"}},
                   "required": ["command"]}}}


def _post(url: str, obj, timeout: float, headers: dict | None = None):
    data = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
    hdr = {"Content-Type": "application/json"}
    hdr.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data, hdr), timeout=timeout) as r:
        return r.read()


def _get(url: str, timeout: float):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _fail(why: str) -> tuple[bool, str]:
    return False, why


def probe_text(port: int, timeout: float = 60, tools: bool = True,
               model: str = "default") -> tuple[bool, str]:
    body = {"model": model, "max_tokens": 256,
            "messages": [{"role": "user", "content": "Say the token GLARB7 and nothing else."}]}
    if tools:
        body["tools"] = [TOOL]
        body["messages"][0]["content"] = ("What is the disk usage of / ? "
                                          "Use a tool, do not answer from memory.")
    raw = json.loads(_post(f"http://127.0.0.1:{port}/v1/chat/completions", body, timeout))
    msg = (raw.get("choices") or [{}])[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    calls = msg.get("tool_calls") or []
    # A correct tool call has EMPTY content — checking content first fails the arm for doing
    # exactly what was asked (observed live 260930 against gemma-collm: "empty completion").
    if tools:
        if not calls:
            return _fail(f"chatted instead of calling the tool: {content[:60]!r}")
        args = (calls[0].get("function") or {}).get("arguments") or ""
        try:
            json.loads(args)
        except ValueError:
            return _fail(f"tool call arguments are not JSON: {args[:80]!r}")
        return True, f"tool call {calls[0]['function'].get('name')}({args[:40]})"
    if not content:
        return _fail("empty completion")
    return True, f"{len(content)} chars"


def probe_image(port: int, timeout: float = 180, model: str = "Qwen-Image-2.1") -> tuple[bool, str]:
    png = base64.b64decode(json.loads(_post(
        f"http://127.0.0.1:{port}/v1/images/generations",
        {"model": model, "prompt": "a red cube on a white table", "size": "512x512",
         "seed": 20260930, "steps": 4}, timeout))["data"][0]["b64_json"])
    if len(png) < 1000 or not png.startswith(b"\x89PNG"):
        return _fail(f"image is not a real png ({len(png)} bytes)")
    return True, f"{len(png)} byte png"


def probe_music(port: int, timeout: float = 300, model: str = "acestep") -> tuple[bool, str]:
    if json.loads(_get(f"http://127.0.0.1:{port}/health", 10)).get("status") != "ok":
        return _fail("engine /health not ok")
    r = json.loads(_post(f"http://127.0.0.1:{port}/v1/tasks/run", {
        "model": model, "request": {
            "text": "check tone: soft synth arpeggio", "lyrics": "", "duration_seconds": 5,
            "num_inference_steps": 4, "seed": 42, "language": "en", "route": "text2music",
            "options": {"thinking": False}}}, timeout))
    wav = base64.b64decode(r["audio"])
    w = wave.open(io.BytesIO(wav))
    n = w.getnframes()
    s = w.readframes(n)
    rms = (sum(int.from_bytes(s[i:i + 2], "little", signed=True) ** 2
               for i in range(0, len(s), 2)) / max(1, len(s) // 2)) ** 0.5 if n else 0.0
    if n == 0 or rms <= 200:
        return _fail(f"silence (rms={rms:.0f}, {n} frames)")
    return True, f"{n / w.getframerate():.1f} s audio rms={rms:.0f}"


def _deseed(wf: dict) -> tuple[dict, int]:
    """ComfyUI caches by prompt hash. Submit the same workflow twice and the second "render"
    is a cache hit that returns in seconds and proves nothing about the GPU or the weights —
    observed live 260930: a 138 s H3 render came back in 2.01 s. Every seed field gets a fresh
    value, so the prompt is never the one that is already in the cache."""
    seed = random.randint(1, 2**53)
    n = 0
    for node in wf.values():
        inp = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inp, dict):
            continue
        for k in list(inp):
            if k in ("seed", "noise_seed", "random_seed"):
                inp[k] = seed
                n += 1
    return wf, n


def probe_video(port: int, timeout: float = 600, workflow: str | None = None,
                poll: float = 2.0) -> tuple[bool, str]:
    """Submit the operator's real ComfyUI workflow and wait for the job to complete. Queued is
    not done: a job that enters the queue and dies is exactly what a naive probe reports green.
    """
    path = pathlib.Path(workflow or (pathlib.Path.home() / "Piero/Work/H3/h3_turbo_workflow.json"))
    if not path.is_file():
        return _fail(f"no workflow at {path}")
    wf, seeds = _deseed(json.loads(path.read_text()))
    if not seeds:
        # a workflow with no seed is cacheable no matter what we do; say so instead of
        # reporting a cache hit as a render
        return _fail(f"{path.name} has no seed input — the probe cannot tell a render from a "
                     f"cache hit")
    cid = uuid.uuid4().hex
    pid = json.loads(_post(f"http://127.0.0.1:{port}/prompt",
                           {"prompt": wf, "client_id": cid},
                           min(timeout, 30)))["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        h = json.loads(_get(f"http://127.0.0.1:{port}/history/{pid}", 30)).get(pid)
        if not h:
            continue
        status = h.get("status") or {}
        if status.get("status_str") == "error" or not status.get("completed"):
            return _fail(f"job {status.get('status_str')}")
        return True, f"job {pid[:8]} completed ({seeds} seed(s) randomised)"
    return _fail(f"job {pid[:8]} still queued after {timeout:.0f} s")


def parse_sse_transcript(raw: str) -> str:
    """gradio's queue answers with SSE; the transcript is the first element of the last data
    frame. Anything else (an error frame, an empty string) is not a transcript."""
    out = ""
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                val = json.loads(line[6:])
            except ValueError:
                continue
            if isinstance(val, list) and val and isinstance(val[0], str):
                out = val[0]
    return out.strip()


def probe_stt(port: int, timeout: float = 120, wav_path: str | None = None,
              model: str = "large-v3-turbo", language: str = "auto") -> tuple[bool, str]:
    path = pathlib.Path(wav_path or (REPO / "stt" / "testaudio" / "stt-en.wav"))
    if not path.is_file():
        return _fail(f"no test audio at {path}")
    boundary = uuid.uuid4().hex
    part = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
    body = part + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    uploaded = json.loads(_post(
        f"http://127.0.0.1:{port}/gradio_api/upload", body, min(timeout, 60),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    eid = json.loads(_post(f"http://127.0.0.1:{port}/gradio_api/call/transcribe", {"data": [
        {"path": uploaded[0], "url": None, "size": None, "orig_name": path.name,
         "meta": {"_type": "gradio.FileData"}}, model, language]}, 30))["event_id"]
    raw = _get(f"http://127.0.0.1:{port}/gradio_api/call/transcribe/{eid}", timeout).decode()
    text = parse_sse_transcript(raw)
    if not text:
        return _fail("no transcript")
    return True, f"{len(text)} chars: {text[:50]!r}"


PROBES = {"text": probe_text, "image": probe_image, "video": probe_video,
          "music": probe_music, "stt": probe_stt}


def probe(name: str, kind: str, cfg: dict[str, str]) -> dict:
    """Run one probe. Budgets and ports come from cfg (doctor.config, Task 9) so the gate can
    be retuned without a code change; PROFILE_PROBE_TIMEOUT_S is deliberately separate from the
    budget — the timeout is how long we wait, the budget is what we accept."""
    fn = PROBES.get(kind)
    if fn is None:
        return {"ok": False, "s": 0.0, "detail": f"unknown probe kind {kind!r}"}
    budget = float(cfg.get(f"PROFILE_BUDGET_S_{kind.upper()}", PROBE_BUDGET_S[kind]))
    timeout = float(cfg.get("PROFILE_PROBE_TIMEOUT_S", budget))
    port = int(cfg.get(f"PORT_{kind.upper()}", DEFAULT_PORTS[kind]))
    kwargs = {}
    if kind == "text":
        kwargs = {"tools": cfg.get("PROFILE_TEXT_TOOLS", "1") != "0",
                  "model": cfg.get("PROFILE_TEXT_MODEL", "default")}
    elif kind == "image":
        kwargs = {"model": cfg.get("PROFILE_IMAGE_MODEL", "Qwen-Image-2.1")}
    elif kind == "video":
        kwargs = {"workflow": cfg.get("PROFILE_VIDEO_WORKFLOW") or None,
                  "poll": float(cfg.get("PROFILE_VIDEO_POLL_S", 2.0))}
    elif kind == "music":
        kwargs = {"model": cfg.get("PROFILE_MUSIC_MODEL", "acestep")}
    elif kind == "stt":
        kwargs = {"wav_path": cfg.get("PROFILE_STT_WAV") or None,
                  "model": cfg.get("PROFILE_STT_MODEL", "large-v3-turbo")}
    t0 = time.monotonic()
    try:
        ok, detail = fn(port, timeout, **kwargs)
    except ConnectionRefusedError:
        ok, detail = False, "no listener"
    except urllib.error.URLError as e:
        ok = False
        detail = ("no listener" if isinstance(e.reason, ConnectionRefusedError)
                  else "timeout" if isinstance(e.reason, socket.timeout) else f"transport: {e.reason}")
    except (socket.timeout, TimeoutError):
        ok, detail = False, "timeout"
    s = time.monotonic() - t0
    if ok and s > budget:
        return {"ok": False, "s": round(s, 2), "detail": "over budget"}
    return {"ok": bool(ok), "s": round(s, 2), "detail": detail}


if __name__ == "__main__":
    import sys
    cfg = dict(line.strip().split("=", 1) for line in
               (REPO / "configs" / "gate.env").read_text().splitlines()
               if "=" in line and not line.strip().startswith("#")
               ) if (REPO / "configs" / "gate.env").exists() else {}
    rc = 0
    for kind in (sys.argv[1:] or ["text"]):
        r = probe(kind, kind, cfg)
        print(f"{kind:6s} {'ok  ' if r['ok'] else 'FAIL'} {r['s']:6.2f}s  {r['detail']}")
        rc = rc or (0 if r["ok"] else 1)
    sys.exit(rc)
