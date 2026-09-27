"""Minimal ACE-Step 1.5 music generator UI -> acestep-serve (audio.cpp) on :8001.

Same shape as ~/Piero/Work/H3/simple_video_ui.py: thin gradio front, engine elsewhere,
stdlib urllib only. The engine is a task server: POST /v1/tasks/run returns the WAV
base64'd in JSON.
"""
import base64, json, pathlib, random, tempfile, urllib.request

import gradio as gr

API = "http://127.0.0.1:8001"
MODEL = "acestep"
UI_PORT = 7862  # one source for the header and launch() — the header cannot rot

LANGUAGES = ["en", "zh", "ja", "ko", "es", "fr", "de", "it", "pt", "ru"]


def post(path, payload, timeout=1800):
    req = urllib.request.Request(API + path, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def health():
    try:
        h = json.load(urllib.request.urlopen(API + "/health", timeout=5))
        m = json.load(urllib.request.urlopen(API + "/v1/models", timeout=5))["data"]
        loaded = next((x["loaded"] for x in m if x["id"] == MODEL), False)
        return f"**engine** `{h['backend']}` · model **{'loaded' if loaded else 'lazy (loads on first song)'}**"
    except Exception as ex:  # noqa: BLE001 — the UI must show the failure, not raise it
        return f"**engine DOWN** `{type(ex).__name__}: {ex}` — `systemctl --user start acestep-serve`"


def generate(prompt, lyrics, duration, language, thinking, steps, seed, randomize):
    if not prompt.strip():
        raise gr.Error("A prompt is required — describe the music.")
    if randomize or seed is None:
        seed = random.randrange(1, 2**31 - 1)
    request = {
        "text": prompt,
        "lyrics": lyrics,
        "duration_seconds": float(duration),
        "num_inference_steps": int(steps),
        "seed": int(seed),
        "language": language,
        "route": "text2music",
        # thinking=true runs the 1.7B planner LM first (BPM/key/lyric structure);
        # false goes straight to the DiT. Both fit in GTT; true is slower but better.
        "options": {"thinking": bool(thinking)},
    }
    r = post("/v1/tasks/run", {"model": MODEL, "request": request})
    t = r.get("timing", {})
    status = (f"seed **{seed}** · {t.get('audio_duration_ms', 0) / 1000:.1f} s of audio in "
              f"{t.get('wall_ms', 0) / 1000:.1f} s (RTF {t.get('rtf', 0):.2f}) · "
              f"{r['channels']} ch @ {r['sample_rate']} Hz")
    out = pathlib.Path(tempfile.gettempdir()) / f"acestep_{seed}.wav"
    out.write_bytes(base64.b64decode(r["audio"]))
    return str(out), status, int(seed)


def unload():
    post("/v1/tasks/unload_models", {"model_ids": [MODEL]})
    return health()


with gr.Blocks(title="ACE-Step music") as demo:
    gr.Markdown(f"# ACE-Step 1.5 — music lab (:{UI_PORT})")
    status = gr.Markdown(health())
    with gr.Row():
        with gr.Column(scale=2):
            prompt = gr.Textbox(label="Prompt", lines=3,
                                placeholder="warm analog synth pop with female vocals, wide drums")
            lyrics = gr.Textbox(label="Lyrics", lines=6, placeholder="[verse]\n...\n[chorus]\n...")
            with gr.Row():
                duration = gr.Slider(5, 120, value=30, step=1, label="Duration (s)")
                steps = gr.Slider(1, 30, value=8, step=1, label="Diffusion steps")
            with gr.Row():
                language = gr.Dropdown(LANGUAGES, value="en", label="Vocal language")
                thinking = gr.Checkbox(value=True, label="Planner LM (thinking)")
            with gr.Row():
                seed = gr.Number(value=1234, precision=0, label="Seed")
                randomize = gr.Checkbox(value=True, label="Random seed")
            btn = gr.Button("Generate", variant="primary")
        with gr.Column(scale=2):
            audio = gr.Audio(label="Result", type="filepath")
            unload_btn = gr.Button("Unload model from VRAM/GTT")
    btn.click(generate, [prompt, lyrics, duration, language, thinking, steps, seed, randomize],
              [audio, status, seed])
    unload_btn.click(unload, None, status)
    demo.load(health, None, status)  # re-probe on every page load, not once at import
    gr.Markdown("Engine: `acestep-serve.service` → `127.0.0.1:8001` (audio.cpp ACE-Step 1.5 "
                "turbo 2B, q8_0 GGUF, Vulkan/RADV on the 8060S). Stop it with "
                "`systemctl --user stop acestep-serve`.")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=UI_PORT, theme="default")
