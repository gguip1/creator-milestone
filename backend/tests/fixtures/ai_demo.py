"""Seeded demo data from PRD section 5, plus a fake provider so tests never touch the network."""

import json
from collections.abc import Callable
from typing import Any

from app.agent.llm import ProviderError
from app.schemas.ai import RateCardEntry, ScopeContext

DEMO_MESSAGE_1 = (
    "Hi! I need a full-body illustration of my original character for my VTuber debut, "
    "transparent PNG plus layered PSD, around November 25. I'd like a sketch review before "
    "coloring. My budget is USD 300. Maybe two rounds of revisions? Please let me know how "
    "payment works."
)
DEMO_MESSAGE_2 = (
    "Love the sketch!! Could you also add a second outfit, maybe a casual hoodie version? And "
    "can we do one more pass on the face? Also I might use it on merch later."
)

DEMO_RATE_CARD = [
    RateCardEntry(
        code="BASE_ILLUSTRATION", name="Full-body illustration base", unit_price_minor_units=30_000
    ),
    RateCardEntry(code="EXTRA_OUTFIT", name="Extra outfit", unit_price_minor_units=8_000),
    RateCardEntry(code="EXTRA_REVISION", name="Extra revision", unit_price_minor_units=2_000),
    RateCardEntry(
        code="COMMERCIAL_LICENSE", name="Commercial license add-on", unit_price_minor_units=10_000
    ),
]


def demo_scope(*, revisions_used: int = 2, revisions_included: int = 2) -> ScopeContext:
    return ScopeContext(
        scope_version=1,
        title="Full-body VTuber illustration",
        deliverables=["One full-body illustration of the client's original character"],
        file_formats=["Transparent PNG", "Layered PSD"],
        revisions_included=revisions_included,
        revisions_used=revisions_used,
        deadline="2026-11-25",
        usage_rights="Personal streaming use",
    )


def raw_field(value: Any = None, provenance: str = "unknown", quote: str = "") -> dict[str, Any]:
    return {"value": value, "provenance": provenance, "quote": quote}


def raw_intake(**overrides: Any) -> dict[str, Any]:
    """What a well-behaved model returns for message 1, overridable per test."""
    payload = {
        "source_language": "en",
        "title": raw_field(
            "Full-body VTuber illustration",
            "inferred",
            "full-body illustration of my original character",
        ),
        "deliverables": [
            raw_field(
                "Full-body illustration",
                "explicit",
                "full-body illustration of my original character",
            )
        ],
        "file_formats": [
            raw_field("Transparent PNG", "explicit", "transparent PNG"),
            raw_field("Layered PSD", "explicit", "layered PSD"),
        ],
        "deadline": raw_field("2026-11-25", "inferred", "around November 25"),
        "revisions": raw_field("2", "inferred", "Maybe two rounds of revisions?"),
        "usage_rights": raw_field(),
        "budget": raw_field("USD 300", "explicit", "My budget is USD 300"),
        "client_email": raw_field(),
        "sketch_review_requested": raw_field(
            "yes", "explicit", "I'd like a sketch review before coloring"
        ),
        "other_questions": [],
    }
    return {**payload, **overrides}


def raw_item(
    summary: str,
    quote: str,
    classification: str,
    *,
    clause_ref: str | None = None,
    code: str | None = None,
    quantity: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "request_summary": summary,
        "summary_ko": f"{summary} (ko)",
        "quote": quote,
        "classification": classification,
        "clause_ref": clause_ref,
        "rate_card_code": code,
        "quantity": quantity,
        **extra,
    }


def raw_guard(*items: dict[str, Any], source_language: str = "en") -> dict[str, Any]:
    return {"source_language": source_language, "items": list(items)}


def raw_message_2() -> dict[str, Any]:
    """A correct model answer for message 2."""
    return raw_guard(
        raw_item(
            "Add a second outfit.",
            "Could you also add a second outfit, maybe a casual hoodie version?",
            "out_of_scope",
            clause_ref="deliverables",
            code="EXTRA_OUTFIT",
        ),
        raw_item(
            "One more revision pass on the face.",
            "can we do one more pass on the face?",
            "exceeds_limit",
            clause_ref="revisions",
            code="EXTRA_REVISION",
        ),
        raw_item(
            "Possible merch use later.",
            "I might use it on merch later",
            "question",
            clause_ref="usage_rights",
            code="COMMERCIAL_LICENSE",
        ),
    )


GOOD_INTAKE_REPLY = {
    "reply_draft_client": (
        "Thank you! I have your budget of {{BUDGET}}. You suggested two revisions and a deadline "
        "of November 25; could you confirm the date and the revision count? I suggest 30% "
        "deposit ({{DEPOSIT}}), 30% at sketch approval ({{SKETCH}}), and 40% at final delivery "
        "({{FINAL}}). "
        "How will you use the art, and which email should get the invoices?"
    ),
    "reply_draft_seller_translation": (
        "감사합니다! 예산 {{BUDGET}} 확인했습니다. 수정 횟수와 마감 날짜를 확인 부탁드립니다. "
        "결제는 30% ({{DEPOSIT}}), 30% ({{SKETCH}}), 40% ({{FINAL}})로 제안드립니다. "
        "사용 범위와 청구서 이메일도 알려 주세요."
    ),
}
GOOD_GUARD_REPLY = {
    "reply_draft_client": (
        "Thank you! The extra outfit is {{PRICE_1}} and one more revision is {{PRICE_2}}, for a "
        "total of {{TOTAL}}. Separately, would you like to discuss merch use?"
    ),
    "reply_draft_seller_translation": (
        "감사합니다! 추가 의상은 {{PRICE_1}}, 추가 수정은 {{PRICE_2}}이며 합계는 {{TOTAL}}입니다. "
        "굿즈 사용은 별도로 여쭙니다."
    ),
}

Response = str | dict[str, Any] | Exception


class FakeProvider:
    """Answers analysis calls and reply calls from separate scripted queues.

    An empty queue raises a non-retryable error, so an unexpected extra call shows up as a failure
    of the code path rather than as a silently reused answer.
    """

    def __init__(
        self,
        analysis: list[Response] | None = None,
        replies: list[Response] | None = None,
    ) -> None:
        self.analysis = list(analysis or [])
        self.replies = list(replies or [])
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, *, model: str, system: str, user: str, response_schema: dict[str, Any]
    ) -> str:
        self.calls.append({"model": model, "system": system, "user": user})
        is_reply = "reply_draft_client" in response_schema["properties"]
        queue = self.replies if is_reply else self.analysis
        if not queue:
            raise ProviderError("FakeProvider queue is empty", retryable=False)
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)

    @property
    def models(self) -> list[str]:
        return [call["model"] for call in self.calls]


def always(error: Callable[[], Exception], count: int = 20) -> list[Response]:
    return [error() for _ in range(count)]


def unavailable() -> ProviderError:
    return ProviderError("Gemini returned HTTP 503", retryable=True, status=503)
