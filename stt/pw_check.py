"""Playwright live check for the whisper-stt gradio arm (:7863).

Uploads the espeak Italian sample and asserts the rendered transcript.
Run: uv run --offline --with playwright python stt/pw_check.py
"""
import sys
from playwright.sync_api import sync_playwright

WAV = "/home/piero/Piero/Work/Strix_AI_Server/stt/testaudio/stt-it.wav"
EXPECT = "riconoscimento vocale"


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto("http://127.0.0.1:7863", wait_until="networkidle", timeout=30000)
        pg.locator('input[type="file"]').first.set_input_files(WAV)
        # gradio 6 Textbox is a <textarea>: innerText never sees its value,
        # so poll input_value() (learned the hard way 260928).
        ta = pg.locator("textarea").first
        try:
            pg.wait_for_function("""() => {
                const t = document.querySelector('textarea');
                return t && t.value && t.value.length > 10;
            }""", timeout=180000)
            val = ta.input_value()
        except Exception:
            pg.screenshot(path="/tmp/stt-pw-check-fail.png")
            b.close()
            return 1
        if EXPECT not in val:
            print(f"WRONG TEXT: {val!r}", flush=True)
            pg.screenshot(path="/tmp/stt-pw-check-fail.png")
            b.close()
            return 1
        pg.screenshot(path="/tmp/stt-pw-check.png")
        b.close()
    print(f"PW_CHECK_OK {val!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
