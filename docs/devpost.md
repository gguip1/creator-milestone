# Devpost submission text (ready to paste)

Project name: **CreatorMilestone**

Tagline (one sentence): When a client asks for one more change, CreatorMilestone's AI checks the request against the scope both sides agreed to, prices the extras from the artist's rate card, and turns what both approve into a PayPal invoice.

Links to enter on Devpost:
- Hosted demo: https://creator-milestone.onrender.com
- Code: https://github.com/gguip1/creator-milestone
- Video: https://youtu.be/5Slk0f7NvUg

Elevator pitch (200 characters max): Catches "just one more change" against the scope both sides agreed to, prices the extras, and turns them into PayPal invoices.

---

## How this differs

Comparisons use each product's public help pages, which we could not all open from a script; we make no claim that any product lacks a feature, and we have not tested with users.

- **PayPal Invoicing alone** already has reminders, status tracking and partial payments. We build on it; we add the step before it, from chat to agreed scope to a matched change order.
- **Commission platforms (VGen, Ko-fi)** offer proposals, milestones and PayPal payments inside their platform. We work with a conversation that happened elsewhere and are not a marketplace.
- **All-in-one tools (Bonsai, HoneyBook)** cover proposals, contracts, invoices and portals, and HoneyBook has AI-assisted invoices. We are narrower: quoted evidence and a priced change order, with no contracts or accounting.
- **ChatGPT plus copy and paste** can read and draft. We add scope versions, client acceptance, a rate card that sets prices in code, seller approval for each PayPal write, and status read back from PayPal.

## The problem

Commission artists already write terms of service to head off "just one more change". Public guides and artists' own pages repeat the same rules: a limited number of revisions, extra fees for additions (for example a flat $60 after one free revision round), commercial use priced separately (for example 1.5x the base price), and a deposit up front. One guide to commission terms names scope creep, ghosting, chargebacks, and surprise usage such as merchandise as the problems those terms are written to prevent. Sources: [Don Corgi](https://doncorgi.com/blog/art-commission-terms-of-service/), [Artists Aware](https://artistsaware.com/art-commissions/sample-tos-detailed/), [cjkkjh](https://www.cjkkjh.com/commissions-terms-and-conditions), [SylviaPaints](https://www.sylviasykesart.com/blog/sample-artist-commission-contract); more in `docs/problem-research.md`.

That shows the structure we model is how artists already work. The gap is that those terms sit in a document the client may not read, while the real agreement happens in a chat, often across languages. When the client later asks for "one more outfit", the artist either does it for free or has the awkward conversation about charging.

**Demand is our hypothesis, not a finding.** We did not interview artists and have no usage or willingness-to-pay data. Scope creep may not be artists' top pain (ghosting, chargebacks, and scams rank alongside it in the same sources, and we prevent none of those), and for very small commissions the extra steps may not be worth it.

We built CreatorMilestone for one person: an artist who wants to be paid fairly for the work they agreed to, without becoming a project manager.

## What it does

CreatorMilestone is a seller-side agent with three stages: Agree, Bill, Guard.

**Agree.** The artist pastes the client's message. The agent extracts the scope (deliverables, formats, deadline, revisions, usage rights, price) and shows where each field came from. Each field is explicit, inferred, needs confirmation, or unknown, with the quote it came from when there is one. The server checks that every quote really appears in the message; that shows where the words came from, not that the reading is right, so the artist reviews each field. It forces hedged wording such as "Maybe two rounds of revisions?" to needs-confirmation whatever the model said. The agent drafts a clarifying reply with a translation for the artist. English and Korean are the tested languages. The artist edits the scope, accepts it, and the client accepts on a mobile-friendly page. Editing the scope later starts a new version and clears both acceptances.

**Bill.** The price is split into milestones (default 30% / 30% / 40%, stored as 3,000 / 3,000 / 4,000 basis points, exact integer math). When a milestone is due, rules propose a PayPal invoice and show it as a card. The artist approves; the backend creates a draft invoice through PayPal Invoicing v2 with the agreed terms inside the invoice note and terms; a second approval sends it. The app reads status back from PayPal, and a milestone counts as settled only when PayPal reports PAID.

**Guard.** When the client later asks for more, the AI compares each request with the agreement, classifies it (in scope, exceeds the revision limit, out of scope, or just a question), cites the clause, and prices the extras from the artist's rate card. The artist gets a change-order proposal with a reply draft. The client approves on their page, which creates scope v2, and rules propose an extra PayPal invoice with one line per extra.

**Safety model.** The AI interprets the request, rules propose the invoice, the artist approves, and the backend calls PayPal. The model is not sent rate-card prices and never calculates invoice amounts; client messages can contain amounts, and the model sees those. It selects rate-card codes and quantities, which the artist reviews. It cannot execute PayPal writes: every charge is computed by code and approved by the artist, and a deterministic validator re-checks it before it runs. A wrong classification could still be approved by a person.

This is a sandbox demo. It is not escrow, buyer protection, or a marketplace. Demo acceptance is a click: it does not verify identity, provide an e-signature, or claim enforceability. Pasted messages are sent to Google's Gemini API.

## How AI is used, and what rules and people do

- **The AI (Google Gemini) reads and drafts.** It reads a pasted client chat into typed scope fields with quotes, drafts the clarifying reply and its translation, and checks a later request against the agreed scope: it classifies each request (in scope, exceeds the limit, out of scope, or a question), cites the clause, and picks a rate-card code and quantity.
- **Rules do the money and the safety.** Code computes every amount from the milestone plan or the artist's rate card, verifies that each quote is in the message, forces hedged wording to needs-confirmation, proposes the invoice, and validates the recipient, amount, and scope version before anything reaches PayPal. The model has no tools and no credentials and is not sent rate-card prices.
- **People decide.** The artist reviews every field and every proposal, both sides accept the scope, the client approves each change order, and the artist approves creating and sending each invoice. The buyer pays.
- The AI can be wrong. In our small labeled evaluation (20 author-written cases, one run) it passed every expectation on 15 and missed one ambiguous extra revision; see `docs/ai-eval.md`.

## How we built it

- **Backend:** Python 3.12 and FastAPI with SQLite. A small, typed event loop with no tool-calling: the LLM is used only where judgment is needed (reading a message, drafting replies, classifying a follow-up); amounts are computed by rules.
- **PayPal:** Invoicing v2 in the sandbox through our own client: OAuth2 token, create draft, send, get status, remind, cancel, and search by invoice number. The agreed scope travels inside `detail.note` and `detail.terms_and_conditions`. A change order is one invoice with one line per extra. Partial payment is off.
- **AI:** Google Gemini (`gemini-3.5-flash-lite`, fallback `gemini-3.1-flash-lite`) with structured JSON output at temperature 0. Client text is passed as marked untrusted input; output is schema-validated and then corrected by server rules.
- **Proposals:** every PayPal write is a typed proposal with an idempotent, atomically claimed approval, staleness detection against the scope version, and a validator that checks recipient, amount, state, and duplicates against our own rows.
- **Frontend:** React, TypeScript, Vite, and Tailwind. One project screen holds the timeline and the agent's waiting card; a separate mobile client page handles acceptance and change-order approval.
- **Judge Mode:** the hosted demo gives each visitor an isolated project and enforces a sandbox recipient allowlist and request and spend limits.
- **Verification:** 472 automated tests (`uv run pytest -q` in `backend/`, fake PayPal and fake LLM, no network), plus real sandbox runs recorded in `docs/paypal-test-log.md`: a sandbox buyer paid both a deposit invoice and a two-line change-order invoice, and the app read both back as PAID.

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

Python, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite, Tailwind CSS, PayPal Invoicing v2 (sandbox), Google Gemini API, Render, Docker, GitHub Actions. Built with the help of Claude Code and Codex. The demo video's narration is AI-generated (Gemini text-to-speech), and the sample art in the demo is AI-generated.

---

## Tools (required: models and AI services, and how each is used)

| Tool | Where | How it is used |
|---|---|---|
| Google Gemini API: `gemini-3.5-flash-lite` (default), `gemini-3.1-flash-lite` (fallback) | In the product, backend only | Reads a pasted client message into typed fields with quotes; drafts the clarifying reply and the translation; classifies a follow-up message against the agreed scope and drafts the reply. It has no tools and no PayPal access, is not sent rate-card prices, never calculates invoice amounts (messages it reads may contain amounts), and its output is validated and corrected by server rules. |
| PayPal Invoicing v2 REST API and OAuth2 (sandbox) | In the product, backend only | Creates, sends, reads, reminds, and cancels invoices; the agreed terms are embedded in each invoice. Sandbox only. |
| Claude Code (Anthropic models) | Development | AI coding agent that wrote much of the code and tests under the owner's direction. Credited as co-author on 30 commits. |
| Codex (OpenAI) | Development | AI coding agent, credited on one commit. |
| Orca (multi-agent IDE) | Development | Coordinated the coding agents. |
| Google Gemini text-to-speech | Demo video | Generated the video's voice-over from the script in `docs/narration.txt`. The narration is AI-generated, not a human voice, and the video and this submission say so. |
| OpenAI built-in image generation | Demo content | Generated the three AI-generated sample illustrations (a finished piece, a sketch, and a variation) used as demo artwork in `design/assets/demo-art/`. Prompts are in that folder's README. |
| Pencil (`.pen` design files) | Design | The UI design source in `design/`. |

The product decisions, the trust model, and the choice of what the AI may and may not do are the owner's.

---

## Testing instructions

**Hosted demo (no setup):** open https://creator-milestone.onrender.com. It runs on a free host and can take about a minute to wake on the first visit. It is PayPal sandbox only; no real money moves.

1. Click **Try the demo**. You get your own isolated project.
2. On the intake screen, click **Use example message**, then **Analyze**. Review the evidence, the flagged terms, and the reply draft. (If the free AI tier is unavailable, the screen shows a "Cached analysis" label and serves a recorded result for this example message.)
3. Quick path: on the intake or project screen, click the Judge Mode shortcut **Jump to: deposit paid** (or **Jump to: sketch shared**, which also logs the two revisions). It fills sample terms, records both acceptances, and reuses an earlier sandbox payment; it does not pay the current invoice. It does not fake PayPal state: the backend asks PayPal and shows "Paid via PayPal" only if that invoice reads PAID for the deposit amount. Full path without the shortcut: click **Go to the scope form and plan**, **Fill example values**, **Accept scope v1 and share with client**; click **Open the client page** and **Accept scope v1** there; return to the project screen.
4. On the project screen click **Log a revision** twice (skip this if you used **Jump to: sketch shared**), then click **Guard the scope** in the step bar. It is available as soon as the scope is agreed, even with the deposit unpaid. Click **Use example message 2**, then **Check against scope**, and review the change-order card. Click **Review change order #1**, then **Approve**. Click **Open** next to the client link and **Approve change order** there (works on a phone-width window).
5. To see real PayPal billing, click **Approve** on the "Bill change order #1" card, then **Send invoice**. This creates a real sandbox invoice and is limited per visitor and per day. Open the invoice's PayPal link and pay with the sandbox buyer below. The app shows "Paid via PayPal" after PayPal reports PAID; click **Check PayPal now** if you do not want to wait for polling.

**Sandbox buyer login (PayPal sandbox only):**
- Email: `<SANDBOX BUYER LOGIN>`
- Password: `<SANDBOX BUYER PASSWORD>`
- Log in at https://www.sandbox.paypal.com when the invoice page asks. Use a private window if you are signed in to a real PayPal account.

**Run it yourself:** see the README. `docker compose up --build` or `uv` plus `npm`, with a sandbox REST app that has Invoicing enabled and a non-Korean sandbox buyer. Tests: `cd backend && uv run pytest -q` (472 passed).

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
