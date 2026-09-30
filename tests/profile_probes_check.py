"""Runnable check for scripts/profile_probes.py.

    uv run --no-project python tests/profile_probes_check.py

Every probe runs against a stdlib http.server stub on 127.0.0.1: a probe is only useful if it
can tell "the service is fine" from "the service said something empty", and that distinction
is testable without a model. The live services are checked separately, by hand, in Task 8.
"""
import base64
import http.server
import importlib.machinery
import importlib.util
import io
import json
import pathlib
import socket
import tempfile
import sys
import threading
import time
import wave

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load():
    loader = importlib.machinery.SourceFileLoader("profile_probes",
                                                  str(REPO / "scripts" / "profile_probes.py"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("profile_probes", loader))
    sys.modules["profile_probes"] = mod
    loader.exec_module(mod)
    return mod


pp = _load()


class _Stub(http.server.BaseHTTPRequestHandler):
    def _handle(self, read_body):
        body = b""
        if read_body:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        handler = self.server.routes.get(self.path.split("?")[0])
        if handler is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        code, payload = handler(body)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self._handle(True)

    def do_GET(self):
        self._handle(False)

    def log_message(self, *a):
        pass


def stub(routes):
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
    srv.routes = routes
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _wf():
    """A workflow the probe can read; the stub accepts anything, so its contents do not matter."""
    f = pathlib.Path(tempfile.mkstemp(suffix=".json")[1])
    f.write_text('{"1": {"class_type": "EmptyLatentImage"}}')
    return str(f)


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wav(seconds=0.2, level=8000):
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    n = int(8000 * seconds)
    w.writeframes(b"".join((level if i % 2 else -level).to_bytes(2, "little", signed=True)
                           for i in range(n)))
    w.close()
    return buf.getvalue()


def check_text_rejects_an_empty_completion():
    srv = stub({"/v1/chat/completions": lambda b: (200, {"choices": [{"message": {"content": "   "}}]})})
    try:
        ok, detail = pp.probe_text(srv.server_address[1], 5, tools=False)
        assert ok is False and "empty" in detail, detail
    finally:
        srv.shutdown()


def check_text_needs_a_tool_call_that_is_valid_json():
    def mk(args, content="hi"):
        msg = {"content": content}
        if args is not None:
            msg["tool_calls"] = [{"function": {"name": "run_shell", "arguments": args}}]
        return (200, {"choices": [{"message": msg}]})

    srv = stub({"/v1/chat/completions": lambda b: mk("{not json")})
    try:
        assert pp.probe_text(srv.server_address[1], 5, tools=True)[0] is False
    finally:
        srv.shutdown()

    srv = stub({"/v1/chat/completions": lambda b: mk('{"command":"df -h /"}')})
    try:
        ok, detail = pp.probe_text(srv.server_address[1], 5, tools=True)
        assert ok is True and "run_shell" in detail, detail
    finally:
        srv.shutdown()

    # a model that chats but never calls the tool has failed the thing the arm exists for
    srv = stub({"/v1/chat/completions": lambda b: mk(None)})
    try:
        ok, detail = pp.probe_text(srv.server_address[1], 5, tools=True)
        assert ok is False and "tool" in detail, detail
    finally:
        srv.shutdown()


def check_image_needs_real_png_bytes():
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 2000
    srv = stub({"/v1/images/generations":
                lambda b: (200, {"data": [{"b64_json": base64.b64encode(png).decode()}]})})
    try:
        assert pp.probe_image(srv.server_address[1], 5)[0] is True
    finally:
        srv.shutdown()

    srv = stub({"/v1/images/generations": lambda b: (200, {"data": [{"b64_json": ""}]})})
    try:
        ok, detail = pp.probe_image(srv.server_address[1], 5)
        assert ok is False and "image" in detail.lower(), detail
    finally:
        srv.shutdown()


def check_music_needs_sound_not_silence():
    def run(body):
        return (200, {"audio": base64.b64encode(_wav()).decode(), "timing": {"rtf": 0.6}})

    routes = {"/health": lambda b: (200, {"status": "ok", "backend": "vulkan"}),
              "/v1/tasks/run": run}
    srv = stub(routes)
    try:
        assert pp.probe_music(srv.server_address[1], 30)[0] is True
    finally:
        srv.shutdown()

    routes["/v1/tasks/run"] = lambda b: (200, {"audio": base64.b64encode(_wav(level=0)).decode()})
    srv = stub(routes)
    try:
        ok, detail = pp.probe_music(srv.server_address[1], 30)
        assert ok is False and "silence" in detail.lower(), detail
    finally:
        srv.shutdown()


def check_video_needs_the_job_to_finish_not_just_be_queued():
    ok_hist = {"pid1": {"status": {"status_str": "success", "completed": True}}}
    srv = stub({"/prompt": lambda b: (200, {"prompt_id": "pid1"}),
                "/history/pid1": lambda b: (200, ok_hist)})
    try:
        assert pp.probe_video(srv.server_address[1], 30, poll=0.01,
                              workflow=_wf())[0] is True
    finally:
        srv.shutdown()

    srv = stub({"/prompt": lambda b: (200, {"prompt_id": "pid1"}),
                "/history/pid1": lambda b: (200, {"pid1": {"status": {"status_str": "error",
                                                                      "completed": False}}})})
    try:
        ok, detail = pp.probe_video(srv.server_address[1], 2, poll=0.01,
                                    workflow=_wf())
        assert ok is False and "error" in detail, detail
    finally:
        srv.shutdown()


def check_stt_transcript_comes_out_of_the_sse_stream():
    good = 'event: complete\ndata: ["The quick brown fox.", "model=large-v3-turbo"]\n\n'
    assert pp.parse_sse_transcript(good) == "The quick brown fox."
    assert pp.parse_sse_transcript("event: complete\ndata: [\"\", \"meta\"]") == ""
    assert pp.parse_sse_transcript("event: error\ndata: {\"err\":1}") == ""


def check_no_listener_is_not_the_same_as_a_timeout():
    r = pp.probe("stt", "stt", {"PORT_STT": str(_closed_port())})
    assert r["ok"] is False and r["detail"] == "no listener", r

    def slow(body):
        time.sleep(1.0)
        return (200, {"data": []})

    srv = stub({"/gradio_api/upload": slow})
    try:
        r = pp.probe("stt", "stt", {"PORT_STT": str(srv.server_address[1]),
                                    "PROFILE_PROBE_TIMEOUT_S": "0.2",
                                    "PROFILE_BUDGET_S_STT": "30"})
        assert r["ok"] is False and "timeout" in r["detail"], r
    finally:
        srv.shutdown()


def check_over_budget_is_a_failure_even_when_the_answer_arrives():
    def slow(body):
        time.sleep(0.3)
        return (200, {"choices": [{"message": {"content": "late but fine"}}]})

    srv = stub({"/v1/chat/completions": slow})
    try:
        r = pp.probe("text", "text", {"PORT_TEXT": str(srv.server_address[1]),
                                      "PROFILE_PROBE_TIMEOUT_S": "5",
                                      "PROFILE_TEXT_TOOLS": "0",
                                      "PROFILE_BUDGET_S_TEXT": "0.05"})
        assert r["ok"] is False and r["detail"] == "over budget", r
    finally:
        srv.shutdown()


def check_unknown_kind_and_dispatch_table():
    assert set(pp.PROBES) == {"text", "image", "video", "music", "stt"}
    r = pp.probe("x", "hologram", {})
    assert r["ok"] is False and "unknown probe kind" in r["detail"], r


def main():
    for fn in [check_text_rejects_an_empty_completion,
               check_text_needs_a_tool_call_that_is_valid_json,
               check_image_needs_real_png_bytes, check_music_needs_sound_not_silence,
               check_video_needs_the_job_to_finish_not_just_be_queued,
               check_stt_transcript_comes_out_of_the_sse_stream,
               check_no_listener_is_not_the_same_as_a_timeout,
               check_over_budget_is_a_failure_even_when_the_answer_arrives,
               check_unknown_kind_and_dispatch_table]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("SELF-TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
