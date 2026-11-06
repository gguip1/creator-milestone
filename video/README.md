# Demo video pipeline

Turns `docs/demo-script.md`, `docs/narration.txt` and `docs/demo-captions.srt` into
`out/creator-milestone-demo.mp4` (H.264, 1920x1080, 30 fps, AAC, under 2:50, no music).
Everything on screen is real browser rendering (Chromium via Playwright, device scale factor 1).
The client page is a real 390 px wide recording, composited over a dimmed freeze of the seller screen with a title above it.

## Composition

- The 1920x1080 frame is a 1920x930 app area plus a 150 px black caption band. Nothing is drawn over the app.
- The band holds the captions, one short callout, and small badges: "PayPal sandbox, no real money" (always, right corner),
  "DRAFT: dry run" (dry runs only), "Recorded AI result (saved)" (only when the app itself showed a cached result),
  "Sped up 1.25x" (only when applied) and "Wait cut" (only while a cut wait is on screen).
- The app is rendered at 125% (CSS zoom on `body`, so the cursor is unaffected) so body text reads at 1080p.
- `record.py` notes the box of every element it dwells on; `assemble.py` crop-zooms to it with smoothstep easing
  (up to 1.45x on top of the 125%), frame by frame with sub-pixel crops.
- Narration length sets the shot length. Longer footage is sped up at most 1.25x (labelled); shorter footage holds its last frame.

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
invoice's payer link in a clean private window (S6), pays it as the sandbox buyer (S7), then reads
PAID back in the app (S8). It never uses **Jump to: deposit paid**, never touches the deposit
card, and costs two AI analyses plus one invoice.

How S7 works (structure verified from earlier successful sandbox payments): the invoice page has a cookie
banner (closed first) and a PayPal Buttons iframe titled `PayPal-paypal`. A real mouse click at the iframe's
centre (a DOM click does not work) opens checkout in a **popup**. The popup goes to `/checkoutnow` (login,
only if the pre-login did not carry over) and then `/webapps/hermes` ("Complete Purchase"). The recorder then
clicks Complete Purchase, waits for the popup to close, and waits for the invoice page to say paid. S7 is
composed from three clips: the invoice page up to the click, the popup (its own recording, cropped to the
popup's viewport and shown over a dimmed freeze of the invoice page), and the invoice page afterwards.

Safeguards in the recorder:
- Before typing anything on PayPal it checks the host is exactly `www.sandbox.paypal.com`, on the invoice page
  and on every pass over the popup, and it refuses a payer link on any other host.
- The buyer login happens first in an unrecorded, in-memory browser context, so the email and
  password are never on camera. If the popup still shows a login form it logs in there; the popup clip then
  starts 0.8 s after Complete Purchase appears, and the login span is also in the manifest as a cut. Nothing is written to disk.
- It aborts if the invoice page lacks $100.00, $80.00, $20.00 and the invoice number from S5, and if the checkout
  popup does not show 100.00 before Complete Purchase.
- It aborts if the buyer password text appears on any app page.

Rehearse the whole PayPal path with no network and no PayPal: `record.py --stub-paypal prelogin|popup-login`
(fake runner only) routes `www.sandbox.paypal.com` to local stub pages (`paypal_stub.py`, marked "LOCAL STUB, NOT
PAYPAL") with the same structure. `uv run pytest` runs the composition and host-check tests.

## What the coordinator must watch for

1. **PayPal selectors**: the iframe title, popup flow and button names come from your verified Nov 5 payments and
   run correctly against the stub, but the real pages can differ in detail (popup size, wording). On
   failure the recorder saves `raw/debug-paypal.png`; pay by hand and re-record S8 only if needed.
2. **A verification prompt** at buyer login (captcha, OTP) stops the recorder with a clear message.
3. **"Cached analysis"**: the recorder prints a warning if the label shows in a live take. Re-record.
4. **Note and terms on the PayPal page**: if the recorder prints that they are not found, cut the
   last sentence of S6 and its caption (rule 3 in the script).
5. **Narration**: run `tts.py` before `assemble.py`. Check the pace by ear, especially that the voice
   does not read the style instruction aloud (the fallback model did in testing, so it now gets bare text).
   The Gemini free quota ran out during the dry run (`429`); `tts.py` now stops on a 429. Use a key with quota. Cached shots are never regenerated.
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

## Editor repairs applied automatically (from the first live take)

- A clip before a popup is trimmed by 1.5 s (second cursor over the PayPal iframe, dimmed page, Chrome's debugger
  tooltip); the recorder now ends it about 1 s before the click itself (`pre_popup`).
- The invoice page is shown again only once the dim overlay is gone: `assemble.py` finds the first bright stretch of
  the return clip (the overlay averages about 35 luma, the success state about 160). If it never gets clean, S7 ends
  on the popup and S8 shows PAID. The recorder also waits for "Payment successful" before the return clip starts.
- S6 zooms on whole item cards, then the total (the recorder climbs to the nearest bordered box). For an
  already-recorded take, `video/overrides/<invoice number>.json` can replace a shot's focus boxes
  (`S6_focus`); one exists for the first live take.
- S8 keeps only the left column (milestones and activity log) on the app background, so a stale card in the right
  column never shows (`COLUMN` in `assemble.py`).
- Re-assemble a finished take without re-recording: copy its `raw/*.webm`, `manifest.json` and `run.json` into
  `video/raw/` (keep `raw/tts/`), then `uv run python assemble.py && uv run python check.py`.
