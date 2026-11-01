# CreatorMilestone

Your AI back office for cross-border freelance work. It turns messy client chats into agreed scope, guards that scope, and bills every stage through PayPal.
**The agent proposes, you approve, PayPal executes.**

Built for the PayPal AI Hackathon 2026. Sandbox only. No real money moves.

> Status: early skeleton. The PayPal sandbox smoke test (Gate A) runs first, and the product UI comes after it. See [`docs/PRD.md`](docs/PRD.md).

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
