# Demo video pipeline

Turns `docs/demo-script.md`, `docs/narration.txt` and `docs/demo-captions.srt` into
`out/creator-milestone-demo.mp4` (H.264, 1920x1080, 30 fps, AAC, under 2:50, no music).
Everything on screen is real browser rendering (Chromium via Playwright, device scale factor 1).
The client page is a real 390 px wide page, shown in a phone-sized frame.

`raw/` (footage, narration audio) and `out/` (video, frames) are git-ignored. Never commit them.

## Setup (once)

```sh
brew install ffmpeg            # needs ffmpeg and ffprobe on PATH
cd video
uv sync
uv run playwright install chromium
```

This ffmpeg build has no `drawtext` or `subtitles` filter, so labels, captions and cards are drawn
with Pillow and composited with `overlay`. Fonts come from macOS system fonts (`cards.py`).

## Files

| File | Job |
|---|---|
| `record.py` | Drives the app through every shot; one recording per segment, `raw/manifest.json` records idle waits to trim and spans to cut |
| `tts.py` | Gemini TTS, one WAV per shot in `raw/tts/`, cached |
| `assemble.py` | Fits footage to narration, overlays, captions, end card, final MP4 and soft-sub MP4 |
| `check.py` | Duration, resolution, audio, frame grab per shot in `out/frames/` |

## Dry run (fake runner, no AI, no PayPal)

```sh
# terminal 1: build the frontend once, then start the fake
(cd ../frontend && npm ci && npm run build)
(cd ../backend && uv run python -m scripts.dev_fake_paypal --judge --port 8765)

# terminal 2, in video/
uv run --env-file /path/to/backend/.env python tts.py        # at most 15 API calls, cached
uv run python record.py --base-url http://127.0.0.1:8765
uv run python assemble.py
uv run python check.py
```

The dry run refuses any non-local `--base-url`. S6 and S7 are placeholder cards ("PayPal page
recorded in live take"); the buyer's payment is simulated through the fake's `/dev/pay`. The
draft carries a "DRAFT" tag and a "Recorded AI result" tag (the fake serves the saved analysis).
A shot with no valid narration audio is silent, with its length estimated, and tagged.

## Live final take

Needs the hosted demo awake (open it and check `/api/health` two minutes before), the narration
generated, and these environment variables (never printed or logged):

| Variable | Use |
|---|---|
| `DEMO_BUYER_EMAIL` | sandbox buyer login |
| `DEMO_BUYER_PASSWORD` | sandbox buyer password |
| `LLM_API_KEY` | Gemini TTS key, only for `tts.py` |

```sh
export DEMO_BUYER_EMAIL=... DEMO_BUYER_PASSWORD=...
uv run python record.py --live --base-url https://creator-milestone.onrender.com
uv run python assemble.py
uv run python check.py
```

What `--live` does beyond the dry run: it creates a new change-order invoice (S5), opens that
invoice's payer link in a clean private window, pays it as the sandbox buyer (S6, S7), then reads
PAID back in the app (S8). It never uses **Jump to: deposit paid**, never touches the deposit
card, and costs two AI analyses plus one invoice.

Safeguards in the recorder:
- Before typing anything on PayPal it checks the host is exactly `www.sandbox.paypal.com`, and it
  refuses a payer link on any other host.
- The buyer login happens first in an unrecorded, in-memory browser context, so the email and
  password are never on camera. If the recorded page still shows a login form, it logs in there and
  the editor removes that span. Nothing is written to disk.
- It aborts if the PayPal page does not show $100.00, $80.00 and $20.00 and the invoice number from S5.
- It aborts if the buyer password text appears on any app page.

## What the coordinator must watch for

1. **PayPal selectors are untested.** The PayPal steps (Pay button, login ids `#email`, `#password`,
   `#btnNext`, `#btnLogin`, confirmation wording) were written from PayPal's usual page structure and
   could not be run without real PayPal calls. Rehearse S6/S7 once and read the recorder's output. On
   failure it saves `raw/debug-paypal.png`; pay by hand and re-record S8 only if needed.
2. **A verification prompt** at buyer login (captcha, OTP) stops the recorder with a clear message.
3. **"Cached analysis"**: the recorder prints a warning if the label shows in a live take. Re-record.
4. **Note and terms on the PayPal page**: if the recorder prints that they are not found, cut the
   last sentence of S6 and its caption (rule 3 in the script).
5. **Narration**: run `tts.py` before `assemble.py`. Check the pace by ear, especially that the voice
   does not read the style instruction aloud (the fallback model did in testing, so it now gets bare text).
   The Gemini free quota ran out during the dry run (`429`); use a key with quota.
6. **Fit**: read the table `assemble.py` prints. A shot needing more than 1.5x is flagged "does not fit";
   shorten that shot's holds in `record.py` rather than letting it run long. Sped-up and cut spans are
   labelled on screen.
7. **Captions** are retimed by text length across each shot's narration, not by forced alignment.
   Upload `out/captions.srt` to YouTube; `creator-milestone-demo-softsubs.mp4` is the same video
   without burned captions and with the SRT as a track.
8. **Placeholders to replace**: the repository URL on the S9 and end cards is `<REPOSITORY URL>`
   (`common.py`, `REPO_URL_PLACEHOLDER`).
9. Watch every frame in `out/frames/`: no secrets, no real names or emails, no third-party marks.
10. Upload as Public and open the link in a private window.
