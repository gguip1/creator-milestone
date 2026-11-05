# Demo video script

Target length **2:40**, hard maximum 2:50 (Devpost limit: under 3 minutes). Narration is timed at about 140 words per minute (about 2:39 with short pauses; re-time after any wording change). Captions matching it word for word are in [`demo-captions.srt`](demo-captions.srt). Upload to YouTube as public, with the SRT as the English caption track.

**What the video must make clear:** the problem (vague requests, free extras, payment chasing), who it is for (independent artists with clients abroad), why it matters (they get paid for the work they agreed to), and that it works end to end (agreement, real PayPal sandbox invoices, status read back from PayPal, scope creep caught and billed).

Screen actions are written against the flow and routes, not exact button labels or colors, because the UI is still being polished. Re-read each step against the live app before recording.

## Shot list and narration

| Time | Route | On screen | Narration (word for word) |
|---|---|---|---|
| 0:00-0:20 | `/` | **Problem.** Landing page. Hold on the headline, then the three-step strip (Agree, Bill, Guard). | Jiwoo is an illustrator in Seoul. Her client is a VTuber abroad. Requests arrive vague, extra work creeps in for free, and chasing each payment is awkward. Each of those costs her money or time. CreatorMilestone is an AI back office for artists like her. |
| 0:20-0:30 | `/` | **Rule.** Click Try the demo. Point at the sandbox banner. | The rule is simple: AI reads the request, rules propose the invoice, Jiwoo approves, and the backend calls PayPal. This is the PayPal sandbox, so no real money moves. |
| 0:30-0:54 | `/projects/:id/intake` | **Agree: intake.** Click Paste example, then Analyze. Hover the flagged revisions field, then scroll to the reply draft with its Korean translation. | She pastes the client's message. Every field shows where it came from. The agent lists every term with the exact words it relied on. Revisions are flagged, because the client only said maybe. Usage rights and the client's email are unknown. It drafts a reply in English, with a Korean translation for her. |
| 0:54-1:02 | `/projects/:id/intake, then /c/:token` | **Agree: accept.** Fill the missing fields, accept as seller. Switch to the client page at phone width and accept. | She fills the gaps and accepts. The client accepts on their phone. Now both sides share the same terms. |
| 1:02-1:18 | `/projects/:id` | **Bill.** Show the Bill deposit card. Click Approve, then Approve on the send card. | Rules propose the deposit invoice. The amount comes from the milestone plan, not from the model. Jiwoo approves, and the backend creates a PayPal invoice with the agreed terms inside it, then sends it. |
| 1:18-1:34 | `/projects/:id` | **Paid.** Open the invoice's PayPal link, pay as the sandbox buyer (keep the login out of frame), then show Paid via PayPal on the deposit and the activity row Status read from PayPal. | The sandbox buyer pays this invoice on PayPal's page, and PayPal reports it paid. Only then does the app settle the milestone. |
| 1:34-2:02 | `/projects/:id/messages/new` | **Guard.** Click Paste example, run Scope Guard, then show the change-order card: evidence rows, rate-card amounts, total. | Then the client asks for more: a second outfit, one more face revision, and maybe merch use. Scope Guard checks the agreement. The outfit is out of scope. The face edit exceeds the two included revisions. Merch is only a question, so it is not billed. Extras are priced from Jiwoo's rate card, a hundred dollars total. Code sets the price; Jiwoo reviews it. |
| 2:02-2:08 | `/projects/:id, then /c/:token` | **Change order.** Approve the card. Open the client page at phone width and approve the change order. | Jiwoo approves, and the client approves on their page. That creates scope version two. |
| 2:08-2:16 | `/projects/:id` | **Second invoice.** Show the change-order bill card with two lines. Approve, then approve send. Show the sent state. | Rules propose a second invoice, one line per extra. Jiwoo approves, and it goes out through PayPal. |
| 2:16-2:39 | `/projects/:id` | **Close.** Show the final timeline, then cut to the title card with the repository URL. | Gemini reads and drafts. Rules compute the money. A validator checks every PayPal write, and automated tests pass. The AI is checked on a small labeled set, with its misses published. Sandbox only, messages are pasted, one seller account. Every claim here is in the repository, with a log of real sandbox calls. CreatorMilestone: get paid for the work you agreed to. |

Architecture frame: during the Close segment, cut for about 6 seconds to the architecture diagram from the README (the Mermaid chart as rendered on GitHub), pointing at the line between the model and PayPal. If time is tight, drop the sentence "Sandbox only, messages are pasted, one seller account." from the narration and the SRT; do not drop the limits from the Devpost text.

### Quick path for judges: the shortcut (not the recorded flow)

PRD rule: show PAID only if it happened in that session. The recorded video should pay the newly created deposit invoice for real, as above. The **Jump to: deposit paid** shortcut is only the judges' quick path in the hosted demo. It reuses an earlier sandbox payment and does not pay the current invoice. If it ever appears on camera, put a caption on screen and say: "To save time, a shortcut reuses an earlier sandbox payment. It does not pay this invoice." Never present it as payment of the current invoice.

## How to record

1. **Prepare.** Open <https://creator-milestone.onrender.com> once about two minutes before recording so the free host is awake. Use a fresh browser profile or a private window with no personal bookmarks, extensions, or logins. Turn off notifications.
2. **Window size.** Record the app at 1440x900 browser viewport so the project screen fits without scrolling (1920x1080 capture at 100% zoom with the browser window sized accordingly). For the client page, use the browser's device mode at 390 wide, and rescale in the edit; show it as a framed phone-size window.
3. **Capture.** Use the operating system's screen recorder (macOS: Cmd+Shift+5, record selected portion) or any recorder you own. Record 1080p, 30 fps, with no microphone while capturing screen actions.
4. **Real footage only.** Everything on screen must be the real app in a real browser. No mockups. Show the "Sandbox only" banner in the first shot and again when PayPal appears.
5. **Narration.** Record the voice separately from the narration column, one segment at a time, in a quiet room, at a natural pace. About 140 words per minute is a normal speaking rate. Then align each segment to its screen action in the editor, trimming dead time (loading, typing) with clearly marked cuts or a speed-up marked "2x".
6. **Cost control.** The hosted demo limits AI calls and invoices. A take costs two AI analyses (intake, then follow-up) and, if you bill live, two invoices. Do a dry run on the local fake (`cd backend && uv run python -m scripts.dev_fake_paypal --judge`), which makes no AI or PayPal calls, then record once on the hosted app. Use **Reset** (Start over) only on your own demo project.
7. **Captions.** Upload `demo-captions.srt` to YouTube as an English subtitle file; check the timing against your final cut and shift all cues if you changed pacing. Optionally burn them in.
8. **Export** at 1080p, MP4 (H.264, AAC), under 3:00. Upload to YouTube as **Public**, then open the link in a private window to confirm it plays without sign-in.

## Recording checklist

- [ ] Hosted app awake; `/api/health` answers.
- [ ] Browser: clean profile, no personal data, notifications off, no other tabs visible.
- [ ] Sandbox banner visible at the start and when PayPal appears.
- [ ] The sandbox buyer login is **not** visible on screen at any point (password fields masked, no screenshots of credentials).
- [ ] Only the demo's own sample data on screen (the example messages, `client@example.com`); no real names, emails, or tokens.
- [ ] PayPal invoice page shown with the agreed terms in the note and terms, and the buyer paying that same invoice (matching invoice number and amount).
- [ ] "Paid via PayPal" shown only for an invoice paid in that session. If the shortcut is used, label it on screen as an earlier sandbox payment that does not pay the current invoice.
- [ ] Client page recorded at phone width (390).
- [ ] No PayPal logo used as our branding; PayPal appears only as the product's own pages and text. No other third-party logos, trademarks, or footage.
- [ ] No music, or music you own or have a license for. Narration only is fine.
- [ ] If the AI shows the "Cached analysis" label during the take, re-record, or say that it is a recorded result.
- [ ] If sample art is shown (`design/assets/demo-art/`), it is labeled AI-generated.
- [ ] Total length under 2:50, 1080p, captions uploaded, link public.
- [ ] Video link pasted into the Devpost form.
