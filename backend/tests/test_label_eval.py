"""The label scorer is plain code, so it is tested without any model call."""

from app.schemas.ai import ScopeGuardItem, ScopeGuardResult
from scripts.label_eval import CASES_FILE, case_passed, load_cases, render_report, score_guard


def _result(*items: ScopeGuardItem) -> ScopeGuardResult:
    return ScopeGuardResult(
        items=list(items),
        total_minor_units=sum(i.amount_minor_units or 0 for i in items if i.billable),
        reply_draft_client="",
        reply_draft_seller_translation="",
        source="live",
    )


def _outfit(**overrides) -> ScopeGuardItem:
    base = dict(
        request_summary="Add a second outfit",
        quote="add a second outfit",
        classification="out_of_scope",
        rate_card_code="EXTRA_OUTFIT",
        amount_minor_units=8000,
        billable=True,
    )
    return ScopeGuardItem(**{**base, **overrides})


EXPECT = {
    "items": [
        {
            "match": ["outfit"],
            "classification": "out_of_scope",
            "rate_card_code": "EXTRA_OUTFIT",
            "billable": True,
            "amount": 8000,
        }
    ],
    "total": 8000,
}


def test_guard_scoring_passes_a_match_and_names_each_failure() -> None:
    assert all(e["ok"] for e in score_guard(_result(_outfit()), EXPECT))
    wrong = score_guard(_result(_outfit(classification="question", billable=False)), EXPECT)
    assert {e["name"] for e in wrong if not e["ok"]} == {
        "outfit.classification",
        "outfit.billable",
        "total",
    }


def test_guard_scoring_fails_every_expectation_when_the_item_is_missing() -> None:
    missing = score_guard(_result(), EXPECT)
    assert [e["ok"] for e in missing] == [False, False, False, False, False]


def test_labels_file_has_the_promised_mix_and_report_renders() -> None:
    cases = load_cases(CASES_FILE)
    assert len(cases) == 20
    assert sum(c["kind"] == "intake" for c in cases) == 8
    assert sum(c["kind"] == "guard" for c in cases) == 12
    assert {c["language"] for c in cases} == {"en", "ko"}
    record = {
        "id": "x",
        "kind": "guard",
        "language": "en",
        "source": "live",
        "run_at": "now",
        "attempts": [],
        "expectations": [{"name": "total", "ok": False, "expected": 1, "actual": 2}],
    }
    assert not case_passed(record)
    assert "FAIL" in render_report([record], 1)
