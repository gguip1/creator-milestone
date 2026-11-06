"""Composition and safety checks that need no browser, network or PayPal.

    uv run pytest
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assemble  # noqa: E402
import record  # noqa: E402
from common import duration, probe  # noqa: E402


def make_clip(path: Path, seconds: float, size: str, inner: str | None = None) -> None:
    """A stub clip: test pattern, or a small pattern on gray (like a popup recording)."""
    if inner:
        graph = f"color=gray:s={size}:r=30:d={seconds}[g];testsrc=s={inner}:r=30:d={seconds}[t];[g][t]overlay=0:0"
    else:
        graph = f"testsrc=s={size}:r=30:d={seconds}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", graph, "-pix_fmt", "yuv420p", str(path)], check=True)


def test_s7_is_composed_from_three_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(assemble, "RAW", tmp_path)
    make_clip(tmp_path / "main.mp4", 12, "1920x930")
    make_clip(tmp_path / "popup.mp4", 8, "1920x930", inner="480x640")
    base = {"idle": [], "cut": [], "focus": []}
    segs = [
        {**base, "kind": "desktop", "file": "main.mp4", "in": 2.0, "out": 3.5},           # invoice page up to the click
        {**base, "kind": "popup", "file": "popup.mp4", "in": 1.0, "out": 6.0,             # the popup, login span cut
         "cut": [[2.0, 3.0]], "crop": [480, 640]},
        {**base, "kind": "desktop", "file": "main.mp4", "in": 8.0, "out": 9.5},           # back on the invoice page
    ]
    clips, prev, total = [], None, 0.0
    for i, seg in enumerate(segs):
        dest = tmp_path / f"s7-{i}.mp4"
        dur, _, _ = assemble.prepare_footage(seg, dest, tmp_path, prev)
        if seg["kind"] == "desktop":
            prev = dest
        v = next(s for s in probe(dest)["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (1920, 930)
        assert v["r_frame_rate"] == "30/1"
        total += dur
        clips.append(dest)
    # 1.5 + (6.0 - 1.0 in - 1.0 cut) + 1.5 = 7.0 seconds, give or take a frame or two.
    assert total == pytest.approx(7.0, abs=0.2)
    joined = tmp_path / "s7.mp4"
    assemble.concat(clips, joined, tmp_path / "s7.txt")
    assert duration(joined) == pytest.approx(total, abs=0.2)


def test_zoom_curve_eases_and_stays_in_frame():
    at = assemble.zoom_curve([[2.0, 5.0, 600, 300, 700, 300]], 8.0)
    z0, *_ = at(0.0)
    zmid, cx, cy = at(3.5)
    zend, *_ = at(7.9)
    assert z0 == 1.0 and zend == pytest.approx(1.0, abs=0.01)
    assert 1.0 < zmid <= assemble.ZOOM_MAX
    assert 0 < cx < 1920 and 0 < cy < 930
    assert at(2.3)[0] < zmid  # still easing in


def test_assert_sandbox_accepts_only_the_sandbox_host():
    record.assert_sandbox(SimpleNamespace(url="https://www.sandbox.paypal.com/checkoutnow?token=x"))
    for bad in ("https://www.paypal.com/checkoutnow", "https://www.sandbox.paypal.com.evil.test/x", "about:blank"):
        with pytest.raises(SystemExit):
            record.assert_sandbox(SimpleNamespace(url=bad))


def test_payer_link_must_be_https_sandbox():
    assert record.check_payer_link("https://www.sandbox.paypal.com/invoice/p/#INV2-1")
    for bad in ("http://www.sandbox.paypal.com/x", "https://www.paypal.com/invoice/p/#1", None, ""):
        with pytest.raises(SystemExit):
            record.check_payer_link(bad)


def test_clean_start_waits_for_the_dim_overlay_to_go(tmp_path):
    dark, bright = tmp_path / "d.mp4", tmp_path / "b.mp4"
    for path, color in ((dark, "0x202020"), (bright, "0xe0e0e0")):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={color}:s=320x180:r=30:d=2",
                        "-pix_fmt", "yuv420p", str(path)], check=True)
    both = tmp_path / "both.mp4"
    assemble.concat([dark, bright], both, tmp_path / "l.txt")
    t = assemble.clean_start(both, 0.0, None)
    assert t is not None and 2.0 <= t <= 2.7
    assert assemble.clean_start(dark, 0.0, None) is None  # never clean: the caller ends on the popup


def test_fix_segments_trims_before_popup_and_skips_dim_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(assemble, "RAW", tmp_path)
    for name, color in (("dim.mp4", "0x202020"), ("ok.mp4", "0xe0e0e0")):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={color}:s=320x180:r=30:d=4",
                        "-pix_fmt", "yuv420p", str(tmp_path / name)], check=True)
    base = {"shot": "S7", "idle": [], "cut": [], "focus": []}
    pre = {**base, "kind": "desktop", "file": "ok.mp4", "in": 0.0, "out": 3.0}
    pop = {**base, "kind": "popup", "file": "ok.mp4", "in": 0.0, "out": 2.0}
    notes: list[str] = []
    fixed = assemble.fix_segments([pre, pop, {**base, "kind": "desktop", "file": "ok.mp4", "in": 0.0, "out": 3.0}], {}, notes)
    assert fixed[0]["out"] == pytest.approx(1.5)  # 3.0 minus BEFORE_POPUP
    assert len(fixed) == 3 and fixed[2]["in"] >= 0.0
    fixed = assemble.fix_segments([pre, pop, {**base, "kind": "desktop", "file": "dim.mp4", "in": 0.0, "out": 3.0}], {}, notes)
    assert len(fixed) == 2  # the dim-overlay clip is dropped; the shot ends on the popup


def test_s8_keeps_only_the_left_column(tmp_path, monkeypatch):
    monkeypatch.setattr(assemble, "RAW", tmp_path)
    make_clip(tmp_path / "s8.mp4", 2, "1920x930")
    seg = {"shot": "S8", "kind": "desktop", "file": "s8.mp4", "in": 0.0, "out": None, "idle": [], "cut": [], "focus": []}
    dest = tmp_path / "out.mp4"
    assemble.prepare_footage(seg, dest, tmp_path, None)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(dest), "-frames:v", "1", str(tmp_path / "f.png")], check=True)
    from PIL import Image
    im = Image.open(tmp_path / "f.png").convert("RGB")
    assert im.getpixel((20, 20)) == pytest.approx((16, 16, 16), abs=3)  # bar beside the column: app background
    assert im.getpixel((960, 465)) != (16, 16, 16)                         # the column itself
