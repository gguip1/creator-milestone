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


AH, BAND = 930, 150  # app area and caption band; the app is never covered


def _layer() -> Image.Image:
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def band_static(path: Path, tags: list[str]) -> None:
    """The one small sandbox badge in the band's right corner; optional small tags in its left corner."""
    img = _layer()
    y = AH + BAND - 44
    sb = chip("PayPal sandbox, no real money", font(18, True), bg=(146, 64, 14, 255), pad=(14, 5))
    img.alpha_composite(sb, (W - sb.width - 24, y))
    x = 24
    for t in tags:
        c = chip(t, font(17, True), bg=(30, 64, 175, 255), pad=(12, 4))
        img.alpha_composite(c, (x, y))
        x += c.width + 8
    img.save(path)


def band_callout(path: Path, text: str) -> None:
    """Short on-screen text, in the band under the app."""
    img = _layer()
    ImageDraw.Draw(img).text((W // 2, AH + BAND - 40), text, font=font(26, True), fill=(252, 211, 77), anchor="ma")
    img.save(path)


def caption(path: Path, text: str) -> None:
    fnt = font(40, True)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrap(probe, text, fnt, 1480)
    img = _layer()
    d = ImageDraw.Draw(img)
    y0 = AH + 14 if len(lines) > 1 else AH + 30
    for i, line in enumerate(lines):
        d.text((W // 2, y0 + i * 48), line, font=fnt, fill=(255, 255, 255), anchor="ma")
    img.save(path)


def tag(path: Path, text: str) -> None:
    """Short-lived small tag in the band, left of the sandbox badge (for 'Wait cut')."""
    img = _layer()
    c = chip(text, font(17, True), bg=(0, 0, 0, 255), pad=(12, 4))
    img.alpha_composite(c, (W - 24 - 270 - c.width, AH + BAND - 44))
    img.save(path)


def _canvas(bg=(15, 23, 42), h: int = 930) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, h), bg)
    return img, ImageDraw.Draw(img)


def phone_background(path: Path, desktop_frame: Path | None, x: int = 1230, y: int = 76) -> None:
    """Dimmed desktop view with a title above the phone slot. The phone itself is composited over it."""
    if desktop_frame and desktop_frame.exists():
        from PIL import ImageEnhance, ImageFilter
        img = Image.open(desktop_frame).convert("RGB").resize((W, AH))
        img = ImageEnhance.Brightness(img.filter(ImageFilter.GaussianBlur(2))).enhance(0.32)
    else:
        img = Image.new("RGB", (W, AH), (24, 28, 38))
    d = ImageDraw.Draw(img)
    cx = x + 195
    title = "The client's phone"
    f = font(32, True)
    tw = d.textlength(title, font=f)
    d.rounded_rectangle((cx - tw / 2 - 28, 14, cx + tw / 2 + 28, 66), radius=26, fill=(17, 24, 39))
    d.text((cx, 22), title, font=f, fill=(255, 255, 255), anchor="ma")
    d.rounded_rectangle((x - 5, y - 5, x + 395, y + 849), radius=14, outline=(148, 163, 184), width=4)
    img.save(path)


def placeholder_card(path: Path, title: str, sub: str) -> None:
    img, d = _canvas((30, 41, 59))
    d.rounded_rectangle((260, 220, W - 260, 700), radius=28, outline=(148, 163, 184), width=3)
    d.text((W // 2, 390), title, font=font(64, True), fill=(255, 255, 255), anchor="ma")
    d.text((W // 2, 510), sub, font=font(36), fill=(203, 213, 225), anchor="ma")
    d.text((W // 2, 600), "Draft only. The final video shows the real PayPal sandbox page here.", font=font(28), fill=(148, 163, 184), anchor="ma")
    img.save(path)


def s9_card(path: Path) -> None:
    img, d = _canvas()
    d.text((W // 2, 40), "CreatorMilestone", font=font(66, True), fill=(255, 255, 255), anchor="ma")
    col_w = 700
    for i, (head, body, color) in enumerate([
        ("Real", "Gemini reading the chat.\nPayPal sandbox invoicing and payment.", (110, 231, 183)),
        ("Sandbox", "The money.\nThe buyer.", (252, 211, 77)),
    ]):
        x = 190 + i * (col_w + 150)
        d.rounded_rectangle((x, 150, x + col_w, 380), radius=20, outline=color, width=3)
        d.text((x + 36, 168), head, font=font(44, True), fill=color)
        for j, line in enumerate(body.split("\n")):
            d.text((x + 36, 240 + j * 52), line, font=font(34), fill=(226, 232, 240))
    fnt = font(36)
    probe = d
    y = 440
    for line in wrap(probe, PITCH, fnt, W - 360):
        d.text((W // 2, y), line, font=fnt, fill=(255, 255, 255), anchor="ma")
        y += 54
    d.text((W // 2, y + 36), f"Repository: {REPO_URL_PLACEHOLDER}", font=font(34, True), fill=(147, 197, 253), anchor="ma")
    d.text((W // 2, AH - 110), "Narration voice: AI-generated (Gemini TTS). Sample art: AI-generated.", font=font(30), fill=(203, 213, 225), anchor="ma")
    img.save(path)


def end_card(path: Path) -> None:
    img, d = _canvas(h=1080)
    d.text((W // 2, 360), "CreatorMilestone", font=font(110, True), fill=(255, 255, 255), anchor="ma")
    d.text((W // 2, 520), "Try it: " + DEMO_URL.removeprefix("https://"), font=font(48), fill=(147, 197, 253), anchor="ma")
    d.text((W // 2, 600), f"Code: {REPO_URL_PLACEHOLDER}", font=font(44), fill=(203, 213, 225), anchor="ma")
    d.text((W // 2, 760), "PayPal sandbox demo — no real money. Narration voice: AI-generated.", font=font(30), fill=(148, 163, 184), anchor="ma")
    img.save(path)
