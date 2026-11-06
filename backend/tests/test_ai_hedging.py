import pytest

from app.agent.hedging import (
    fill_tokens,
    find_money_mentions,
    has_hedge,
    is_firm_request,
    is_mostly_korean,
    normalize_text,
    numbers_in_text,
    parse_usd_amount,
    quote_is_hedged,
    reply_problems,
    verify_quote,
)
from tests.fixtures.ai_demo import DEMO_MESSAGE_1, DEMO_MESSAGE_2


@pytest.mark.parametrize(
    "text",
    [
        "Maybe two rounds",
        "I might use it",
        "perhaps a hat",
        "probably PNG",
        "around November 25",
        "about 300 dollars",
        "roughly $50",
        "I think two",
        "May I add one",
        "PNG if possible",
        "아마 두 번",
        "혹시 가능할까요",
        "두 번 정도",
        "12월 10일쯤",
        "약 300달러",
    ],
)
def test_hedges_are_detected(text):
    assert has_hedge(text)


@pytest.mark.parametrize(
    "text",
    [
        "Add a glow around the character",
        "I am excited about the sketch",
        "What I love about this sketch",
        "By May 5",
        "두 번으로 해주세요",
        "계약서 보내 주세요",
        "예약 부탁드립니다",
        "아마추어 스타일",
    ],
)
def test_ordinary_wording_is_not_a_hedge(text):
    assert not has_hedge(text)


def test_quote_must_be_case_sensitive_substring_after_whitespace_normalization():
    source = "My budget\n  is USD 300."
    assert verify_quote("My budget is USD 300", source) == "My budget is USD 300"
    assert verify_quote("my budget is usd 300", source) is None
    assert verify_quote("My budget is USD 500", source) is None
    assert verify_quote("   ", source) is None


def test_decomposed_korean_still_verifies():
    source = "수정은 두 번".encode().decode()
    import unicodedata

    assert verify_quote("수정은 두 번", unicodedata.normalize("NFD", source)) is not None


def test_hedge_outside_the_quote_is_still_found():
    assert quote_is_hedged("two rounds of revisions", DEMO_MESSAGE_1)
    assert quote_is_hedged("November 25", DEMO_MESSAGE_1)


def test_hedge_in_another_clause_does_not_spread():
    assert not quote_is_hedged("transparent PNG plus layered PSD", DEMO_MESSAGE_1)
    assert not quote_is_hedged("My budget is USD 300", DEMO_MESSAGE_1)


def test_sentence_offsets_match_the_normalized_text():
    source = "First line.\n\nCould you  add a hat?\nMaybe a scarf?"
    assert quote_is_hedged("a scarf", source)
    assert is_firm_request("add a hat", source)
    assert "add a hat" in normalize_text(source)


@pytest.mark.parametrize(
    "quote",
    [
        "Could you also add a second outfit, maybe a casual hoodie version?",
        "add a second outfit",
        "maybe a casual hoodie version",
        "can we do one more pass on the face?",
        "one more pass on the face",
    ],
)
def test_demo_message_firm_requests(quote):
    assert is_firm_request(quote, DEMO_MESSAGE_2)


@pytest.mark.parametrize(
    "quote,source",
    [
        ("I might use it on merch later", DEMO_MESSAGE_2),
        ("use it on merch later", DEMO_MESSAGE_2),
        ("Maybe add a hat?", "Maybe add a hat?"),
        ("a hat", "Could you fix the eyes and maybe a hat?"),
        ("How much is a hat?", "How much is a hat?"),
        ("What would a second outfit cost?", "What would a second outfit cost?"),
        ("Could you tell me the price of a hat?", "Could you tell me the price of a hat?"),
        ("a hat", "I think a hat and a scarf would be good."),
        ("굿즈로 쓸 수도 있어요", "나중에 굿즈로 쓸 수도 있어요."),
        ("의상을 추가할 수 있을까요", "혹시 의상을 추가할 수 있을까요?"),
        ("not in the source", "Add a hat."),
    ],
)
def test_tentative_requests_are_not_firm(quote, source):
    assert not is_firm_request(quote, source)


@pytest.mark.parametrize(
    "quote,source",
    [
        ("Please add a hat.", "Please add a hat."),
        ("I want a hat.", "I want a hat."),
        ("could you add a hat?", "Love it, could you add a hat?"),
        ("의상 하나 더 추가해 주세요", "의상 하나 더 추가해 주세요."),
        ("추가해 주실 수 있나요", "의상을 추가해 주실 수 있나요?"),
    ],
)
def test_polite_requests_are_firm(quote, source):
    assert is_firm_request(quote, source)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("USD 300", 30_000),
        ("My budget is USD 300", 30_000),
        ("$1,200.50", 120_050),
        ("300 dollars", 30_000),
        ("300달러", 30_000),
        ("300 usd", 30_000),
        ("$300 USD", 30_000),
        ("US$ 90", 9_000),
        ("€250", None),
        ("EUR 250", None),
        ("30만원", None),
        ("C$300", None),
        ("300", None),
        ("$1.5k", None),
        ("$300-$400", None),
        ("USD 300 or EUR 250", None),
        ("$300.555", None),
        ("$0", None),
        ("three hundred dollars", None),
    ],
)
def test_parse_usd_amount(text, expected):
    assert parse_usd_amount(text) == expected


def test_numbers_in_text_reads_digits_words_and_korean_counts():
    assert numbers_in_text("two rounds") == {2}
    assert numbers_in_text("3 passes") == {3}
    assert numbers_in_text("수정 두 번") == {2}
    assert numbers_in_text("a second outfit") == set()


def test_spelled_out_money_counts_as_a_mention():
    assert find_money_mentions("eighty dollars")
    assert find_money_mentions("팔십 달러")
    assert not find_money_mentions("2 rounds by November 25")


def test_reply_check_flags_every_uncomputed_statement():
    tokens = {"PRICE_1": 8_000, "TOTAL": 8_000}
    ok = "The outfit is {{PRICE_1}}."
    assert reply_problems(ok, tokens, required_tokens=["PRICE_1"]) == []
    assert reply_problems("The outfit is $80.00.", tokens) == []
    assert reply_problems("The outfit is $1.", tokens)
    assert reply_problems("That is 300 dollars.", tokens)
    assert reply_problems("{{PRICE_2}}", tokens)
    assert reply_problems("no token", tokens, required_tokens=["PRICE_1"])
    assert reply_problems("{PRICE_1}", tokens)
    assert reply_problems("Take 20% off", tokens)
    assert reply_problems("I can do it for free", tokens)
    assert reply_problems("See https://example.com", tokens)
    assert reply_problems("   ", tokens)


def test_mostly_korean_requires_a_hangul_majority():
    assert is_mostly_korean("추가 의상은 {{PRICE_1}}입니다.")
    assert is_mostly_korean("투명 PNG와 레이어 PSD로 드리겠습니다.")
    assert not is_mostly_korean("Adding an extra 의상 goes beyond the agreement.")
    assert not is_mostly_korean("")


def test_fill_tokens_handles_a_model_written_dollar_sign():
    assert fill_tokens("${{PRICE_1}} and {{TOTAL}}", {"PRICE_1": 8_000, "TOTAL": 10_000}) == (
        "$80.00 and $100.00"
    )


def test_fill_tokens_turns_escaped_breaks_into_real_ones_and_fixes_doubled_ending():
    out = fill_tokens("첫 줄\\n\\n어떻게 하시겠겠습니까?\\r\\n끝", {})
    assert out == "첫 줄\n\n어떻게 하시겠습니까?\n끝"
    assert fill_tokens("Real\nbreak and 겠습니다", {}) == "Real\nbreak and 겠습니다"
