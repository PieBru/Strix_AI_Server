"""faster-whisper STT test app — lab arm for strixy-9ad3.

gradio UI on :7863: pick model (large-v3 / large-v3-turbo) + language,
drop an audio file, get a transcript with timing info.

ponytail: ctranslate2 CPU int8 (the PyPI wheels carry no CUDA/ROCm).
Up to ~3x realtime on 32 cores — fine for a test arm. Upgrade path if STT
needs to be a low-latency always-on service: ctranslate2 ROCm wheel +
device="cuda" (ROCm maps into the cuda backend).
"""
from __future__ import annotations

import os
import time

import gradio as gr
from faster_whisper import WhisperModel

MODELS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
LANGS = ["auto", "it", "en", "de", "fr", "es", "zh", "ja"]

# lazy, one instance per model (int8 ≈ 3 GB / 1.6 GB RAM)
_cache: dict[str, WhisperModel] = {}


def get_model(name: str) -> WhisperModel:
    if name not in _cache:
        t0 = time.time()
        _cache[name] = WhisperModel(
            MODELS[name], device="cpu", compute_type="int8",
            cpu_threads=os.cpu_count() or 8,
        )
        print(f"loaded {name} in {time.time() - t0:.1f}s", flush=True)
    return _cache[name]


def transcribe(audio_path: str | None, model_name: str, language: str) -> tuple[str, str]:
    if not audio_path:
        return "", "no audio provided"
    print(f"TRANSCRIBE START path={audio_path} size={os.path.getsize(audio_path)}", flush=True)
    t0 = time.time()
    model = get_model(model_name)
    print(f"model ready {time.time() - t0:.1f}s", flush=True)
    segments, info = model.transcribe(audio_path, language=None if language == "auto" else language)
    print(f"transcribe done {time.time() - t0:.1f}s dur={info.duration}", flush=True)
    text = "".join(s.text for s in segments).strip()
    dt = time.time() - t0
    rtf = dt / info.duration if info.duration > 0 else 0
    meta = f"model={model_name} lang={info.language} (p={info.language_probability:.2f}) " \
           f"audio={info.duration:.1f}s wall={dt:.1f}s RTF={rtf:.2f}"
    return text or "(no speech detected)", meta


def ui() -> gr.Blocks:
    with gr.Blocks(title="STT — faster-whisper") as demo:
        gr.Markdown("## STT — faster-whisper (lab arm :7863)")
        with gr.Row():
            model = gr.Dropdown(list(MODELS), value="large-v3", label="Model")
            lang = gr.Dropdown(LANGS, value="auto", label="Language")
        audio = gr.Audio(type="filepath", label="Audio (upload or record)")
        btn = gr.Button("Transcribe", variant="primary")
        out = gr.Textbox(label="Transcript", lines=8)
        meta = gr.Textbox(label="Info", interactive=False)
        btn.click(transcribe, [audio, model, lang], [out, meta])
        audio.change(transcribe, [audio, model, lang], [out, meta])
    return demo


if __name__ == "__main__":
    ui().launch(server_name="0.0.0.0", server_port=7863)
