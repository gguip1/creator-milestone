# PayPal Sandbox Test Log

Evidence of real calls against the PayPal sandbox (`https://api-m.sandbox.paypal.com`).
Entries are appended by `backend/scripts/paypal_smoke_test.py --write-log`.
Tokens are never logged; emails are masked.

## Environment

- Seller sandbox account: Business, Korea (inferred from the `KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED` error)
- Buyer sandbox account: Personal, United States
- REST app: sandbox, default features

## Findings

- 2026-11-03: OAuth succeeds, but the token has no invoicing scope (26 scopes, none containing `invoicing`). `GET /v2/invoicing/invoices`, `POST /v2/invoicing/generate-next-invoice-number`, and draft creation all return `403 NOT_AUTHORIZED`. Cause: Invoicing was not enabled on the sandbox app.
- 2026-11-03: After enabling Invoicing, PayPal kept returning the same cached token without the scope. Revoking it with `POST /v1/oauth2/token/terminate` produced a new token with 27 scopes including invoicing. `GET /v2/invoicing/invoices` then returned 200.
- 2026-11-03: Draft creation works, and `note` and `terms_and_conditions` come back on GET. Sending fails with `406 MEDIA_TYPE_NOT_ACCEPTABLE`, issue `KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED`. PayPal documents that Korean accounts cannot transact with each other.
- 2026-11-04: With a US sandbox buyer and the same seller, send, remind, and cancel all succeed (14/14 smoke steps). 
- 2026-11-04: **Gate A passed.** The sandbox buyer paid invoice `INV2-78WJ-HT2J-UYNV-XNG2`. `GET` returned `status: PAID`, `due_amount: 0.00`, `paid_amount: 90.00`, and one `PAYPAL` transaction with `transaction_status: SUCCESS`. The owner confirmed that the note and terms appeared on the buyer-facing page.
- 2026-11-04: `payments.transactions[].payment_date_time` read `05:10:49Z`, about 8 hours before the invoice's `first_sent_time` of `13:08:46Z`. Do not treat this field as reliable UTC; order events by our own sync time.
- 2026-11-04: Send returns a single link object: `{href, rel: "payer-view", method}`. Search by invoice number found exactly one invoice after the rejected duplicate create.
- 2026-11-03: Repeating a create with the same `PayPal-Request-Id` and invoice number returned `422 DUPLICATE_INVOICE_NUMBER` instead of replaying the invoice. Retry recovery must handle this error and look the invoice up by number.
- 2026-11-03: `POST /v2/invoicing/invoices/{id}/cancel` on a draft returns `422 CANNOT_CANCEL_DRAFT_INVOICE`.
- 2026-11-05: **Full product flow verified live** through the app's HTTP API with real Gemini and the real sandbox: analyze, scope, both acceptances, deposit draft and send (`INV2-7QWT-H5G2-TH3P-U3U7`), Scope Guard ($100.00 total), both change-order approvals, scope v2, change-order draft and send with two lines (`INV2-PGQS-4XMX-4SPB-YKMV`). Both read back as SENT. Driven by script, not through the browser UI.

## Smoke run 20261103140847 (UTC)

| Step | Result | Detail |
|---|---|---|
| oauth token | PASS | access token issued (not logged) |
| create A (deposit) | FAIL | HTTP 403 NOT_AUTHORIZED: Authorization failed due to insufficient permissions. [NOT_AUTHORIZED] (debug_id f773521225f32) |
| create B (change order, 2 lines) | FAIL | HTTP 403 NOT_AUTHORIZED: Authorization failed due to insufficient permissions. [NOT_AUTHORIZED] (debug_id f320313bad1f9) |
| create C (cancel test) | FAIL | HTTP 403 NOT_AUTHORIZED: Authorization failed due to insufficient permissions. [NOT_AUTHORIZED] (debug_id f9688370aa79d) |

## Smoke run 20261104130840 (UTC)

| Step | Result | Detail |
|---|---|---|
| oauth token | PASS | access token issued (not logged) |
| create A (deposit) | PASS | id=INV2-78WJ-HT2J-UYNV-XNG2 status=DRAFT |
| duplicate create | PASS | rejected with DUPLICATE_INVOICE_NUMBER |
| search by invoice number | PASS | 1 match(es) |
| get A after create | PASS | status=DRAFT note=True terms=True |
| send A | PASS | payer link returned |
| get A after send | PASS | status=SENT note=True terms=True |
| create B (change order, 2 lines) | PASS | id=INV2-WP33-S7TN-3N4V-53RV status=DRAFT |
| send B | PASS | payer link returned |
| remind B | PASS | reminder accepted |
| create C (cancel test) | PASS | id=INV2-MGFP-KW3A-WR6V-8A7B status=DRAFT |
| send C | PASS | payer link returned |
| cancel C | PASS | cancel accepted |
| get C after cancel | PASS | status=CANCELLED note=False terms=False |

Invoice object top-level keys observed:

- create A (deposit): `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
- get A after create: `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
- get A after send: `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
- create B (change order, 2 lines): `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
- create C (cancel test): `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
- get C after cancel: `amount, configuration, detail, due_amount, id, invoicer, items, links, primary_recipients, settings, status, unilateral`
