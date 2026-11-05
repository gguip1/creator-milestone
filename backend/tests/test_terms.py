"""The buyer-facing terms text: exact wording, clean punctuation, and PayPal's length limit."""

from app.services.invoices import NOTE_LIMIT, invoice_terms
from tests.conftest import bill_and_send
from tests.test_change_orders import post_message

V2_TERMS = (
    "Agreed scope v2: VTuber debut illustration. "
    "Deliverables: One full-body illustration; Extra outfit. "
    "File formats: PNG, PSD. Revisions included: 3. "
    "Usage rights: Personal streaming. Delivery by: 2026-11-25."
)


async def test_scope_v2_terms_use_the_rate_card_name_and_no_double_period(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    project = await bill_and_send(api, project["id"])
    posted = await post_message(api, project)
    co_id = posted["change_order"]["id"]
    await api.post(f"/api/proposals/{posted['proposal']['id']}/approve")
    await api.post(f"/api/c/{project['share_token']}/change-orders/{co_id}/approve")

    project = await api.get(f"/api/projects/{project['id']}")
    bill = next(
        p
        for p in project["proposals"]
        if p["kind"] == "BILL_MILESTONE" and p["status"] == "PENDING"
    )
    assert bill["payload"]["terms_and_conditions"] == V2_TERMS
    assert ".." not in bill["payload"]["terms_and_conditions"]
    await api.post(f"/api/proposals/{bill['id']}/approve")
    remote = list(fake_paypal.invoices.values())[-1]
    assert remote["detail"]["terms_and_conditions"] == V2_TERMS


def test_terms_normalize_trailing_punctuation_and_whitespace():
    terms = invoice_terms(
        {
            "version": 1,
            "title": "Portrait. ",
            "deliverables": ["Add a second outfit..", "  Sketch ;"],
            "file_formats": ["PNG."],
            "revisions_included": 0,
            "usage_rights": "Personal use.",
            "deadline_date": None,
        }
    )
    assert terms == (
        "Agreed scope v1: Portrait. Deliverables: Add a second outfit; Sketch. "
        "File formats: PNG. Revisions included: 0. Usage rights: Personal use."
    )


def test_terms_stay_within_paypals_text_limit():
    terms = invoice_terms(
        {"version": 3, "title": "T", "deliverables": ["x" * 300] * 30, "file_formats": []}
    )
    assert len(terms) == NOTE_LIMIT == 4000
