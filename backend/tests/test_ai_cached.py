"""Fallback behavior, exercised against the real recordings in app/agent/cached/."""

import json
from datetime import date

import pytest

from app.agent import cached, llm
from app.agent.intake import analyze_intake
from app.agent.scope_guard import guard_scope
from app.config import Settings
from app.schemas.ai import LLMUnavailableError, RateCardEntry
from tests.fixtures.ai_demo import (
    DEMO_MESSAGE_1,
    DEMO_MESSAGE_2,
    DEMO_RATE_CARD,
    FakeProvider,
    demo_scope,
    unavailable,
)

TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
def every_model_down(monkeypatch):
    monkeypatch.setattr(llm, "BACKOFF_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(_env_file=None, llm_model="gemini-3.5-flash-lite", llm_api_key="k"),
    )
    llm.set_provider(FakeProvider([unavailable() for _ in range(6)]))
    yield
    llm.set_provider(None)


async def test_intake_recording_is_returned_labeled_cached():
    analysis = await analyze_intake(DEMO_MESSAGE_1, today=TODAY)
    assert analysis.source == "cached"
    assert analysis.model_id is not None
    assert analysis.budget_minor_units == 30_000
    assert analysis.revisions.needs_confirmation is True
    assert analysis.usage_rights.provenance == "unknown"
    assert "$90.00" in analysis.reply_draft_client


async def test_intake_match_ignores_whitespace_and_case():
    noisy = "  " + DEMO_MESSAGE_1.upper().replace(" ", "\n  ") + "\n"
    analysis = await analyze_intake(noisy, today=TODAY)
    assert analysis.source == "cached"


async def test_changed_intake_message_does_not_match():
    with pytest.raises(LLMUnavailableError):
        await analyze_intake(DEMO_MESSAGE_1 + " Also a hat.", today=TODAY)


async def test_scope_guard_recording_matches_the_prd():
    result = await guard_scope(
        DEMO_MESSAGE_2, scope=demo_scope(), rate_card=DEMO_RATE_CARD, today=TODAY
    )
    assert result.source == "cached"
    assert [item.classification for item in result.items] == [
        "out_of_scope",
        "exceeds_limit",
        "question",
    ]
    assert [item.amount_minor_units for item in result.items] == [8_000, 2_000, None]
    assert result.total_minor_units == 10_000
    assert all(item.quote_verified for item in result.items)
    assert "merch" in result.reply_draft_client
    assert "$100.00" in result.reply_draft_client
    assert "{{" not in result.reply_draft_client


async def test_scope_guard_recording_stores_no_amounts():
    payload = json.loads(cached.SCOPE_GUARD_FILE.read_text(encoding="utf-8"))
    assert "{{PRICE_1}}" in payload["client_draft"]
    assert "$" not in payload["client_draft"]
    assert "$" not in payload["seller_draft"]
    assert all("amount_minor_units" not in item for item in payload["items"])


async def test_scope_guard_prices_are_recomputed_from_the_given_rate_card():
    card = [
        RateCardEntry(code="O", name="Extra outfit", unit_price_minor_units=9_500),
        RateCardEntry(code="R", name="Extra revision", unit_price_minor_units=2_500),
        RateCardEntry(code="L", name="Commercial license add-on", unit_price_minor_units=10_000),
    ]
    result = await guard_scope(DEMO_MESSAGE_2, scope=demo_scope(), rate_card=card, today=TODAY)
    assert result.source == "cached"
    assert [item.rate_card_code for item in result.items] == ["O", "R", "L"]
    assert result.total_minor_units == 12_000
    assert "$95.00" in result.reply_draft_client
    assert "$25.00" in result.reply_draft_client
    assert "$120.00" in result.reply_draft_client
    assert "$80.00" not in result.reply_draft_client


async def test_scope_guard_rules_rerun_when_the_scope_changed():
    result = await guard_scope(
        DEMO_MESSAGE_2,
        scope=demo_scope(revisions_used=1),
        rate_card=DEMO_RATE_CARD,
        today=TODAY,
    )
    assert result.source == "cached"
    assert result.items[1].classification == "in_scope"
    assert result.items[1].billable is False
    assert result.total_minor_units == 8_000
    # The recorded prose described a billed revision, so it must not be reused.
    assert "$20.00" not in result.reply_draft_client
    assert "$100.00" not in result.reply_draft_client
    assert "$80.00" in result.reply_draft_client


async def test_item_missing_from_the_rate_card_needs_a_price():
    card = [entry for entry in DEMO_RATE_CARD if entry.name != "Extra outfit"]
    result = await guard_scope(DEMO_MESSAGE_2, scope=demo_scope(), rate_card=card, today=TODAY)
    assert result.items[0].needs_price is True
    assert result.items[0].amount_minor_units is None
    assert result.total_minor_units == 2_000
    assert "$80.00" not in result.reply_draft_client


async def test_changed_scope_guard_message_does_not_match():
    with pytest.raises(LLMUnavailableError):
        await guard_scope(
            DEMO_MESSAGE_2 + " Also a hat.",
            scope=demo_scope(),
            rate_card=DEMO_RATE_CARD,
            today=TODAY,
        )
