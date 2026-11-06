# Demo video script

Target **2:38**, hard maximum 2:40 (Devpost limit: under 3 minutes). Narration is **294 words** at about 145 words per minute, with short pauses for on-screen actions. The voice is **AI-generated (Gemini TTS)** and is disclosed in the video itself and in the submission. The narration only, one line per shot, is in [`narration.txt`](narration.txt). Captions matching it are in [`demo-captions.srt`](demo-captions.srt). Upload to YouTube as public, with the SRT as the English caption track.

**The story:** the video opens on the decisive moment, a client asking for one more change, and shows within 20 seconds the client's request, the agreed clause, the $80 + $20 = $100 change order with the merch question not billed, and approval. It then shows briefly how the original agreement was formed, then the PayPal path: the change-order invoice created and sent, the buyer-facing invoice with two lines and the agreed terms, payment of that same invoice by the sandbox buyer, and the app reading PAID back. It ends on who it is for and what is real versus sandbox.

**Pitch (on screen in the closing card, verbatim):** "When a client asks for one more change, CreatorMilestone's AI checks the request against the scope both sides agreed to, prices the extras from the artist's rate card, and turns what both approve into a PayPal invoice."

**Shot types:** **LIVE** is recorded in the browser on the hosted app (or localhost). **PAYPAL** is a PayPal sandbox page. **CARD** is a title card made in the editor.

## Timing table

| Shot | Start | End | Words | Narration length | Type | Beat |
|---|---|---|---|---|---|---|
| S1 | 0:00 | 0:20 | 48 | 19.9 s | LIVE | The decisive moment |
| S2 | 0:20 | 0:28 | 16 | 6.6 s | LIVE | Sandbox label, bridge |
| S3 | 0:28 | 0:48 | 39 | 16.1 s | LIVE | How the agreement was formed: intake |
| S4 | 0:48 | 1:01 | 19 | 7.9 s | LIVE | Both sides accept |
| S5 | 1:01 | 1:24 | 42 | 17.4 s | LIVE | Change-order invoice created and sent |
| S6 | 1:24 | 1:42 | 33 | 13.7 s | PAYPAL | Buyer-facing invoice |
| S7 | 1:42 | 1:58 | 17 | 7.0 s | PAYPAL | Sandbox buyer pays the same invoice |
| S8 | 1:58 | 2:12 | 24 | 9.9 s | LIVE | App reads PAID back |
| S9 | 2:12 | 2:38 | 56 | 23.2 s | LIVE + CARD | Who it is for, real versus sandbox |
| **Total** | | **2:38** | **294** | | | |

Narration for each shot starts at the shot's start time. The rest of each window is silent screen action (clicks, page loads, paying). If your cut runs long, trim silent action first, never the narration.

## Shot list

### S1 · 0:00-0:20 · LIVE · The decisive moment

- **Route:** `/projects/:id/messages/new` (Scope Guard result), then `/projects/:id`, then `/c/:token` at 390 px wide.
- **Actions:** Start on the change-order card, with the client's message visible: "a second outfit", "one more pass on the face", "I might use it on merch". Zoom or highlight each row in turn: the outfit marked Out of scope ($80.00), the face edit marked Exceeds limit: 2/2 used ($20.00) with its cited clause, the merch line marked Question, not billed, and the total $100.00. Click Approve. Cut to the client page at phone width and click Approve.
- **On-screen text (burned in, small):** "PayPal sandbox demo". Lower third: "Extra request → agreed clause → $80 + $20 = $100".
- **Footage:** cut from the S5 take (see Recording order). Do not show any loading spinner.
- **Narration:** Jiwoo's agreement allows two revisions. Her client wants a second outfit, one more face edit, and maybe merch use. The AI checks the agreement and prices the extras. Eighty plus twenty is one hundred dollars. Merch is only a question, so it is not billed. Both sides approve.

### S2 · 0:20-0:28 · LIVE · Sandbox label and bridge

- **Route:** `/`
- **Actions:** Landing page with the Sandbox only banner in frame. Click Try the demo.
- **On-screen text:** "PayPal sandbox. No real money." Then "Flashback: how the agreement began."
- **Narration:** This is a PayPal sandbox, so no real money moves. Here is how the agreement began.

### S3 · 0:28-0:48 · LIVE · How the agreement was formed: intake

- **Route:** `/projects/:id/intake`
- **Actions:** Click Use example message, then Analyze (cut the wait, mark the cut). Hover the Revisions field showing Needs confirmation and its highlighted quote "two rounds of revisions" (the app marks it as a guess, not an agreement). Point at usage rights and client email marked Unknown. Scroll to the reply draft with its Korean translation.
- **On-screen text:** "Needs confirmation" and "Unknown" callouts on those fields.
- **Narration:** Jiwoo pastes the client's chat. The AI lists each term with the exact words behind it. Revisions are flagged, because the client only said maybe. Usage rights and email are unknown. It drafts a reply with a Korean translation.

### S4 · 0:48-1:01 · LIVE · Both sides accept

- **Route:** `/projects/:id/intake`, then `/c/:token` at 390 px.
- **Actions:** Click Go to the scope form and plan, click Fill example values, then click Accept scope v1 and share with client. Click Open the client page, switch to the client page at phone width and accept. Show both acceptances ticked.
- **On-screen text:** "Seller accepts" then "Client accepts: scope v1".
- **Narration:** She fills the gaps and accepts. The client accepts on their phone. Now both sides share the same terms.
- **Before S5 (off camera or sped up, no shortcut):** back on the project screen, click **Log a revision** twice. The agreed scope starts at 0 of 2 used; the follow-up only prices the extra revision once 2 of 2 are used, so skipping this changes the $100 result. Then click **Guard the scope** in the step bar (it is available with the deposit unpaid) to open the new-message screen.

### S5 · 1:01-1:24 · LIVE · Change-order invoice created and sent

- **Route:** `/projects/:id`
- **Actions:** Back on the project screen, after both change-order approvals shown in S1 (scope now version 2). Show the Bill card for the change order: recipient, two lines, $100.00 total. Click Approve, show the draft created. Click Send invoice on the send card, show the Sent state and invoice number. Do not touch the deposit card.
- **On-screen text:** "Scope v2" and "Rules compute the amount. Jiwoo approves."
- **Narration:** Back to the change order. Both approved, so the agreement became version two. Rules, not the AI, build the invoice from her rate card, one line per extra. Jiwoo approves, and the backend creates it in PayPal. A second approval sends it.

### S6 · 1:24-1:42 · PAYPAL · Buyer-facing invoice

- **Route:** the invoice's PayPal link (from the Sent state), opened in a private window.
- **Actions:** Show the invoice page: two line items, the total, and the invoice number. Scroll to the note and terms showing the scope version and the agreed terms. Keep the invoice number and the amount in frame, the same as in S5.
- **On-screen text:** "Same invoice: [number]" and "PayPal sandbox page". No PayPal logo used as our branding.
- **Narration:** This is the client's view on PayPal's own page. The extra outfit, eighty dollars. The extra revision, twenty dollars. One hundred in total, and no merch. The agreed terms travel inside the invoice.

### S7 · 1:42-1:58 · PAYPAL · Sandbox buyer pays the same invoice

- **Route:** PayPal sandbox checkout for the same invoice.
- **Actions:** Click Pay. Log in as the sandbox buyer, with the login kept out of frame (cut or blur the email and password fields). Confirm payment. End on PayPal's payment confirmation with the amount.
- **On-screen text:** "Sandbox buyer pays invoice [number], $100.00".
- **Narration:** The sandbox buyer pays this same invoice. The invoice number and amount match the one Jiwoo sent.

### S8 · 1:58-2:12 · LIVE · App reads PAID back

- **Route:** `/projects/:id`
- **Actions:** Return to the app. Click Check PayPal now. Show Paid via PayPal on the change order, and the activity row Status read from PayPal with the same invoice number. Show the final timeline.
- **On-screen text:** "Paid via PayPal. Read back from PayPal."
- **Narration:** Back in the app, PayPal reports the invoice paid. Only then does the app settle the change order. The status is read from PayPal.

### S9 · 2:12-2:38 · LIVE + CARD · Who it is for, real versus sandbox

- **Route:** `/` (landing page, Who it is for), then a title card.
- **Actions:** Hold on the landing page's Who it is for text for about 6 seconds. Cut to the title card. On the card, list two columns while the narration names them: **Real:** Gemini reading the chat, PayPal sandbox invoicing and payment. **Sandbox:** the money and the buyer. Then show the pitch (verbatim, above), the repository URL `<REPOSITORY URL>` and the line "Narration voice: AI-generated (Gemini TTS). Sample art: AI-generated."
- **Narration:** It is for illustrators and character artists who take commissions from clients abroad. Real here: Gemini reading the chat, and PayPal sandbox invoicing and payment. Sandbox: the money and the buyer. Messages are pasted in. The AI fully passed fifteen of twenty test cases, so Jiwoo reviews everything. The voice and sample art are AI generated.

## What the video claims, and the source

| Claim | Source |
|---|---|
| Agreement allows two revisions; $80 outfit + $20 revision = $100; merch is a question, not billed | The follow-up example and Scope Guard output, `design/implementation-screenshots/refined-2/1440-06-change-order-card-a.png` |
| Prices come from the rate card; code computes amounts | README, [`architecture.md`](architecture.md) |
| Fifteen of twenty test cases passed fully | [`ai-eval.md`](ai-eval.md): author-written cases, one run |
| Invoice created, sent, paid by the sandbox buyer, read back PAID | [`paypal-test-log.md`](paypal-test-log.md), 2026-11-05 entries |

## Recording order and rules

1. **Record chronologically in one take**, then assemble in the editor: S1 is built from footage recorded during S5's lead-in (the change-order card, Jiwoo's approval, the client's approval), placed first. S2 to S4 follow, then the rest of S5 to S8 as recorded. Mark every cut and any speed-up (for example a "2x" tag over waiting).
2. **No shortcut.** Do not use **Jump to: deposit paid** or **Jump to: sketch shared** anywhere in the video; log the two revisions by hand. The only payment shown is the change-order invoice created in this take, paid by the sandbox buyer, and read back. Leave the deposit unbilled in the take. Scope Guard needs only an agreed scope.
3. **Verify during the dry run:** the test log records that the two-line change-order invoice's buyer-facing page showed the note, both lines and the terms on 2026-11-06 (`docs/paypal-test-log.md`). Check it again on the actual recording take. If the note and terms are not visible there, cut the last sentence of S6 and its caption, and drop "with the agreed terms" from any copy that describes this invoice.
4. **Cached analysis.** If the "Cached analysis" label appears during the take, re-record, or say on screen that it is a recorded result.
5. **Narration.** Generate it from [`narration.txt`](narration.txt) with Gemini TTS, one line per shot, and place each line at its shot's start time. If the TTS reads a line faster or slower than 145 words per minute, adjust the silent action time, not the words. Numbers are written the way they should be spoken; the text has no symbols to read aloud.
6. **Disclose the AI voice** in the S9 card and in the Devpost text.

## How to record

1. **Prepare.** Open <https://creator-milestone.onrender.com> once about two minutes before recording so the free host is awake. Use a fresh browser profile or a private window with no bookmarks, extensions, or logins. Turn off notifications.
2. **Window size.** Record at a 1440x900 browser viewport, 1920x1080 capture at 100% zoom. For the client page, use device mode at 390 wide and show it as a framed phone-size window.
3. **Capture.** Use the operating system's screen recorder, 1080p, 30 fps, no microphone.
4. **Real footage only.** Everything on screen is the real app or real PayPal sandbox pages. No mockups. Show the Sandbox only banner in the first shot and again when PayPal appears.
5. **Cost control.** The hosted demo limits AI calls and invoices. A take costs two AI analyses (intake, then follow-up) and one invoice. Do a dry run on the local fake (`cd backend && uv run python -m scripts.dev_fake_paypal --judge`), which makes no AI or PayPal calls, then record once on the hosted app. Reserve budget for one retry. Use **Reset** (Start over) only on your own demo project.
6. **Captions.** Upload `demo-captions.srt` to YouTube as an English subtitle file. Check the timing against the final cut and shift all cues if you changed pacing. Optionally burn them in.
7. **Export** at 1080p, MP4 (H.264, AAC), under 2:40. Upload as **Public**, then open the link in a private window to confirm it plays without sign-in.

## Recording checklist

- [ ] Hosted app awake; `/api/health` answers.
- [ ] Clean browser profile, notifications off, no other tabs visible.
- [ ] Sandbox banner visible at the start and when PayPal appears.
- [ ] The sandbox buyer login is **not** visible at any point (masked, cut, or blurred).
- [ ] Only the demo's own sample data on screen (the example messages, `client@example.com`); no real names, emails, or tokens.
- [ ] S6 and S7 show the same invoice number and amount as S5 and S8.
- [ ] The shortcut is not used. If it ever appears, caption it on screen as an earlier sandbox payment that does not pay the current invoice.
- [ ] Client page recorded at phone width (390).
- [ ] No PayPal logo used as our branding; no other third-party logos, trademarks, or footage. No music, or music you own.
- [ ] Sample art, if shown (`design/assets/demo-art/`), is labeled AI-generated.
- [ ] AI-generated narration disclosed on the S9 card.
- [ ] First 20 seconds show: the request, the clause, $80 + $20 = $100, merch not billed, and approval.
- [ ] Total length under 2:40, 1080p, captions uploaded, link public.
- [ ] Video link pasted into the Devpost form.
