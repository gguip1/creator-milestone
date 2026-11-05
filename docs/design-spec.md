# CreatorMilestone design spec

Source: `design/creator-milestone.pen`. PNG exports (2x): `design/screenshots/`.

**Rule of the system:** blue marks the decision in front of the user. A 2px blue card border means "the agent is waiting for you", and nothing else gets one. Every status has an icon and text, never color alone.

## Frames and routes

| Frame name | Frame id | Route | Screenshot |
|---|---|---|---|
| 00 Component sheet | `hsips` | none (reference) | `00-component-sheet.png` |
| 01 Project main — /projects/:id | `YYd0u` | `/projects/:id` | `01-project-main.png`, card only: `01-scope-guard-card.png` (card id `NOktg`) |
| 02 Bill proposal states — /projects/:id agent panel | `VTzle` | `/projects/:id`, agent panel states | `02-bill-proposal-states.png` |
| 03 Intake and review — /projects/:id/intake | `MEcZM` | `/projects/:id/intake` | `03-intake-review.png` |
| 04a Client page, accept scope — /c/:token | `HZ95M` | `/c/:token`, before acceptance | `04a-client-accept.png` |
| 04b Client page, change order approval — /c/:token | `s7BVGx` | `/c/:token`, change order waiting | `04b-client-change-order.png` |
| 04c Client page, change order approved — /c/:token | `y8kEA` | `/c/:token`, after approval | `04c-client-approved.png` |
| 05 Landing — / | `sK8f2` | `/` | `05-landing.png` |

Not designed: `/projects/:id/messages/new` and `/settings`. Reuse the app header, the card style and the components below.

## Color tokens

Add to `@theme` in `frontend/src/index.css` as `--color-<name>`.

| Token | Hex | Use |
|---|---|---|
| paper | `#FAF7F2` | Page background (existing) |
| paper-deep | `#F3EEE5` | Bands, insets |
| surface | `#FFFFFF` | Cards, inputs |
| ink | `#1F2328` | Text, demo banner background (existing) |
| muted | `#5F636A` | Secondary text. **Darker than the current `#6b6f76`, for video legibility** |
| line | `#E7E2D9` | Dividers, quiet card borders (existing) |
| line-strong | `#8F897E` | Input and secondary button borders, timeline rail |
| accent | `#2563EB` | Primary button, waiting-card border (existing) |
| accent-deep | `#1D4ED8` | Agent text, pressed primary |
| accent-soft | `#E8EFFD` | Waiting chip, Agent tag |
| success / success-soft | `#1B6B45` / `#E3F1E8` | Paid via PayPal, explicit provenance |
| warn / warn-soft | `#8A5200` / `#FBEFD5` | Flags, missing fields, billable verdicts |
| danger / danger-soft | `#A92F25` / `#FBE8E4` | Failed, blocked |
| neutral / neutral-soft | `#4A4E55` / `#EFEBE3` | Everything else, disabled buttons |

## Type tokens

Google Fonts. Minimum size is 13px, and only for small labels; body text starts at 14.

| Role | Font | Size |
|---|---|---|
| Display, titles, section heads | Newsreader 500 | 36 to 68, 24 to 30 |
| Client quotes | Newsreader italic | 17 to 18 |
| UI and body | Instrument Sans 400/600 | 13 to 18 (mobile body 16) |
| Money, invoice numbers, PayPal codes, times | IBM Plex Mono 500/600 | 13 to 42 |
| Korean | Noto Sans KR | 16, line height 1.6 |

## Spacing and shape

- Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.
- Page gutter: 40 in the app, 64 on landing, 16 on mobile.
- Radius: chip 6, input and button 8, small card 10, proposal card 14.

## Components

**Chip:** icon 15 + label 14/600, padding 5/10, tones neutral, accent, success, warn, danger. Exact labels are on frame 00.

PayPal status labels (PRD 11.3):

| PayPal status | Label | Tone |
|---|---|---|
| DRAFT | Draft (not sent) | neutral |
| SCHEDULED | Scheduled | neutral |
| SENT / UNPAID | Sent — awaiting payment | neutral |
| PAYMENT_PENDING | Payment pending | neutral |
| PARTIALLY_PAID | Partially paid (unexpected; partial disabled) | warn |
| PAID | Paid via PayPal | success, the only green PayPal status |
| MARKED_AS_PAID | Marked paid (outside PayPal) | neutral, deliberately not green |
| CANCELLED | Cancelled | neutral |
| REFUNDED, PARTIALLY_REFUNDED, MARKED_AS_REFUNDED | Refunded | warn |
| other | Unknown (raw value shown), with the actual raw value in the label | neutral |

**Button:** primary (blue), secondary (white, line-strong border), ghost (muted text). Padding 12/20, label 16/600. Pending and blocked use neutral-soft with neutral text, and the reason sits nearby. Use `loader-circle` for pending and `lock` for blocked. Icons are lucide.

**Proposal card**, top to bottom:
1. Kicker: who proposed and which rule or check fired.
2. Title and exact amount, amount in mono. Amounts come from the backend only.
3. Status chip.
4. Why: one sentence.
5. Facts or evidence. Bill: recipient, amount, currency, terms version (send step adds the invoice number). Change order: evidence table and total row with a 2px ink rule.
6. Reply draft inset (change order only).
7. Actions: Approve, Edit, Dismiss, plus a note on what happens next.

| Proposal state | Border | Chip | Actions |
|---|---|---|---|
| PENDING | accent 2px | Waiting for your approval | Approve, Edit, Dismiss |
| APPROVED, running | line 1px | Working | Disabled button with progress text |
| EXECUTED | success 1.5px | The PayPal status chip | Open PayPal invoice |
| FAILED | danger 1.5px | Failed | Plain-language message, raw PayPal code below, Edit recipient, Try again |
| Blocked by validation | danger 1.5px | Blocked: <reason> | Edit scope |
| STALE | line 1px | Outdated | Dismiss only |
| DISMISSED | removed from panel | Dismissed (activity log) | None |

Compact decided row (frame 01, "Earlier"): title, one-line detail, amount, chip.

**Evidence row:** columns client quote 220, verdict chip + clause (fill), rate card 144, amount 84 right-aligned. Non-billed rows show "Not billed" in UI text, never $0.00.

**Provenance:** Explicit (success, `quote`), Inferred (neutral, `lightbulb`), Needs confirmation (warn, `flag`), Unknown (warn, `circle-help`). Message highlights use the same tone plus a numbered marker that matches the field row. Needs confirmation also gets a 2px warn border and a flag icon.

**Cached-analysis label:** neutral chip "Cached analysis" + "The AI service is unavailable, so this is a saved result for the demo message." Show it whenever the fallback served the result.

**Demo banner:** ink band on every route, reading "Sandbox only — no real money". The Judge Mode links "Jump to: deposit paid" and "Jump to: sketch shared" appear on the project screen only.

**Actor tag:** Agent, Seller, Client, PayPal, 84 wide, icon + text. The PayPal tag is outlined with plain text. No PayPal logo anywhere.

## Responsive

- 1440 is the reference. Project main's proposal card ends near y=845, so it fits a 1440×900 recording without scrolling. Protect this.
- Project main: below about 1100, stack the agent panel above the timeline.
- Evidence table on narrow widths: stack each row, as the item rows do on 04b.
- Intake: paired columns stack below about 1000. The EN and KO reply columns stack last.
- Client page: single column at 390, full-width buttons, banner shows the notice title only.
- The message highlights in the frame use manual line breaks. Build them with inline `<mark>` spans so they wrap naturally.

## Sample values, not product data

These must come from the backend or seed: `client@example.com`, `CM-demo-deposit-1` (real format `CM-<project>-<milestone>-<attempt>`), "VTuber client", and activity log times.

## Open points

- **Deadline provenance:** PRD 5 expects "around November 25" to be inferred, but the PRD 4 P0 rule marks any "around" quote unconfirmed. The design shows Inferred, following PRD 5, with the reply asking the client to confirm. Align the rule or the label before recording.
- **One pending card on frame 01:** in the seeded state the sketch is shared but not approved, so no sketch invoice proposal is valid yet.
- **Client total on frame 04c:** assumes scope v2 total = $300.00 + $100.00 = $400.00.
