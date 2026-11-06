"""Checks on the finished video, plus a frame grab per shot for review.

    uv run python check.py

Exit code 1 if a check fails. Frames go to out/frames/ (look at every one before upload).
"""

import json
import re
import shutil
import subprocess
import sys

from common import FPS, OUT, SANDBOX_HOST, need, probe, run  # noqa: F401

LIMIT = 170.0  # 2:50, inside the 3:00 Devpost limit


def main() -> None:
    video = OUT / "creator-milestone-demo.mp4"
    soft = OUT / "creator-milestone-demo-softsubs.mp4"
    if not video.exists():
        sys.exit(f"{video} not found. Run assemble.py first.")
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    fps = eval(v["r_frame_rate"])  # noqa: S307 - ffprobe fraction like 30/1
    results: list[tuple[str, bool, str]] = [
        ("duration under 2:50", dur < LIMIT, f"{dur:.1f}s"),
        ("resolution 1920x1080", (v["width"], v["height"]) == (1920, 1080), f"{v['width']}x{v['height']}"),
        ("H.264 video", v["codec_name"] == "h264", v["codec_name"]),
        ("30 fps", abs(fps - 30) < 0.01, f"{fps:.2f}"),
        ("audio present (AAC)", bool(a) and a["codec_name"] == "aac", a["codec_name"] if a else "none"),
    ]
    vol = subprocess.run([need("ffmpeg"), "-hide_banner", "-i", str(video), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", vol)
    results.append(("audio is not silent", bool(mean) and float(mean[1]) > -50, f"mean {mean[1]} dB" if mean else "unknown"))
    if soft.exists():
        kinds = [s["codec_type"] for s in probe(soft)["streams"]]
        results.append(("soft-sub version has a subtitle track", "subtitle" in kinds, ", ".join(kinds)))
    results.append(("retimed captions.srt written", (OUT / "captions.srt").exists(), ""))

    timeline = json.loads((OUT / "timeline.json").read_text())
    frames = OUT / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    for s in timeline["shots"]:
        for label, frac in (("a", 0.2), ("b", 0.75)):
            t = s["start"] + s["duration"] * frac
            run([need("ffmpeg"), "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(frames / f"{s['shot']}-{label}.png")])
    results.append(("frame grabs", len(list(frames.glob("*.png"))) == 2 * len(timeline["shots"]), f"{len(list(frames.glob('*.png')))} in out/frames/"))

    bad = False
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
        bad |= not ok
    if timeline.get("mode") == "dry":
        print("NOTE  this is a DRAFT from the dry run (fake runner, PayPal pages are placeholders)")
    for s in timeline["shots"]:
        for n in s.get("notes", []):
            print(f"WARN  {s['shot']}: {n}")
        if s.get("narration_estimated"):
            print(f"WARN  {s['shot']}: narration audio missing, length estimated")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
