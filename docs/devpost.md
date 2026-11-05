# Devpost submission text (ready to paste)

Project name: **CreatorMilestone**

Tagline (one sentence): An AI back office for independent artists with clients abroad: it turns a messy client chat into an agreed scope, catches scope creep against it, and bills each stage with PayPal invoices that the artist approves.

Links to enter on Devpost:
- Hosted demo: https://creator-milestone.onrender.com
- Code: the public repository URL (owner fills in)
- Video: the public YouTube URL (owner fills in)

---

## How this differs

Comparisons use each product's public help pages, which we could not all open from a script; we make no claim that any product lacks a feature, and we have not tested with users.

- **PayPal Invoicing alone** already has reminders, status tracking and partial payments. We build on it; we add the step before it, from chat to agreed scope to a matched change order.
- **Commission platforms (VGen, Ko-fi)** offer proposals, milestones and PayPal payments inside their platform. We work with a conversation that happened elsewhere and are not a marketplace.
- **All-in-one tools (Bonsai, HoneyBook)** cover proposals, contracts, invoices and portals, and HoneyBook has AI-assisted invoices. We are narrower: quoted evidence and a priced change order, with no contracts or accounting.
- **ChatGPT plus copy and paste** can read and draft. We add scope versions, client acceptance, a rate card that sets prices in code, seller approval for each PayPal write, and status read back from PayPal.

## Inspiration

Independent digital artists (illustrators, character designers, VTuber asset makers) take commissions from clients in other countries. The client writes in another language and sends a vague request. Scope, revisions, usage rights, and payment terms stay unclear until work has started. Midway, the client asks for "one more outfit" or "one more pass on the face". The artist either works for free or avoids the awkward conversation about charging. Then they chase each stage payment by hand.

We built CreatorMilestone for that one person: an artist who wants to be paid fairly for the work they agreed to, without becoming a project manager.

## What it does

CreatorMilestone is a seller-side agent with three stages: Agree, Bill, Guard.

**Agree.** The artist pastes the client's message. The agent extracts the scope (deliverables, formats, deadline, revisions, usage rights, price) and shows where each field came from. Each field is explicit, inferred, needs confirmation, or unknown, with the quote it came from when there is one. The server checks that every quote really appears in the message; that shows where the words came from, not that the reading is right, so the artist reviews each field. It forces hedged wording such as "Maybe two rounds of revisions?" to needs-confirmation whatever the model said. The agent drafts a clarifying reply with a translation for the artist. English and Korean are the tested languages. The artist edits the scope, accepts it, and the client accepts on a mobile-friendly page. Editing the scope later starts a new version and clears both acceptances.

**Bill.** The price is split into milestones (default 30% / 30% / 40%, stored as 3,000 / 3,000 / 4,000 basis points, exact integer math). When a milestone is due, rules propose a PayPal invoice and show it as a card. The artist approves; the backend creates a draft invoice through PayPal Invoicing v2 with the agreed terms inside the invoice note and terms; a second approval sends it. The app reads status back from PayPal, and a milestone counts as settled only when PayPal reports PAID.

**Guard.** When the client later asks for more, the AI compares each request with the agreement, classifies it (in scope, exceeds the revision limit, out of scope, or just a question), cites the clause, and prices the extras from the artist's rate card. The artist gets a change-order proposal with a reply draft. The client approves on their page, which creates scope v2, and rules propose an extra PayPal invoice with one line per extra.

**Safety model.** The AI interprets the request, rules propose the invoice, the artist approves, and the backend calls PayPal. The model is not sent rate-card prices and never calculates invoice amounts; client messages can contain amounts, and the model sees those. It selects rate-card codes and quantities, which the artist reviews. It cannot execute PayPal writes: every charge is computed by code and approved by the artist, and a deterministic validator re-checks it before it runs. A wrong classification could still be approved by a person.

This is a sandbox demo. It is not escrow, buyer protection, or a marketplace. Demo acceptance is a click: it does not verify identity, provide an e-signature, or claim enforceability. Pasted messages are sent to Google's Gemini API.

## How we built it

- **Backend:** Python 3.12 and FastAPI with SQLite. A small, typed event loop with no tool-calling: the LLM is used only where judgment is needed (reading a message, drafting replies, classifying a follow-up); amounts are computed by rules.
- **PayPal:** Invoicing v2 in the sandbox through our own client: OAuth2 token, create draft, send, get status, remind, cancel, and search by invoice number. The agreed scope travels inside `detail.note` and `detail.terms_and_conditions`. A change order is one invoice with one line per extra. Partial payment is off.
- **AI:** Google Gemini (`gemini-3.5-flash-lite`, fallback `gemini-3.1-flash-lite`) with structured JSON output at temperature 0. Client text is passed as marked untrusted input; output is schema-validated and then corrected by server rules.
- **Proposals:** every PayPal write is a typed proposal with an idempotent, atomically claimed approval, staleness detection against the scope version, and a validator that checks recipient, amount, state, and duplicates against our own rows.
- **Frontend:** React, TypeScript, Vite, and Tailwind. One project screen holds the timeline and the agent's waiting card; a separate mobile client page handles acceptance and change-order approval.
- **Judge Mode:** the hosted demo gives each visitor an isolated project and enforces a sandbox recipient allowlist and request and spend limits.
- **Verification:** 471 automated tests (`uv run pytest -q` in `backend/`, fake PayPal and fake LLM, no network), plus real sandbox runs recorded in `docs/paypal-test-log.md`: a sandbox buyer paid both a deposit invoice and a two-line change-order invoice, and the app read both back as PAID.

## Challenges we ran into

- **PayPal Invoicing wasn't enabled, and the token was cached.** Calls returned 403 until Invoicing was enabled on the sandbox app, and PayPal kept returning the old token until we revoked it.
- **Korean to Korean is impossible.** Our seller account is Korean. PayPal rejects sends between two Korean accounts, so the demo uses a Korean seller and a US buyer, which matches the product's cross-border purpose.
- **Retrying a create does not replay.** A repeat with the same request ID returned `DUPLICATE_INVOICE_NUMBER`, so we use a stable invoice number and look the invoice up by it.
- **LLMs smooth over hedging.** The model returned "2 revisions" for "Maybe two rounds of revisions?" every time, sometimes labeled explicit. We added a deterministic hedge rule that overrides it.
- **A free AI tier and a free host.** We built caps, a recorded analysis for the two demo messages (always labeled), and a cold-start notice instead of hiding either limit.

## Accomplishments that we're proud of

- A real end-to-end flow in the PayPal sandbox: two invoices created, sent, paid by a sandbox buyer, and read back as PAID.
- A design that limits what the AI can do: it cannot execute PayPal writes, amounts and recipients are computed or checked by code, and the seller approves each charge. A wrong classification could still be approved by a person.
- Evidence you can check: quotes are verified to appear in the source text, clauses are cited, and prices come from the artist's own rate card. Whether a quote supports the model's reading is for the artist to judge.
- A small published evaluation of the AI layer (20 labeled cases, with failures listed): `docs/ai-eval.md`.
- The test log records what worked and what did not, including limits we did not verify.

## What we learned

- With money, split the work cleanly: the model reads and writes language, code decides amounts and states.
- A good agent shows its evidence and waits for a human on irreversible steps.
- PayPal sandbox behavior (scopes, caching, country restrictions, duplicate handling) is worth testing against the real API early.

## What's next

Planned, not built:
- Email or chat integration so messages need not be pasted.
- PayPal webhooks (today the app polls).
- Real authentication for multiple sellers.
- Optional electronic signature for scope acceptance.
- Other cross-border freelancers beyond commission artists.

## Built with

Python, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, PayPal Invoicing v2 (sandbox), Google Gemini API, Render, Docker, GitHub Actions. Built with the help of Claude Code and Codex.

---

## Tools (required: models and AI services, and how each is used)

| Tool | Where | How it is used |
|---|---|---|
| Google Gemini API: `gemini-3.5-flash-lite` (default), `gemini-3.1-flash-lite` (fallback) | In the product, backend only | Reads a pasted client message into typed fields with quotes; drafts the clarifying reply and the translation; classifies a follow-up message against the agreed scope and drafts the reply. It has no tools and no PayPal access, is not sent rate-card prices, never calculates invoice amounts (messages it reads may contain amounts), and its output is validated and corrected by server rules. |
| PayPal Invoicing v2 REST API and OAuth2 (sandbox) | In the product, backend only | Creates, sends, reads, reminds, and cancels invoices; the agreed terms are embedded in each invoice. Sandbox only. |
| Claude Code (Anthropic models) | Development | AI coding agent that wrote much of the code and tests under the owner's direction. Credited as co-author on 30 commits. |
| Codex (OpenAI) | Development | AI coding agent, credited on one commit. |
| Orca (multi-agent IDE) | Development | Coordinated the coding agents. |
| OpenAI built-in image generation | Demo content | Generated the three AI-generated sample illustrations (a finished piece, a sketch, and a variation) used as demo artwork in `design/assets/demo-art/`. Prompts are in that folder's README. |
| Pencil (`.pen` design files) | Design | The UI design source in `design/`. |

The product decisions, the trust model, and the choice of what the AI may and may not do are the owner's.

---

## Testing instructions

**Hosted demo (no setup):** open https://creator-milestone.onrender.com. It runs on a free host and can take about a minute to wake on the first visit. It is PayPal sandbox only; no real money moves.

1. Click **Try the demo**. You get your own isolated project.
2. On the intake screen, press **Paste example**, then **Analyze**. Review the evidence, the flagged terms, and the reply draft. (If the free AI tier is unavailable, the screen shows a "Cached analysis" label and serves a recorded result for this example message.)
3. For a quick path, on the project screen use **Jump to: deposit paid**. It fills sample terms, records both acceptances, and reuses an earlier sandbox payment; it does not pay the current invoice. It does not fake PayPal state: the backend asks PayPal and shows "Paid via PayPal" only if that invoice reads PAID for the deposit amount.
4. Go to **New message**, use the follow-up example, and run Scope Guard. Review the change-order card. Use **Open** next to the client page link to approve as the client (works on a phone-width window).
5. To see real PayPal billing, approve the bill card, then the send card. This creates a real sandbox invoice and is limited per visitor and per day. Open the invoice's PayPal link and pay with the sandbox buyer below. The app shows "Paid via PayPal" after PayPal reports PAID; use the refresh control if you do not want to wait for polling.

**Sandbox buyer login (PayPal sandbox only):**
- Email: `<SANDBOX BUYER LOGIN>`
- Password: `<SANDBOX BUYER PASSWORD>`
- Log in at https://www.sandbox.paypal.com when the invoice page asks. Use a private window if you are signed in to a real PayPal account.

**Run it yourself:** see the README. `docker compose up --build` or `uv` plus `npm`, with a sandbox REST app that has Invoicing enabled and a non-Korean sandbox buyer. Tests: `cd backend && uv run pytest -q` (471 passed).

**Known limits:** demo acceptance does not verify identity or provide an e-signature; messages are pasted, not integrated; one seller account; Korean-to-Korean PayPal transactions are not possible; the deposit shortcut reuses an earlier sandbox payment and does not pay the current invoice; only English and Korean were tested; the free host may take about a minute to wake; the free AI tier can return recorded demo analyses, which are labeled.

---

## Gallery shot list

Images in `design/implementation-screenshots/` (1440 wide for the app, 390 for phone views). Devpost shows them in the order uploaded. These were captured before the final visual refresh: **re-capture after the dark theme lands if the look changed**, keeping the same states.

| # | File | Caption | Shows |
|---|---|---|---|
| 1 | `1440/13-project-change-order.png` | The agent caught scope creep and priced it from the rate card | Hero: Scope Guard card with quotes, clauses, rate-card amounts, "Not billed" for a question, and the Approve button |
| 2 | `1440/03-intake-analyzed.png` | Every field shows its evidence; unclear terms are flagged | Intake: provenance chips, highlighted quotes, English reply with Korean translation |
| 3 | `1440/08-project-bill-card.png` | Rules propose the invoice; the artist approves | Bill card with recipient, amount, terms version |
| 4 | `1440/11-project-paid.png` | PayPal reports the deposit paid | "Paid via PayPal" status read back from PayPal |
| 5 | `390/06-client-accept-390.png` | The client accepts the scope on their phone | Mobile client page |
| 6 | `390/15-client-change-order-390.png` | The client approves the extras | Change-order approval on mobile |
| 7 | `1440/17-project-bill-co.png` | The change order becomes a PayPal invoice | Bill card for the change order |
| 8 | `1440/19-project-final.png` | Final state of the project | Timeline after both invoices |
| 9 | `1440/18-project-send-failed.png` | Failures are shown plainly, with PayPal's code | Failed send state and retry |
| 10 | `judge/02-visitor-b-cannot-see-a.png` | Each visitor gets an isolated sandbox project | Judge Mode isolation |

Also available: `1440/01-landing.png` (landing), `1440/21-client-final-390.png` (client final), `polish/04-activity-reused-1440.png`, `polish/02-korean-intake-1440.png` (Korean client message). Also `design/assets/demo-art/final.png`, `sketch.png`, `hoodie.png` are AI-generated sample art; if shown, caption them as such.

Thumbnail: use image 1 cropped to 3:2.
