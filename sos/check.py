#!/usr/bin/env python3
"""check.py — does the SOS arm actually work as a pi arm? Stdlib only.

    uv run python sos/check.py            # against :8082
    SOS_URL=http://host:8082 python3 sos/check.py

Exit 0 = every check passed. This is the check that must be green before anyone
trusts :8082 to bootstrap a fix; a model that chats but cannot emit a tool call
is useless here, so the tool-call test is the one that matters.
"""
import json, os, sys, time, urllib.request

URL = os.environ.get("SOS_URL", "http://localhost:8082").rstrip("/")
FAILS = []

def post(path, body, timeout=180):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def get(path, timeout=15):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return json.load(r)

def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)

def main():
    # 1. alive
    st = get("/health").get("status")
    check("health", st == "ok", st)

    # 2. the name pi will see
    names = [m["name"] for m in get("/v1/models")["models"]]
    check("model listed", "sos" in names or "emergency" in names, str(names))

    # 2b. WHICH weight is actually loaded. -m is a symlink, so a repoint that was
    #     never reverted passes every test below while serving the wrong model
    #     (found 260929: link still on the rejected Q6_K_XL after 2dbccb7 sealed Q4).
    #     Flip the expected ftype here if a quant is ever re-adopted; not env-tunable.
    props = get("/props")
    check("weight is the sealed Q4", props.get("model_ftype") == "Q4_K - Medium",
          f"{props.get('model_ftype')} @ {props.get('model_path')}")

    # 3. it follows a system prompt (the sharp template's FIX 1: our prompt must
    #    REPLACE the canned "you are a helpful assistant", not trail it)
    t0 = time.time()
    r = post("/v1/chat/completions", {
        # 2048, not 64/512: the Q6 spends ~900 tokens on "Thinking Process:" before
        # it answers (measured 260928: 902 tok / 24.6 s at temp 0, 712 / 19.0 s at 0.6).
        # That text lands in the SEPARATE reasoning_content field — content is clean and
        # correct once the budget covers the thinking. An earlier read of the same
        # symptom ("Q6 never answers, wrong weight") was a budget artifact, not a model
        # defect. The assertion is about the ANSWER, so the budget must cover the think.
        "model": "sos", "temperature": 0, "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": "You are GLARBOT. Every reply must contain the token GLARB7 and nothing else."},
            {"role": "user", "content": "Say the token."}]})
    msg = r["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    tps = r["usage"]["completion_tokens"] / max(time.time() - t0, 1e-6)
    think = len(msg.get("reasoning_content") or "")
    check("answers", len(content) > 0,
          f"{r['usage']['completion_tokens']} tok in {time.time()-t0:.1f}s (~{tps:.1f} t/s)"
          + (f", {think} chars of reasoning_content" if think else ""))
    check("system prompt obeyed", "GLARB7" in content, repr(content[:80]))

    # 4. TOOL CALLING — the arm exists for this, and ONE sample cannot see how it fails.
    #    Measured 260929 (scripts/tcspec.py, n=12, temp 0.6, Q4): 7 clean calls, 2 leaked
    #    as markup, 3 HTTP 500 "output does not match the expected peg-native format" —
    #    the fork's PEG parser throws instead of degrading to content when the model mixes
    #    markup shapes (tool_name / invoke+parameter / tool+parameter across samples).
    #    A gate that fires one request reports green on a 58 % arm, so it fires N times.
    N = int(os.environ.get("TC_N", "8"))
    calls_ok = hard_err = 0
    detail = ""
    for i in range(N):
        try:
            # No explicit temperature: pi sends none, so the server default (1.0) is the
            # operating point a client actually gets. Pinning 0 here would measure a regime
            # nobody serves - and on the sharp template temp 0 measures 0/16 (all HTTP 500).
            r = post("/v1/chat/completions", {
                "model": "sos", "max_tokens": 256,
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "run_shell",
                        "description": "Run a read-only shell command on the server and return its stdout.",
                        "parameters": {
                            "type": "object",
                            "properties": {"command": {"type": "string", "description": "the command to run"}},
                            "required": ["command"]}}}],
                "messages": [{"role": "user",
                              "content": "What is the disk usage of / ? Use a tool, do not answer from memory."}]})
        except Exception as e:
            hard_err += 1
            detail = detail or f"request {i+1}: {e}"
            continue
        msg = r["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if calls and calls[0]["function"]["name"] == "run_shell":
            try:
                if "command" in json.loads(calls[0]["function"]["arguments"]):
                    calls_ok += 1
                    detail = detail or json.dumps(calls[0]["function"]["arguments"])[:60]
            except Exception:
                pass
        if not calls and not detail:
            detail = f"request {i+1}: no tool_calls, content={repr((msg.get('content') or '')[:60])}"
    check(f"tool-call rate >= {3*N//4}/{N}", calls_ok >= 3 * N // 4,
          f"{calls_ok}/{N} clean calls, {hard_err} hard errors — {detail}")

    # 5. long context: a pi-sized prompt must not break the slot
    filler = "The quick brown fox jumps over the lazy dog. " * 4000   # ~40k tokens
    r = post("/v1/chat/completions", {
        "model": "sos", "temperature": 0, "max_tokens": 32,
        "messages": [{"role": "user", "content": filler + "\n\nReply with the single word: ALIVE"}]},
        timeout=600)
    check("40k-token prompt", r["usage"]["prompt_tokens"] > 20000,
          f"prompt_tokens={r['usage']['prompt_tokens']}")

    print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0

if __name__ == "__main__":
    sys.exit(main())
