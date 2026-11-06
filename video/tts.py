"""Narration: one audio file per shot from docs/narration.txt with Gemini TTS.

    uv run --env-file ../backend/.env python tts.py [--shots S1 S2] [--max-calls 15]

The key is read from LLM_API_KEY and never printed. Results are cached in raw/tts/, so a rerun
makes no API calls. The first model returns raw 16-bit PCM at 24 kHz, the fallback returns WAV;
both are written as 24 kHz mono WAV files.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import wave
from pathlib import Path

import httpx

from common import RAW, ensure_dirs, parse_narration

MODELS = ["gemini-3.1-flash-tts-preview", "gemini-3.8-flash-tts"]
VOICE = "Sulafat"  # Gemini prebuilt voice described as warm
STYLE = "Say in a calm, warm, professional voice, at a steady and unhurried pace: "
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TTS_DIR = RAW / "tts"


def to_wav(data: bytes, mime: str, dest: Path) -> None:
    """Write API audio as a 24 kHz mono 16-bit WAV. Raw PCM (audio/L16) gets a header; WAV is kept."""
    if data[:4] == b"RIFF":
        dest.write_bytes(data)
        return
    rate = 24000
    m = re.search(r"rate=(\d+)", mime or "")
    if m:
        rate = int(m[1])
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit, self.used = limit, 0

    def spend(self) -> None:
        if self.used >= self.limit:
            sys.exit(f"TTS call budget of {self.limit} reached; stopping. Cached shots are kept.")
        self.used += 1


class QuotaError(RuntimeError):
    """HTTP 429: the quota is spent. Switching models would only burn more calls."""


def synth(client: httpx.Client, key: str, model: str, text: str, voice: str) -> tuple[bytes, str]:
    # Only the first model gets the style prefix. The fallback model read it aloud in testing,
    # so it gets the bare text and relies on the voice choice for tone.
    prompt = STYLE + text if model == MODELS[0] else text
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    r = client.post(ENDPOINT.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=120)
    if r.status_code == 429:
        raise QuotaError(f"HTTP 429 (quota or rate limit): {r.text[:200].replace(key, '***')}")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300].replace(key, '***')}")
    part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    return base64.b64decode(part["data"]), part.get("mimeType", "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shots", nargs="*", help="only these shots (default: all)")
    ap.add_argument("--max-calls", type=int, default=15, help="hard cap on API calls, failures included")
    ap.add_argument("--voice", default=VOICE)
    args = ap.parse_args()
    ensure_dirs()
    TTS_DIR.mkdir(exist_ok=True)
    narration = parse_narration()
    shots = args.shots or list(narration)
    key = os.environ.get("LLM_API_KEY", "")
    meta_path = TTS_DIR / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    budget = Budget(args.max_calls)
    models = list(MODELS)
    with httpx.Client() as client:
        for shot in shots:
            text = narration[shot]
            digest = hashlib.sha256(f"{args.voice}|{STYLE}|{text}".encode()).hexdigest()[:16]
            dest = TTS_DIR / f"{shot}.wav"
            if dest.exists() and meta.get(shot, {}).get("digest") == digest and meta[shot].get("valid", True):
                print(f"{shot}: cached ({wav_seconds(dest):.1f}s)")
                continue
            if not key:
                sys.exit("LLM_API_KEY is not set. Run with: uv run --env-file ../backend/.env python tts.py")
            while True:
                model = models[0]
                budget.spend()
                try:
                    data, mime = synth(client, key, model, text, args.voice)
                    break
                except QuotaError as exc:
                    sys.exit(f"{shot}: {model}: {exc}\nQuota is spent. Stopping without retries; cached shots are kept.")
                except Exception as exc:  # noqa: BLE001 - report status only, never the key
                    print(f"{shot}: {model} failed ({str(exc).replace(key, '***')})")
                    if len(models) > 1:
                        models.pop(0)  # model unavailable: use the fallback for this and later shots
                    else:
                        sys.exit("No TTS model is available; stopping.")
            to_wav(data, mime, dest)
            secs = wav_seconds(dest)
            meta[shot] = {"digest": digest, "model": model, "mime": mime, "seconds": round(secs, 2), "voice": args.voice, "valid": True}
            meta_path.write_text(json.dumps(meta, indent=2))
            words = len(text.split())
            print(f"{shot}: {model} {mime} -> {secs:.1f}s, {words} words, {words / secs * 60:.0f} wpm")
    print(f"API calls used: {budget.used} of {args.max_calls}")


if __name__ == "__main__":
    main()
