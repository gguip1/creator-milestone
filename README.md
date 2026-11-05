# CreatorMilestone

Your AI back office for cross-border commission work. It turns messy client chats into agreed scope, guards that scope, and bills every stage through PayPal.
**The agent proposes, you approve, PayPal executes.**

Built for the PayPal AI Hackathon 2026. Sandbox only. No real money moves.

> Status: early skeleton. The PayPal sandbox flow is verified end to end ([test log](docs/paypal-test-log.md)); the product UI is next. See [`docs/PRD.md`](docs/PRD.md).
>
> PayPal does not allow transactions between two Korean accounts, so use a sandbox buyer from another country if your seller account is Korean.

## Repository layout

```text
backend/    FastAPI service, PayPal Invoicing v2 client, smoke test, tests
frontend/   React + TypeScript + Vite + Tailwind single-page app
docs/       PRD, PayPal sandbox test log
```

The backend serves the built frontend and the API on one origin.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 24+
- A [PayPal Developer](https://developer.paypal.com/) account with:
  - a **sandbox REST app** (client ID + secret)
  - a sandbox **Business** account (seller) and a sandbox **Personal** account (buyer)

## Setup

```bash
cp backend/.env.example backend/.env   # fill in the PayPal sandbox values
cd backend && uv sync
cd ../frontend && npm install
```

## Run

```bash
# Development: API on :8000, Vite dev server on :5173 (proxies /api)
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# Single origin: build the SPA, then the backend serves it
cd frontend && npm run build
cd backend && uv run uvicorn app.main:app --port 8000
```

## PayPal sandbox smoke test (Gate A)

This test makes real calls to the PayPal sandbox:

1. Gets an OAuth token.
2. Creates a draft invoice with the agreed terms in `note` and `terms_and_conditions`.
3. Checks that `PayPal-Request-Id` makes create idempotent.
4. Sends the invoice and reads its status back.
5. Sends a two-line change-order invoice, then a reminder for it.
6. Sends a third invoice and cancels it.

Use `--wait-for-payment` to also wait until the sandbox buyer pays.

```bash
cd backend
uv run python -m scripts.paypal_smoke_test
uv run python -m scripts.paypal_smoke_test --wait-for-payment 600 --write-log
```

Output is sanitized: tokens are never printed and emails are masked. With `--write-log`, a summary is appended to [`docs/paypal-test-log.md`](docs/paypal-test-log.md).

## Tests

```bash
cd backend && uv run pytest -q && uv run ruff check .
cd frontend && npm run build
```

## License

[MIT](LICENSE)

## Judge Mode (the hosted demo)

`JUDGE_MODE=true` turns the app into the public demo:

- **Per-visitor projects.** Each browser gets a signed, HttpOnly, SameSite=Lax cookie and its own seeded project, rate card, and activity. `POST /api/demo/reset` resets only that visitor. Another visitor's project, milestone, invoice, or proposal answers 404. The client page (`/c/:token`) stays reachable by its unguessable token.
- **Seeded on demand.** Nothing is pre-seeded, so a restart or redeploy (free hosts lose local files) is harmless: `GET /api/demo/session` seeds a project for a visitor who has none, and the UI offers "Open my demo project" when a link points at a project that is gone.
- **Sandbox only.** The recipient is preset to the configured sandbox buyer, and the recipient allowlist is enforced when billing.
- **Skip-ahead links** ("Jump to: deposit paid", "Jump to: sketch shared") never fake PayPal state. They fill sample terms and record both acceptances, then adopt the real, already paid sandbox invoice named by `DEMO_PAID_INVOICE_ID`: the backend asks PayPal live and shows "Paid via PayPal" only if PayPal returns `PAID` with this deposit's amount. Otherwise the project stays in its plain state and the normal billing card still works.
- **Limits** (in memory, one instance): per-visitor and per-IP request rates, per-visitor and per-IP AI rates, a per-visitor and a **global daily cap on AI requests** (past the cap the two demo messages are served from recorded analysis, anything else gets a clear 503), invoice creation per visitor per hour and globally per day, and a 64 KB request-body cap on top of per-field length limits. Answers are `429` (or `503` for the global AI cap) in the usual `{code, message, request_id}` shape. The client IP is taken from the entry our own proxy appended to `X-Forwarded-For` (`TRUSTED_PROXY_HOPS`, default 1), never from entries a client put in front, and the global caps are the backstop if that is still gamed. Defaults live in `app/config.py` (`LIMIT_*`).

### Settings for the hosted instance

| Setting | Purpose |
|---|---|
| `JUDGE_MODE=true` | Turns all of the above on |
| `RECIPIENT_ALLOWLIST`, `PAYPAL_SANDBOX_BUYER_EMAIL` | Sandbox buyer(s) that may be billed; the first preset |
| `SESSION_SECRET` | Signs the visitor cookie. Optional: blank generates a random secret each boot, so a restart only gives visitors a fresh project |
| `DEMO_BUYER_EMAIL`, `DEMO_BUYER_PASSWORD` | Display-only sandbox buyer login in the banner. Set in the host dashboard, never committed. Unset, the banner says the login is in the submission's testing instructions |
| `DEMO_PAID_INVOICE_ID` | A real paid sandbox invoice for the deposit shortcut (amount must equal the deposit, $90.00 of the $300 sample) |

### Cold start

Render's free instance sleeps after 15 idle minutes and takes about a minute to wake; it also loses local files on restart. There is deliberately no keep-alive ping, which the host's terms do not allow. While the server wakes, the UI shows a calm "waking up" notice and retries by itself for about 95 seconds instead of showing an error. Open the URL once before judging.

The database schema comes from `create_all` and there are no migrations: after pulling this change, delete any local `creatormilestone.db`.
