"""Pillow renderers for everything the editor draws: labels, lower thirds, captions, cards.

This ffmpeg build has no drawtext/subtitles filter, so text is rendered to transparent PNGs
here and composited with the overlay filter.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import DEMO_URL, H, PITCH, REPO_URL_PLACEHOLDER, W

FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in (BOLD_CANDIDATES if bold else []) + FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def chip(text: str, fnt, fg=(255, 255, 255), bg=(17, 24, 39, 215), pad=(18, 10)) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(probe.textlength(text, font=fnt)) + pad[0] * 2
    h = fnt.size + pad[1] * 2 + 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2 if h < 60 else 14, fill=bg)
    d.text((pad[0], pad[1]), text, font=fnt, fill=fg)
    return img


def static_overlay(path: Path, lower: str | None, extra_tags: list[str] | None = None) -> None:
    """Full-frame overlay for a whole shot: sandbox label top right, optional tags top left."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sb = chip("PayPal sandbox — no real money", font(24, True), bg=(146, 64, 14, 235))
    img.alpha_composite(sb, (W - sb.width - 28, 24))
    y = 24
    for tag in extra_tags or []:
        t = chip(tag, font(24, True), bg=(30, 64, 175, 235))
        img.alpha_composite(t, (28, y))
        y += t.height + 10
    img.save(path)


def lower_third(path: Path, text: str) -> None:
    fnt = font(34, True)
    c = chip(text, fnt, bg=(17, 24, 39, 225), pad=(26, 14))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(c, (60, H - 250 - c.height))
    img.save(path)


def caption(path: Path, text: str) -> None:
    fnt = font(40, True)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrap(probe, text, fnt, W - 360)
    lh = 52
    box_w = max(int(probe.textlength(line, font=fnt)) for line in lines) + 56
    box_h = lh * len(lines) + 28
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = (W - box_w) // 2, H - 60 - box_h
    d.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=14, fill=(0, 0, 0, 205))
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=fnt)
        d.text(((W - lw) / 2, y0 + 14 + i * lh), line, font=fnt, fill=(255, 255, 255))
    img.save(path)


def tag(path: Path, text: str) -> None:
    """Small label near the top, used for 'Sped up 1.3x' and 'Wait cut'."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    c = chip(text, font(26, True), bg=(0, 0, 0, 215))
    img.alpha_composite(c, (W - c.width - 28, 24 + 52 + 10))
    img.save(path)


def _canvas(bg=(15, 23, 42)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), bg)
    return img, ImageDraw.Draw(img)


def phone_background(path: Path) -> None:
    img, d = _canvas((24, 28, 38))
    d.text((W // 2, 40), "Client's phone (390 px wide, real page)", font=font(28, True), fill=(203, 213, 225), anchor="ma")
    img.save(path)


def placeholder_card(path: Path, title: str, sub: str) -> None:
    img, d = _canvas((30, 41, 59))
    d.rounded_rectangle((260, 300, W - 260, 780), radius=28, outline=(148, 163, 184), width=3)
    d.text((W // 2, 470), title, font=font(64, True), fill=(255, 255, 255), anchor="ma")
    d.text((W // 2, 590), sub, font=font(36), fill=(203, 213, 225), anchor="ma")
    d.text((W // 2, 680), "Draft only. The final video shows the real PayPal sandbox page here.", font=font(28), fill=(148, 163, 184), anchor="ma")
    img.save(path)


def s9_card(path: Path) -> None:
    img, d = _canvas()
    d.text((W // 2, 70), "CreatorMilestone", font=font(66, True), fill=(255, 255, 255), anchor="ma")
    col_w = 760
    for i, (head, body, color) in enumerate([
        ("Real", "Gemini reading the chat.\nPayPal sandbox invoicing and payment.", (110, 231, 183)),
        ("Sandbox", "The money.\nThe buyer.", (252, 211, 77)),
    ]):
        x = 200 + i * (col_w + 200)
        d.rounded_rectangle((x, 190, x + col_w, 430), radius=20, outline=color, width=3)
        d.text((x + 36, 212), head, font=font(44, True), fill=color)
        for j, line in enumerate(body.split("\n")):
            d.text((x + 36, 290 + j * 52), line, font=font(34), fill=(226, 232, 240))
    fnt = font(36)
    probe = d
    y = 500
    for line in wrap(probe, PITCH, fnt, W - 360):
        d.text((W // 2, y), line, font=fnt, fill=(255, 255, 255), anchor="ma")
        y += 54
    d.text((W // 2, y + 36), f"Repository: {REPO_URL_PLACEHOLDER}", font=font(34, True), fill=(147, 197, 253), anchor="ma")
    d.text((W // 2, H - 120), "Narration voice: AI-generated (Gemini TTS). Sample art: AI-generated.", font=font(30), fill=(203, 213, 225), anchor="ma")
    d.text((W // 2, H - 70), "PayPal sandbox — no real money", font=font(26, True), fill=(252, 211, 77), anchor="ma")
    img.save(path)


def end_card(path: Path) -> None:
    img, d = _canvas()
    d.text((W // 2, 360), "CreatorMilestone", font=font(110, True), fill=(255, 255, 255), anchor="ma")
    d.text((W // 2, 520), "Try it: " + DEMO_URL.removeprefix("https://"), font=font(48), fill=(147, 197, 253), anchor="ma")
    d.text((W // 2, 600), f"Code: {REPO_URL_PLACEHOLDER}", font=font(44), fill=(203, 213, 225), anchor="ma")
    d.text((W // 2, 760), "PayPal sandbox demo — no real money. Narration voice: AI-generated.", font=font(30), fill=(148, 163, 184), anchor="ma")
    img.save(path)
