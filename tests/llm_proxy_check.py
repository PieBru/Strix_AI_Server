"""Runnable check for the /llm pass-through in doctor/Doctor.py.

    uv run --no-project python tests/llm_proxy_check.py

The proxy exists because llama.cpp sends no Access-Control-Allow-Origin on real
responses, so Anvil (served from :8667) can only reach the arm through Doctor.
Nothing here touches :8080 or a systemd unit: LLM_UP is pointed at a throwaway
server on a random port, and one case points it at a closed port on purpose.
"""
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import time
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


D = _load("doctor_llm_under_test", REPO / "doctor" / "Doctor.py")


class Upstream(BaseHTTPRequestHandler):
    """Stands in for llama-server: echoes what it got, and can stream or fail."""

    def _reply(self, code, payload, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/boom":
            self._reply(500, b'{"error":"model not loaded"}')
            return
        self._reply(200, json.dumps({"path": self.path, "method": self.command}).encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/v1/chat/completions":
            self._reply(200, json.dumps({"path": self.path, "method": self.command,
                                         "ctype": self.headers.get("Content-Type"),
                                         "echo": raw.decode()}).encode())
        elif self.path == "/slow":  # two chunks, flushed: a buffered proxy reads as one
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: one\n\n")
            self.wfile.flush()
            time.sleep(0.5)  # if Doctor buffers instead of flushing, the reader waits for this
            self.wfile.write(b"data: two\n\n")
            self.wfile.end_headers if False else self.wfile.flush()
        else:
            self._reply(404, b'{"error":"no route"}')

    def log_message(self, *a):  # keep the check quiet
        pass


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def doctor_on(upstream):
    """Doctor's real handler class, on a random port, pointed at `upstream`."""
    D.LLM_UP = upstream
    h = type("Quiet", (D.H,), {"log_message": lambda *a: None})
    return serve(h)


def post(url, body=None, method=None):
    req = urllib.request.Request(url, data=(body.encode() if body else None), method=method or "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("Content-Type"), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read().decode()


def check_the_llm_prefix_is_stripped_and_the_body_carries():
    up, up_url = serve(Upstream)
    srv, url = doctor_on(up_url)
    try:
        code, ctype, body = post(url + "/llm/v1/chat/completions", '{"model":"default"}')
        got = json.loads(body)
        assert code == 200 and ctype.startswith("application/json"), (code, ctype, body)
        assert got["path"] == "/v1/chat/completions", f"/llm not stripped: {got}"
        assert got["echo"] == '{"model":"default"}', got
        assert got["ctype"] == "application/json", got
    finally:
        srv.shutdown(); up.shutdown()


def check_get_and_a_non_200_pass_straight_through():
    up, up_url = serve(Upstream)
    srv, url = doctor_on(up_url)
    try:
        code, _, body = post(url + "/llm/v1/models", method="GET")
        assert code == 200 and json.loads(body)["path"] == "/v1/models", (code, body)
        code, _, body = post(url + "/llm/boom", method="GET")
        # an upstream 500 is the arm's answer, not our failure: it must not become a 502
        assert code == 500 and "model not loaded" in body, (code, body)
    finally:
        srv.shutdown(); up.shutdown()


def check_a_dead_arm_is_a_502_and_not_a_traceback():
    srv, url = doctor_on("http://127.0.0.1:1")  # nothing listens on port 1
    try:
        code, ctype, body = post(url + "/llm/v1/chat/completions", "{}")
        assert code == 502, (code, body)
        assert body.startswith("llm proxy:"), body
    finally:
        srv.shutdown()


def check_a_stream_arrives_as_it_is_written():
    up, up_url = serve(Upstream)
    srv, url = doctor_on(up_url)
    try:
        req = urllib.request.Request(url + "/llm/slow", method="POST",
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=10) as r:
            first = r.readline().decode() + r.readline().decode()
            took = time.time() - t0
            assert "one" in first, first
            assert took < 0.4, f"first chunk waited {took:.2f}s — the proxy is buffering the stream"
            rest = r.read().decode()
        assert "two" in rest, rest
    finally:
        srv.shutdown(); up.shutdown()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("check_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} checks passed")
