"""Shared paths, script parsing and ffmpeg helpers for the demo-video pipeline."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_DIR = Path(__file__).resolve().parent
REPO = VIDEO_DIR.parent
DOCS = REPO / "docs"
RAW = VIDEO_DIR / "raw"
OUT = VIDEO_DIR / "out"
FPS = 30
W, H = 1920, 1080
SANDBOX_HOST = "www.sandbox.paypal.com"
DEMO_URL = "https://creator-milestone.onrender.com"
REPO_URL_PLACEHOLDER = "github.com/gguip1/creator-milestone"
PITCH = (
    "When a client asks for one more change, CreatorMilestone's AI checks the request against the scope "
    "both sides agreed to, prices the extras from the artist's rate card, and turns what both approve "
    "into a PayPal invoice."
)

# On-screen text per shot, from docs/demo-script.md. {num} is the invoice number from the take.
SHOT_TEXT: dict[str, list[str]] = {
    "S1": ["Extra request → agreed clause → $80 + $20 = $100"],
    "S2": ["PayPal sandbox. No real money.", "Flashback: how the agreement began."],
    "S3": ["Revisions: Needs confirmation", "Usage rights and client email: Unknown"],
    "S4": ["Seller accepts", "Client accepts: scope v1"],
    "S5": ["Scope v2", "Rules compute the amount. Jiwoo approves."],
    "S6": ["PayPal sandbox page", "Same invoice: {num}"],
    "S7": ["Sandbox buyer pays invoice {num}, $100.00"],
    "S8": ["Paid via PayPal. Read back from PayPal."],
    "S9": [],
}


def ensure_dirs() -> None:
    for d in (RAW, OUT):
        d.mkdir(parents=True, exist_ok=True)


def parse_narration() -> dict[str, str]:
    lines = {}
    for line in (DOCS / "narration.txt").read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            shot, text = line.split("\t", 1)
            lines[shot.strip()] = text.strip()
    return lines


def _secs(stamp: str) -> int:
    m, s = stamp.split(":")
    return int(m) * 60 + int(s)


def parse_timing() -> dict[str, dict]:
    """Shot id -> {start, end, window, type} from the timing table of docs/demo-script.md."""
    rows = {}
    pat = re.compile(r"^\|\s*(S\d)\s*\|\s*([\d:]+)\s*\|\s*([\d:]+)\s*\|\s*\d+\s*\|\s*[\d.]+ s\s*\|\s*([^|]+?)\s*\|")
    for line in (DOCS / "demo-script.md").read_text(encoding="utf-8").splitlines():
        m = pat.match(line)
        if m:
            start, end = _secs(m[2]), _secs(m[3])
            rows[m[1]] = {"start": start, "end": end, "window": end - start, "type": m[4]}
    return rows


def parse_srt() -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", (DOCS / "demo-captions.srt").read_text(encoding="utf-8").strip()):
        parts = block.splitlines()
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", parts[1])
        a = [int(x) for x in m.groups()]
        cues.append({
            "start": a[0] * 3600 + a[1] * 60 + a[2] + a[3] / 1000,
            "end": a[4] * 3600 + a[5] * 60 + a[6] + a[7] / 1000,
            "text": " ".join(parts[2:]),
        })
    return cues


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        sys.exit(f"{tool} not found. Install it with: brew install ffmpeg")
    return path


def run(cmd: list[str], quiet: bool = True) -> None:
    res = subprocess.run(cmd, capture_output=quiet, text=True)
    if res.returncode:
        sys.exit(f"command failed: {' '.join(cmd[:6])} ...\n{(res.stderr or '')[-1500:]}")


def probe(path: Path) -> dict:
    out = subprocess.run(
        [need("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def frame_ceil(seconds: float) -> float:
    """Round up to a whole number of 30 fps frames."""
    return int(seconds * FPS + 0.999999) / FPS
