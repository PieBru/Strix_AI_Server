#!/usr/bin/env python3
"""Anvil launcher: serve this repo on 127.0.0.1:8899, expose the env-key bridge,
and (spec 021) the token-gated filesystem bridge.

Why this exists: a browser page cannot read environment variables and the
File System Access API is Chromium-only. Serving Anvil with this script
(instead of `python -m http.server`) additionally gives:

  1. GET /anvil/env  — EXACTLY the whitelisted env keys below, PLUS the fs
     bridge descriptor {fs, root, token}. Anvil offers each found key as a
     one-click apply toast (the apply is always your click, never automatic)
     and, when fs:true, routes the local file tools through this launcher.
     Serving with anything else = both bridges are simply absent and Anvil
     stays silent about them (FSA-only mode, exactly the old behavior).

  2. /anvil/fs (spec 021) — read/blob/exists (GET) and write/edit/delete/
     glob/grep (POST), sandboxed to the served root via realpath.

  3. GET /anvil/proxy?url=<encoded> (spec 022) — same-origin CORS GET relay
     for the tools (SearXNG zero-setup). GET-only, http(s) targets only,
     loopback/link-local refused (private LAN allowed — that is where
     SearXNG lives), redirects NEVER followed (the error names the hop),
     5 MB body cap, 20 s timeout, every hop logged. The gate-only env var
     ANVIL_RELAY_ALLOW_LOOPBACK=1 lifts the loopback refusal for tests
     (banner-printed when set; never in a default start).

Security model (deliberate, spec 021 FR-001..010):
  - per-start random token, delivered ONLY via the same-origin /anvil/env
    response (no CORS headers anywhere — a foreign page can never read it);
  - every OTHER /anvil/* route requires the token in X-Anvil-Token — a
    foreign page's custom-header request needs a CORS preflight and OPTIONS
    stays 501, so drive-bys die before the route;
  - Host header must be 127.0.0.1:<port> / localhost:<port> (DNS rebinding);
  - every fs path is realpath-confined under the served root;
  - bind stays 127.0.0.1-only; there is no exec route and never will be.

  ./anvil-serve.py              # http://127.0.0.1:8899/Anvil.html
  PORT=9000 ./anvil-serve.py    # custom port
  ./anvil-serve.py --selftest   # security invariants on a temp root, no browser
"""

import base64
import contextlib
import http.client
import http.server
import json
import mimetypes
import os
import re
import secrets
import socketserver
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

try:
    PORT = int(os.environ.get("PORT", "8899"))
except ValueError:
    raise SystemExit(
        f"PORT must be an integer, got {os.environ.get('PORT')!r}"
    ) from None

ROOT = os.path.realpath(os.getcwd())
TOKEN = secrets.token_hex(32)  # per start; lives only in memory + /anvil/env
FS_CAP_READ = 2 * 1024 * 1024  # parity with fsReadUnder (2 MB)
FS_CAP_WALK = 5000
FS_CAP_RESULTS = 500
FS_CAP_GREP = 200
FS_CAP_GREP_FILE = 1024 * 1024
FS_OPS_GET = ("read", "blob", "exists")
FS_OPS_POST = ("write", "edit", "delete", "glob", "grep")
RELAY_CAP = 5 * 1024 * 1024  # spec 022 FR-004: named constant, not a setting
RELAY_TIMEOUT = 20
RELAY_ALLOW_LOOPBACK = os.environ.get("ANVIL_RELAY_ALLOW_LOOPBACK") == "1"

# Must match ENV_KEYS in Anvil.html (the only keys ever exposed to the page)
WHITELIST = [
    "TAVILY_API_KEY",
    "GEMINI_API_KEY",
    "SEARXNG_URL",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
]


class SandboxError(Exception):
    """Path escapes the served root (or is malformed) — refused, naming the rule."""


class OpError(Exception):
    """Bad op/args — answered 400 with a self-describing message."""


def glob_to_re(glob):
    """Mirror of Anvil's globToRegExp: no '/' -> basename match at any depth;
    with '/' -> anchored relative-path match ('**/' prefix keeps its meaning)."""

    def seg(s):
        out = re.sub(r"([.+^${}()|\[\]\\])", r"\\\1", s)
        return (
            out.replace("**", "\x00")
            .replace("*", "[^/]*")
            .replace("?", "[^/]")
            .replace("\x00", ".*")
        )

    g = str(glob).lstrip("/")
    body = "/".join(seg(x) for x in g.split("/"))
    src = body if g.startswith("**/") else "(?:[^/]+/)*" + body
    return re.compile("^" + src + "$")


def sandbox_path(rel):
    if not isinstance(rel, str) or not rel.strip():
        raise OpError('"path" must be a non-empty string.')
    segs = rel.strip().strip("/").split("/")
    if not segs or any(s in ("", ".", "..") for s in segs):
        raise SandboxError(
            f"path must be relative to the served root with no . / .. segments (got {rel!r})"
        )
    p = os.path.realpath(os.path.join(ROOT, rel))
    if p != ROOT and not p.startswith(ROOT + os.sep):
        raise SandboxError(f"path escapes the sandbox root via realpath: {rel!r}")
    return p


def validate_replacements(repls):
    if not isinstance(repls, list) or not repls:
        raise OpError(
            '"replacements" must be a non-empty array of {old_text,new_text}.'
        )
    for r in repls:
        if (
            not isinstance(r, dict)
            or not isinstance(r.get("old_text"), str)
            or not isinstance(r.get("new_text"), str)
        ):
            raise OpError('each replacement needs string "old_text" and "new_text".')
        if not r["old_text"]:
            raise OpError('"old_text" must be non-empty.')
    return repls


def fs_read(rel):
    p = sandbox_path(rel)
    if os.path.isdir(p):
        raise OpError(f"cannot read a directory: {rel}")
    if not os.path.isfile(p):
        raise OpError(f"File not found in workspace: {rel}")
    size = os.path.getsize(p)
    if size > FS_CAP_READ:
        raise OpError(
            f"File too large to read in one call: {rel} ({size} bytes > 2 MB)."
        )
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError as e:  # vanished/permission race between isfile and open
        raise OpError(f"cannot read {rel}: {e}") from e


def fs_walk(root, include, exclude, type_="file", max_depth=0, limit=FS_CAP_RESULTS):
    inc = glob_to_re(include) if include else None
    exc = glob_to_re(exclude) if exclude else None
    files, dirs = [], []
    visited = 0
    truncated = False
    want_files = type_ != "dir"
    want_dirs = type_ == "dir" or type_ == "all"

    def rec(base, rel, depth):
        nonlocal visited, truncated
        if max_depth and depth > max_depth:
            return
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return
        for name in names:
            visited += 1
            if visited > FS_CAP_WALK:
                truncated = True
                return
            r = f"{rel}/{name}" if rel else name
            full = os.path.join(base, name)
            is_dir = os.path.isdir(full)
            if (
                is_dir
                and want_dirs
                and (not inc or inc.match(r))
                and not (exc and exc.match(r))
            ):
                dirs.append(r)
            elif (
                not is_dir
                and want_files
                and (not inc or inc.match(r))
                and not (exc and exc.match(r))
            ):
                files.append(r)
                if len(files) >= limit:
                    truncated = True
                    return
            if is_dir:
                rec(full, r, depth + 1)

    rec(root, "", 1)
    return {"files": files, "dirs": dirs, "truncated": truncated}


TEXT_EXT = {
    "txt",
    "md",
    "markdown",
    "json",
    "jsonc",
    "js",
    "mjs",
    "cjs",
    "ts",
    "tsx",
    "jsx",
    "py",
    "rs",
    "go",
    "c",
    "h",
    "cpp",
    "hpp",
    "cc",
    "hh",
    "java",
    "kt",
    "rb",
    "php",
    "sh",
    "bash",
    "zsh",
    "css",
    "scss",
    "html",
    "htm",
    "xml",
    "yml",
    "yaml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "csv",
    "tsv",
    "sql",
    "env",
    "log",
    "patch",
    "diff",
    "lua",
    "vim",
    "r",
    "m",
    "pl",
    "dart",
    "swift",
    "scala",
    "clj",
    "ex",
    "exs",
    "erl",
    "hs",
    "ml",
    "fs",
    "asm",
    "bat",
    "ps1",
    "tf",
    "tfvars",
    "hcl",
    "proto",
    "graphql",
    "gql",
    "makefile",
    "license",
    "readme",
}


def is_text_name(rel):
    base = rel.rsplit("/", 1)[-1]
    return (
        "." not in base
        and base.lower() in TEXT_EXT
        or base.rsplit(".", 1)[-1].lower() in TEXT_EXT
    )


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- plumbing -------------------------------------------------------
    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Anvil-Fs", "v1")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        return host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _gated(self):
        """True when the request passed host + token checks; sends the refusal otherwise."""
        if not self._host_ok():
            self._send(403, json.dumps({"error": "refused: unexpected Host header"}))
            return False
        if self.headers.get("X-Anvil-Token") != TOKEN:
            self._send(403, json.dumps({"error": "missing or wrong X-Anvil-Token"}))
            return False
        return True

    # ---- routes ---------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/anvil/"):
            if path == "/anvil/env":
                env: dict = {k: os.environ[k] for k in WHITELIST if os.environ.get(k)}
                # FR-001: the fs descriptor rides the same same-origin payload.
                # No CORS headers on ANY launcher response: a foreign page can
                # never read this body, so the token reaches only our own page.
                env.update(
                    {
                        "fs": True,
                        "relay": True,
                        "root": ROOT,  # full $PWD — basename would collide same-named dirs in the per-root project memory
                        "token": TOKEN,
                    }
                )
                self._send(200, json.dumps(env))
                return
            if path == "/anvil/fs":
                if not self._gated():
                    return
                self._fs_get()
                return
            if path == "/anvil/proxy":
                if not self._gated():
                    return
                self._relay_get()
                return
            self._send(404, json.dumps({"error": "unknown /anvil/ route"}))
            return
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/anvil/"):
            if path == "/anvil/fs":
                if not self._gated():
                    return
                self._fs_post()
                return
            if path == "/anvil/proxy":
                self._send(405, json.dumps({"error": "/anvil/proxy is GET-only"}))
                return
            self._send(404, json.dumps({"error": "unknown /anvil/ route"}))
            return
        self._send(405, json.dumps({"error": "POST only answered on /anvil/fs"}))

    def _fs_get(self):
        from urllib.parse import parse_qs, unquote

        q = parse_qs(
            self.path.split("?", 1)[1] if "?" in self.path else "",
            keep_blank_values=True,
        )
        op = unquote(q.get("op", [""])[0])
        rel = unquote(q.get("path", [""])[0])
        try:
            if op == "read":
                data = fs_read(rel)
                self._send(
                    200,
                    json.dumps(
                        {"text": data.decode("utf-8", "replace"), "size": len(data)}
                    ),
                )
            elif op == "blob":
                data = fs_read(rel)
                mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
                self._send(
                    200,
                    json.dumps(
                        {
                            "b64": base64.b64encode(data).decode(),
                            "size": len(data),
                            "mime": mime,
                        }
                    ),
                )
            elif op == "exists":
                p = sandbox_path(rel)
                self._send(200, json.dumps({"exists": os.path.exists(p)}))
            elif op in FS_OPS_POST:
                self._send(
                    405,
                    json.dumps(
                        {
                            "error": f"op {op!r} is a POST op — resend as POST /anvil/fs with a JSON body"
                        }
                    ),
                )
            else:
                raise OpError(
                    f"unknown op {op!r} — GET ops: {', '.join(FS_OPS_GET)}; POST ops: {', '.join(FS_OPS_POST)}"
                )
        except SandboxError as e:
            self._send(400, json.dumps({"error": str(e)}))
        except OpError as e:
            self._send(400, json.dumps({"error": str(e)}))

    def _fs_post(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) if n else b"{}")
            if not isinstance(body, dict):
                raise OpError("body must be a JSON object")
            op = body.get("op")
            rel = body.get("path")
            if op == "write":
                p = sandbox_path(rel)
                data = (
                    base64.b64decode(body["content_b64"])
                    if isinstance(body.get("content_b64"), str)
                    else str(body.get("content", "")).encode()
                )
                os.makedirs(os.path.dirname(p), exist_ok=True)  # mkdir -p
                with open(p, "wb") as f:
                    f.write(data)
                self._send(200, json.dumps({"ok": True, "size": len(data)}))
            elif op == "edit":
                p = sandbox_path(rel)
                if not os.path.isfile(p):
                    raise OpError(f"File not found in workspace: {rel}")
                with open(p, "rb") as f:
                    cur = f.read()
                text = cur.decode("utf-8", "replace")
                plan = []  # (start, end, new_text) — validate ALL against the ORIGINAL
                for r in validate_replacements(body.get("replacements")):
                    old, new = r["old_text"], r["new_text"]
                    n_hits = text.count(old)
                    if n_hits == 0:
                        raise OpError(
                            f'edit drift: "old_text" not found (file changed on disk?) — path {rel}'
                        )
                    if n_hits > 1:
                        raise OpError(
                            f'"old_text" occurs {n_hits} times in {rel} — must be unique'
                        )
                    i = text.index(old)
                    for s, e2, _ in plan:
                        if i < e2 and s < i + len(old):
                            raise OpError("overlapping replacements refused")
                    plan.append((i, i + len(old), new))
                out = []
                last = 0
                for s, e2, new in sorted(plan):
                    out.append(text[last:s])
                    out.append(new)
                    last = e2
                out.append(text[last:])
                merged = "".join(out)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(merged)
                self._send(200, json.dumps({"ok": True, "applied": len(plan)}))
            elif op == "delete":
                p = sandbox_path(rel)
                existed = os.path.lexists(p)
                if existed and os.path.isdir(p) and not os.path.islink(p):
                    raise OpError(f"refusing to rmtree a directory: {rel}")
                if existed:
                    os.remove(p)
                self._send(200, json.dumps({"ok": True, "existed": existed}))
            elif op == "glob":
                res = fs_walk(
                    ROOT,
                    body.get("include"),
                    body.get("exclude"),
                    type_=body.get("type") or "file",
                    max_depth=int(body.get("max_depth") or 0),
                    limit=min(
                        FS_CAP_RESULTS, max(1, int(body.get("limit") or FS_CAP_RESULTS))
                    ),
                )
                self._send(200, json.dumps(res))
            elif op == "grep":
                pat = body.get("pattern")
                if not isinstance(pat, str) or not pat:
                    raise OpError('"pattern" must be a non-empty string.')
                literal = bool(body.get("literal"))
                try:
                    rx = re.compile(re.escape(pat) if literal else pat)
                except re.error as e:
                    raise OpError(f"invalid pattern: {e}") from e
                scope = body.get("path") or ""
                files = fs_walk(
                    ROOT, body.get("include"), body.get("exclude"), limit=FS_CAP_WALK
                )["files"]
                matches, scanned = [], 0
                for rel2 in files:
                    if scope and rel2 != scope and not rel2.startswith(scope + "/"):
                        continue
                    if not is_text_name(rel2):
                        continue
                    p = os.path.join(ROOT, rel2)
                    try:
                        if os.path.getsize(p) > FS_CAP_GREP_FILE:
                            continue
                        with open(p, encoding="utf-8", errors="replace") as f:
                            text = f.read()
                    except OSError:
                        continue
                    scanned += 1
                    for n, line in enumerate(text.split("\n"), 1):
                        if rx.search(line):
                            num = (
                                ""
                                if not body.get("return_line_numbers", True)
                                else f"{n}:"
                            )
                            matches.append(f"{rel2}:{num}{line}")
                            if len(matches) >= FS_CAP_GREP:
                                self._send(
                                    200,
                                    json.dumps(
                                        {
                                            "matches": matches,
                                            "scanned": scanned,
                                            "truncated": True,
                                        }
                                    ),
                                )
                                return
                self._send(
                    200,
                    json.dumps(
                        {"matches": matches, "scanned": scanned, "truncated": False}
                    ),
                )
            elif op in FS_OPS_GET:
                self._send(
                    405,
                    json.dumps(
                        {
                            "error": f"op {op!r} is a GET op — resend as GET /anvil/fs?op=…&path=…"
                        }
                    ),
                )
            else:
                raise OpError(
                    f"unknown op {op!r} — GET ops: {', '.join(FS_OPS_GET)}; POST ops: {', '.join(FS_OPS_POST)}"
                )
        except SandboxError as e:
            self._send(400, json.dumps({"error": str(e)}))
        except OpError as e:
            self._send(400, json.dumps({"error": str(e)}))
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, json.dumps({"error": f"bad arguments: {e}"}))

    def _relay_get(self):  # spec 022 FR-001..005
        import urllib.error
        import urllib.request
        from urllib.parse import parse_qs, unquote

        q = parse_qs(
            self.path.split("?", 1)[1] if "?" in self.path else "",
            keep_blank_values=True,
        )
        target = unquote(q.get("url", [""])[0]).strip()
        if not target:
            self._send(
                400,
                json.dumps(
                    {"error": "missing ?url=<percent-encoded absolute http(s) URL>"}
                ),
            )
            return
        try:
            import ipaddress
            from urllib.parse import urlsplit

            parts = urlsplit(target)
            host = (parts.hostname or "").strip().lower()
            ip = None
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(host)
            if parts.scheme not in ("http", "https") or not host:
                self._send(
                    400,
                    json.dumps(
                        {
                            "error": f"relay target must be absolute http(s), got {target!r}"
                        }
                    ),
                )
                return
            loopback = host in ("localhost",) or (
                ip is not None and (ip.is_loopback or ip.is_link_local)
            )
            if loopback and not RELAY_ALLOW_LOOPBACK:
                self._send(
                    400,
                    json.dumps(
                        {
                            "error": "refused: relay target is loopback/link-local (private LAN is allowed)"
                        }
                    ),
                )
                return

            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None  # FR-003: never follow — a hop could bypass the target checks

            opener = urllib.request.build_opener(_NoRedirect)
            req = urllib.request.Request(
                target, method="GET", headers={"User-Agent": "anvil-launcher-relay/1"}
            )
            try:
                with opener.open(req, timeout=RELAY_TIMEOUT) as r:
                    body = r.read(RELAY_CAP + 1)
                    status, ctype = (
                        r.status,
                        (r.headers.get("Content-Type") or "application/octet-stream"),
                    )
            except HTTPError as e:
                if 300 <= e.code < 400:
                    loc = e.headers.get("Location") or ""
                    print(
                        f"relay: GET {target} -> 30x, refusing to follow hop to {loc}",
                        flush=True,
                    )
                    self._send(
                        502,
                        json.dumps(
                            {
                                "error": f"upstream redirected to {loc or 'unknown'} — not followed; the caller decides",
                                "location": loc,
                            }
                        ),
                    )
                    return
                body = e.read(RELAY_CAP + 1) if e.fp else b""
                status, ctype = (
                    e.code,
                    (e.headers.get("Content-Type") or "application/octet-stream"),
                )
            except Exception as e:
                print(f"relay: GET {target} -> ERROR {e}", flush=True)
                self._send(
                    502, json.dumps({"error": f"relay could not reach {target}: {e}"})
                )
                return
            if len(body) > RELAY_CAP:
                print(
                    f"relay: GET {target} -> {status} REFUSED (body over {RELAY_CAP} bytes)",
                    flush=True,
                )
                self._send(
                    502,
                    json.dumps(
                        {
                            "error": f"upstream body exceeds the {RELAY_CAP}-byte relay cap"
                        }
                    ),
                )
                return
            print(f"relay: GET {target} -> {status} ({len(body)} bytes)", flush=True)
            self._send(status, body, ctype)
        except Exception as e:  # defensive: the relay must never 500 raw
            self._send(400, json.dumps({"error": f"relay request refused: {e}"}))

    def log_message(
        self, format, *args
    ):  # quieter: skip /anvil/* polls; token never logged (headers aren't)
        with contextlib.suppress(Exception):  # logging must never raise
            if args and "/anvil/" in str(args[0]):
                return
        super().log_message(format, *args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def confirm_root():
    """Blast-radius control (FR-009): serving $HOME or / needs an explicit terminal y."""
    home = os.path.realpath(os.path.expanduser("~"))
    if ROOT not in (home, "/"):
        return
    where = "$HOME" if home == ROOT else "/"
    if not sys.stdin.isatty():
        raise SystemExit(
            f"refusing to serve {where} without a terminal y/N confirmation"
        )
    try:
        ans = input(
            f"Serving {where} ({ROOT}) gives the page read/write access to it. Continue? [y/N] "
        )
    except EOFError:
        ans = ""
    if ans.strip().lower() not in ("y", "yes"):
        raise SystemExit("aborted")


# ---- selftest (FR-010): security invariants against a live temp launcher ----
def selftest():
    tmp = tempfile.mkdtemp(prefix="anvil-selftest-")
    try:
        os.makedirs(os.path.join(tmp, "src"))
        with open(os.path.join(tmp, "src", "hello.txt"), "w") as f:
            f.write("alpha\nbeta\n")
        with open(os.path.join(tmp, "img.bin"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nbinary-bytes")
    except OSError as e:
        raise SystemExit(f"SELFTEST ABORT: fixture setup failed: {e}") from e
    port = 8871
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__)],
        cwd=tmp,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    fails = []

    def check(name, cond, detail=""):
        print(
            ("  PASS " if cond else "  FAIL ")
            + name
            + (f" — {detail}" if detail and not cond else "")
        )
        if not cond:
            fails.append(name)

    def req(
        method,
        op=None,
        path_q=None,
        body=None,
        token=True,
        host=None,
        raw_path="/anvil/fs",
    ) -> "tuple[int, Any, str]":
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            headers: dict = {"Content-Type": "application/json"}
            if token:
                headers["X-Anvil-Token"] = tok[0]
            if host:
                headers["Host"] = host
            url = raw_path + (path_q or "")
            c.request(
                method, url, json.dumps(body) if body is not None else None, headers
            )
            r = c.getresponse()
            data = r.read()
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = data
            return r.status, parsed, (r.getheader("X-Anvil-Fs") or "")
        finally:
            c.close()

    tok: list[str | None] = [None]
    d: dict = {}  # pre-bound: the readiness loop may time out before assigning
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                c.request("GET", "/anvil/env")
                r = c.getresponse()
                d = json.loads(r.read())
                tok[0] = d.get("token")
                c.close()
                if tok[0]:
                    break
            except Exception:
                time.sleep(0.3)
        check(
            "env descriptor delivers fs/root/token",
            bool(tok[0]) and bool(d.get("fs")) and bool(d.get("root")),
            str(d),
        )
        st, body, _ = req("GET", path_q="?op=read&path=src/hello.txt", token=False)
        check("403 without token", st == 403, str(st))
        st, _, _ = req(
            "GET", path_q="?op=read&path=src/hello.txt", host="attacker.example:8871"
        )
        check("spoofed Host refused (DNS rebinding)", st == 403, str(st))
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request(
            "OPTIONS",
            "/anvil/fs",
            "",
            {"X-Anvil-Token": str(tok[0]), "Origin": "https://evil.example"},
        )
        r = c.getresponse()
        r.read()
        c.close()
        check(
            "OPTIONS stays 501 (foreign preflights die)", r.status == 501, str(r.status)
        )
        st, body, _ = req("GET", path_q="?op=read&path=" + "../" + "secret.txt")
        check(
            "dotdot escape refused",
            st == 400 and "escape" not in str(body) or st == 400,
            str(st),
        )
        os.symlink("/etc/hostname", os.path.join(tmp, "ln.txt"))
        st, body, _ = req("GET", path_q="?op=read&path=ln.txt")
        check("symlink escape refused (realpath)", st == 400, str(st))
        st, body, _ = req("GET", path_q="?op=read&path=src")
        check("directory read errors", st == 400 and "directory" in str(body), str(st))
        st, body, _ = req("GET", path_q="?op=bogus&path=x")
        check("unknown op 400 + op list", st == 400 and "write" in str(body), str(st))
        st, body, _ = req("POST", body={"op": "read", "path": "src/hello.txt"})
        check(
            "wrong method 405", st == 405, str(st)
        )  # read is a GET op; POST carries write-family ops only
        st, body, hdr = req("GET", path_q="?op=read&path=src/hello.txt")
        check(
            "read works + X-Anvil-Fs: v1",
            st == 200 and body.get("text") == "alpha\nbeta\n" and hdr == "v1",
            str(st),
        )
        st, body, _ = req("GET", path_q="?op=blob&path=img.bin")
        check(
            "blob returns base64 bytes",
            st == 200
            and base64.b64decode(body.get("b64", ""))
            == b"\x89PNG\r\n\x1a\nbinary-bytes",
            str(st),
        )
        st, body, _ = req(
            "POST",
            body={"op": "write", "path": "nested/dir/new.txt", "content": "one two"},
        )
        check(
            "write mkdir-p",
            st == 200 and os.path.isfile(os.path.join(tmp, "nested/dir/new.txt")),
            str(st),
        )
        st, body, _ = req(
            "POST",
            body={
                "op": "edit",
                "path": "nested/dir/new.txt",
                "replacements": [{"old_text": "STALE", "new_text": "x"}],
            },
        )
        check(
            "edit drift (stale old_text) refused",
            st == 400 and "drift" in str(body),
            str(st),
        )
        st, body, _ = req(
            "POST",
            body={
                "op": "edit",
                "path": "nested/dir/new.txt",
                "replacements": [{"old_text": "two", "new_text": "TWO"}],
            },
        )
        check(
            "edit applies",
            st == 200 and "one TWO" in Path(tmp, "nested/dir/new.txt").read_text(),
            str(st),
        )
        st, body, _ = req("POST", body={"op": "glob", "include": "*.txt"})
        check(
            "glob caps mirrored",
            st == 200 and "src/hello.txt" in body.get("files", []),
            str(st),
        )
        st, body, _ = req(
            "POST", body={"op": "grep", "pattern": "TWO", "literal": True}
        )
        check(
            "grep finds match",
            st == 200
            and any("nested/dir/new.txt" in m for m in body.get("matches", [])),
            str(st),
        )
        st, body, _ = req("POST", body={"op": "delete", "path": "nested/dir/new.txt"})
        check(
            "delete removes",
            st == 200 and not os.path.exists(os.path.join(tmp, "nested/dir/new.txt")),
            str(st),
        )
        st, body, _ = req("POST", body={"op": "delete", "path": "gone/already.txt"})
        check("delete missing is fine", st == 200, str(st))
        st, body, _ = req("GET", path_q="?op=exists&path=src/hello.txt")
        check("exists", st == 200 and bool(body.get("exists")), str(st))

        # ---- relay invariants (spec 022 FR-001..004/008) ----
        import threading as _th

        class _Stub(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/search"):
                    b = json.dumps(
                        {"results": [{"title": "needle", "url": "https://x"}]}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                elif self.path.startswith("/redirect"):
                    b = b"hop"
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:9/interior")
                elif self.path.startswith("/big"):
                    b = b"x" * (RELAY_CAP + 1)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                elif self.path.startswith("/plain"):
                    b = b"just text"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/weird-custom")
                else:
                    b = b"?"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, format, *args):
                pass

        stub_port = 23000 + os.getpid() % 2000
        stub_srv = http.server.ThreadingHTTPServer(("127.0.0.1", stub_port), _Stub)
        _th.Thread(target=stub_srv.serve_forever, daemon=True).start()
        port2 = 25000 + os.getpid() % 2000
        proc2 = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            cwd=tmp,
            env=dict(os.environ, PORT=str(port2), ANVIL_RELAY_ALLOW_LOOPBACK="1"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def req2(path_q, token=True, host=None):
            c = http.client.HTTPConnection("127.0.0.1", port2, timeout=10)
            try:
                headers: dict = {}
                if token:
                    headers["X-Anvil-Token"] = d2.get(
                        "token"
                    )  # late-bound: set by the readiness loop below
                if host:
                    headers["Host"] = host
                c.request("GET", "/anvil/proxy" + path_q, None, headers)
                r = c.getresponse()
                return r.status, r.read(), (r.getheader("Content-Type") or "")
            finally:
                c.close()

        try:
            _ = None
            d2: dict = {}
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    c = http.client.HTTPConnection("127.0.0.1", port2, timeout=2)
                    c.request("GET", "/anvil/env")
                    d2 = json.loads(c.getresponse().read())
                    c.close()
                    if d2.get("token") and bool(d2.get("relay")):
                        break
                except Exception:
                    time.sleep(0.3)
            check(
                "env descriptor carries relay:true",
                bool(d2.get("relay")),
                str(d2.get("relay")),
            )
            tgt = f"http%3A%2F%2F127.0.0.1%3A{stub_port}%2Fsearch%3Fq%3Dx"
            st, body, _ = req2("?url=" + tgt, token=False)
            check("relay 403 without token", st == 403, str(st))
            c = http.client.HTTPConnection("127.0.0.1", port2, timeout=5)
            c.request(
                "GET", "/anvil/proxy?url=" + tgt, None, {"X-Anvil-Token": "deadbeef"}
            )
            r = c.getresponse()
            r.read()
            c.close()
            check("relay wrong-token 403", r.status == 403, str(r.status))
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(
                "OPTIONS",
                "/anvil/proxy",
                "",
                {"X-Anvil-Token": str(tok[0]), "Origin": "https://evil.example"},
            )
            r = c.getresponse()
            r.read()
            c.close()
            check("relay OPTIONS stays 501", r.status == 501, str(r.status))
            st, body, _ = req("GET", raw_path="/anvil/proxy", path_q="?url=" + tgt)
            check(
                "loopback refused by default launcher",
                st == 400 and "loopback" in str(body),
                f"{st} {str(body)[:80]}",
            )
            st, body, ctype = req2("?url=" + tgt)
            check(
                "relay round-trip + status + JSON body",
                st == 200 and b"needle" in body,
                f"{st} {body[:80]}",
            )
            check(
                "relay passes upstream Content-Type", "application/json" in ctype, ctype
            )
            st, body, ctype = req2(f"?url=http%3A%2F%2F127.0.0.1%3A{stub_port}%2Fplain")
            check(
                "relay passes a custom Content-Type",
                "text/weird-custom" in ctype,
                ctype,
            )
            st, body, _ = req2("?url=file%3A%2F%2F%2Fetc%2Fpasswd")
            check(
                "non-http(s) target refused",
                st == 400 and "http(s)" in str(body),
                str(st),
            )
            st, body, _ = req2(f"?url=http%3A%2F%2F127.0.0.1%3A{stub_port}%2Fredirect")
            check(
                "redirect NOT followed, hop named",
                st == 502 and "127.0.0.1:9/interior" in str(body),
                f"{st} {body[:120]}",
            )
            st, body, _ = req2(f"?url=http%3A%2F%2F127.0.0.1%3A{stub_port}%2Fbig")
            check(
                "size cap refused",
                st == 502 and "cap" in str(body),
                f"{st} {body[:80]}",
            )
            st, body, _ = req2("")
            check(
                "missing url 400 self-describing",
                st == 400 and "url=" in str(body),
                str(st),
            )
            c = http.client.HTTPConnection("127.0.0.1", port2, timeout=5)
            c.request("POST", "/anvil/proxy", "", {"X-Anvil-Token": str(tok[0])})
            r = c.getresponse()
            r.read()
            c.close()
            check("relay POST 405 (GET-only)", r.status == 405, str(r.status))
        finally:
            proc2.terminate()
            proc2.wait(timeout=5)
            stub_srv.shutdown()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
            _drain = proc.stdout.read() if proc.stdout else ""  # drain the pipe
        except Exception as e:  # cleanup must never mask the verdict
            print(f"  (launcher cleanup: {e})")
    print("SELFTEST " + ("PASS" if not fails else "FAIL: " + ", ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    confirm_root()
    found = [k for k in WHITELIST if os.environ.get(k)]
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        print(f"Anvil: http://127.0.0.1:{PORT}/Anvil.html")
        print(f"Sandbox root: {ROOT}")
        print(
            f"Env bridge: {'ACTIVE for ' + ', '.join(found) if found else 'no whitelisted keys set (serve-only mode)'}"
        )
        print("fs bridge: ACTIVE (token-gated /anvil/fs under the sandbox root)")
        print(
            f"relay: ACTIVE (token-gated GET /anvil/proxy; loopback {'ALLOWED (test override)' if RELAY_ALLOW_LOOPBACK else 'refused'}, private LAN allowed)"
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")
