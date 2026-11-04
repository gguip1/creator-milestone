"""Deterministic text rules the model cannot override.

Covers quote verification, hedge and firm-request detection, number and money mentions, and
reply-draft checks. Everything here is plain string logic: no model output is trusted.
"""

import re
import unicodedata
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from app.services.money import MoneyError, from_paypal_value, to_paypal_value

MIN_QUOTE_CHARS = 2


def normalize_text(text: str) -> str:
    """NFC-normalize (pasted Korean is often NFD) and collapse all whitespace runs."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def verify_quote(quote: str, source: str) -> str | None:
    """Return the normalized quote if it is a case-sensitive substring of the source."""
    normalized = normalize_text(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return None
    return normalized if normalized in normalize_text(source) else None


def has_hangul(text: str) -> bool:
    return re.search(r"[가-힣]", text) is not None


def detect_language(message: str, model_language: str) -> str:
    """Prefer what the script shows; fall back to a well-formed model label, then English."""
    hangul = len(re.findall(r"[가-힣]", message))
    latin = len(re.findall(r"[A-Za-z]", message))
    if hangul and hangul >= latin / 2:
        return "ko"
    label = model_language.strip()
    if re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2,4})?", label) and label != "ko":
        return label
    return "en"


# "around" and "about" count only before a quantity or a date, so "a glow around the character"
# and "excited about the sketch" are not hedges.
_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|"
    "forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|couple"
)
_DATE_WORDS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|mid|end|early|late|next|"
    "christmas|new year|week|weeks|month|months|day|days|noon|midnight|monday|tuesday|"
    "wednesday|thursday|friday|saturday|sunday"
)
_ENGLISH_HEDGE = re.compile(
    r"\b(?:maybe|might|perhaps|probably|possibly|potentially|roughly|approximately|approx"
    r"|i\s+think|i\s+guess|i\s+suppose|not\s+sure|unsure|thinking\s+(?:of|about)"
    r"|wondering|i['’]?m\s+considering|if\s+possible|or\s+so|at\s+some\s+point|someday"
    r"|would\s+be\s+(?:nice|cool|great|fun|awesome))\b"
    r"|\b\w+-ish\b|~\s*\$?\d"
    rf"|\b(?:around|about)\s+(?:the\s+|a\s+|an\s+)?"
    rf"(?:\$|\d|usd\b|(?:{_NUMBER_WORDS}|{_DATE_WORDS})\b)",
    re.IGNORECASE,
)
# "May 5" is a date, so only lowercase "may" and "May I/we/be" are treated as hedges.
_MAY_HEDGE = re.compile(r"\bmay\b|\bMay\s+(?:be|I|we)\b")
_KOREAN_HEDGE = re.compile(
    r"아마(?!추어)|혹시|정도|쯤|어쩌면|아무래도|대략|대충|글쎄|수도\s*있|지도\s*몰라|것\s*같"
    r"|고민\s*중|생각\s*중|(?<![가-힣])약\s*\d"
)
_KOREAN_QUESTION_ENDING = re.compile(r"(?:까요|나요|가요|을까|할까)[.\s]*$")


def has_hedge(text: str) -> bool:
    return any(
        pattern.search(text) is not None for pattern in (_ENGLISH_HEDGE, _MAY_HEDGE, _KOREAN_HEDGE)
    )


def is_question(sentence: str) -> bool:
    return "?" in sentence or "？" in sentence or bool(_KOREAN_QUESTION_ENDING.search(sentence))


@dataclass(frozen=True)
class _Clause:
    text: str
    sentence: str
    head: str
    index: int
    after_comma: bool


_SENTENCE_BREAK = re.compile(r"(?<=[.!?。！？])\s+|\s*\n\s*")
_CLAUSE_BREAK = re.compile(
    r"\s*[,;:—–]\s*|\s+(?:and|but|or)\s+|\s*(?:그리고|하지만|근데|그런데)\s+"
)


def _sentences(source: str) -> list[tuple[int, str]]:
    """Sentences with their offsets inside normalize_text(source)."""
    pieces = _SENTENCE_BREAK.split(unicodedata.normalize("NFC", source))
    sentences: list[tuple[int, str]] = []
    position = 0
    for piece in pieces:
        sentence = normalize_text(piece)
        if sentence:
            sentences.append((position, sentence))
            position += len(sentence) + 1
    return sentences


def _clauses(start: int, sentence: str) -> list[tuple[int, int, _Clause]]:
    spans: list[tuple[int, int, bool]] = []
    cursor = 0
    after_comma = False
    for separator in _CLAUSE_BREAK.finditer(sentence):
        spans.append((cursor, separator.start(), after_comma))
        cursor = separator.end()
        after_comma = separator.group().strip() == ","
    spans.append((cursor, len(sentence), after_comma))
    head = sentence[spans[0][0] : spans[0][1]]
    return [
        (
            start + begin,
            start + end,
            _Clause(sentence[begin:end], sentence, head, index, comma),
        )
        for index, (begin, end, comma) in enumerate(spans)
    ]


def _overlapping_clauses(quote: str, source: str) -> list[_Clause]:
    """Every clause touched by any occurrence of the quote in the source."""
    normalized_source = normalize_text(source)
    all_clauses = [
        clause for start, sentence in _sentences(source) for clause in _clauses(start, sentence)
    ]
    found: list[_Clause] = []
    position = normalized_source.find(quote)
    while position != -1:
        end = position + len(quote)
        for clause_start, clause_end, clause in all_clauses:
            if clause_start < end and position < clause_end and clause not in found:
                found.append(clause)
        position = normalized_source.find(quote, position + 1)
    return found


def quote_is_hedged(quote: str, source: str) -> bool:
    """True if the quote or its surrounding clause hedges, or its sentence is a question.

    Context matters: a model quoting "two rounds of revisions" out of "Maybe two rounds of
    revisions?" must not escape the rule by leaving the hedge outside its quote.
    """
    normalized = normalize_text(quote)
    if has_hedge(normalized):
        return True
    clauses = _overlapping_clauses(normalized, source)
    if not clauses:
        return True
    return any(
        has_hedge(clause.text) or has_hedge(clause.head) or is_question(clause.sentence)
        for clause in clauses
    )


_REQUEST_FILLER = r"(?:(?:and|also|so|oh|hi|hey|but|then|plus|lastly|finally|ok|okay)[,!\s]+)*"
_POLITE_REQUEST = re.compile(
    rf"^{_REQUEST_FILLER}(?:please\b|(?:could|can|would|will)\s+\w+)", re.IGNORECASE
)
_KOREAN_POLITE_REQUEST = re.compile(
    r"주실\s*수|주시겠|줄\s*수|주세요|부탁|가능할까요|가능한가요|가능하신가요|될까요|할\s*수\s*있|있을까요"
)
_PRICE_INQUIRY = re.compile(r"\b(?:how much|cost|costs|price|expensive)\b|얼마|비용|가격", re.I)
# ", maybe a casual hoodie version" only narrows down a request made earlier in the sentence.
_APPOSITIVE_DETAIL = re.compile(
    r"^(?:maybe|perhaps|probably|possibly|아마|아마도)\s+"
    r"(?:a|an|the|some|something|like|in|with|[가-힣]+)\b",
    re.IGNORECASE,
)


def _is_appositive(clause: _Clause) -> bool:
    return (
        clause.index > 0
        and clause.after_comma
        and _APPOSITIVE_DETAIL.match(clause.text) is not None
        and not has_hedge(clause.head)
    )


def _is_polite_request(text: str) -> bool:
    return (
        _POLITE_REQUEST.match(text) is not None or _KOREAN_POLITE_REQUEST.search(text) is not None
    )


def is_firm_request(quote: str, source: str) -> bool:
    """Whether a quoted request is firm enough to bill.

    Polite questions ("Could you add a second outfit?") are firm. Tentative wording ("I might use
    it on merch later", "Maybe a hat?") and plain inquiries ("How much is a hat?") are not.
    Anything uncertain returns False, because a missed bill is recoverable and a wrong one is not.
    """
    clauses = _overlapping_clauses(normalize_text(quote), source)
    if not clauses:
        return False
    for clause in clauses:
        text = clause.head if _is_appositive(clause) else clause.text
        if has_hedge(text) or has_hedge(clause.head) or _PRICE_INQUIRY.search(text):
            return False
        if is_question(clause.sentence) and not (
            _is_polite_request(clause.text) or _is_polite_request(clause.sentence)
        ):
            return False
    return True


_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_KOREAN_NUMBERS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8}
_KOREAN_COUNTED = re.compile(
    r"(?<![가-힣])(한|두|세|네|다섯|여섯|일곱|여덟)\s*(?:번|회|차례|라운드|벌|개|장|명|가지)"
)


def numbers_in_text(text: str) -> set[int]:
    """Cardinal numbers stated in English or Korean: digits, number words, counted Korean nouns."""
    found = {int(digits) for digits in re.findall(r"(?<![\d.,])\d{1,4}(?![\d,]|\.\d)", text)}
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _WORD_NUMBERS:
            found.add(_WORD_NUMBERS[word])
    for word in _KOREAN_COUNTED.findall(text):
        found.add(_KOREAN_NUMBERS[word])
    return found


@dataclass(frozen=True)
class MoneyMention:
    currency_code: str | None
    minor_units: int | None


_AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_MULTIPLIER = r"(?:[kKmM](?![A-Za-z])|[만천백]+)?"
_MONEY_PREFIX = re.compile(
    r"(?P<currency>US\$|[A-Z]{1,3}\$|\$|€|£|¥|₩|\b(?:USD|EUR|GBP|JPY|KRW|CAD|AUD|CNY)\b)"
    rf"\s*(?P<amount>{_AMOUNT})(?P<multiplier>{_MULTIPLIER})",
    re.IGNORECASE,
)
_MONEY_SUFFIX = re.compile(
    rf"(?P<amount>{_AMOUNT})\s*(?P<multiplier>{_MULTIPLIER})\s*"
    r"(?P<currency>(?:usd|us\s+dollars?|dollars?|bucks?|eur|euros?|gbp|pounds?|jpy|yen|krw|won"
    r"|cad|aud|cny)\b|달러|불|유로|엔|원|파운드)",
    re.IGNORECASE,
)
_SPELLED_MONEY = re.compile(
    rf"\b(?:{_NUMBER_WORDS})(?:[\s-]+\w+)?\s+(?:dollars?|bucks?|usd)\b"
    r"|[일이삼사오육칠팔구십백천만]+\s*달러|[일이삼사오육칠팔구십백천]*만\s*원",
    re.IGNORECASE,
)
_USD_MARKERS = {
    "$",
    "us$",
    "usd",
    "us dollar",
    "us dollars",
    "dollar",
    "dollars",
    "buck",
    "bucks",
    "달러",
    "불",
}


def _mention_from_match(match: re.Match[str]) -> MoneyMention:
    marker = re.sub(r"\s+", " ", match.group("currency")).lower()
    if marker not in _USD_MARKERS:
        return MoneyMention(None, None)
    if match.group("multiplier"):
        return MoneyMention("USD", None)
    try:
        return MoneyMention("USD", from_paypal_value(match.group("amount").replace(",", ""), "USD"))
    except MoneyError:
        return MoneyMention("USD", None)


def find_money_mentions(text: str) -> list[MoneyMention]:
    """Every amount of money stated in the text. Unparseable ones have minor_units None."""
    mentions = [
        _mention_from_match(match)
        for pattern in (_MONEY_PREFIX, _MONEY_SUFFIX)
        for match in pattern.finditer(text)
    ]
    mentions.extend(MoneyMention(None, None) for _ in _SPELLED_MONEY.finditer(text))
    return mentions


def parse_usd_amount(text: str) -> int | None:
    """The single positive USD amount in the text, or None if absent, ambiguous, or not USD."""
    mentions = find_money_mentions(text)
    if not mentions or any(mention.currency_code != "USD" for mention in mentions):
        return None
    amounts = {mention.minor_units for mention in mentions}
    if len(amounts) != 1:
        return None
    amount = amounts.pop()
    return amount if amount else None


def format_money(minor_units: int, currency_code: str = "USD") -> str:
    prefix = "$" if currency_code == "USD" else f"{currency_code} "
    return f"{prefix}{to_paypal_value(minor_units, currency_code)}"


_TOKEN = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|퍼센트|percent\b)", re.IGNORECASE)
_PRICE_CONCESSION = re.compile(
    r"\b(?:discount|discounted|waive|waived|on the house|free of charge|for free|complimentary"
    r"|no charge)\b|할인|무료|공짜|서비스로",
    re.IGNORECASE,
)
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


def reply_problems(
    draft: str,
    tokens: Mapping[str, int],
    *,
    required_tokens: Iterable[str] = (),
    allowed_percents: Collection[int] = (),
) -> list[str]:
    """Why a draft may not be used. Amounts must be tokens or equal a computed value."""
    if not draft.strip():
        return ["an empty draft"]
    problems: list[str] = []
    used = set(_TOKEN.findall(draft))
    problems.extend(f"unknown token {token}" for token in sorted(used - set(tokens)))
    problems.extend(f"a missing token {token}" for token in required_tokens if token not in used)
    remainder = _TOKEN.sub(" ", draft)
    if "{" in remainder or "}" in remainder:
        problems.append("a malformed token")
    allowed = set(tokens.values())
    if any(
        mention.currency_code != "USD" or mention.minor_units not in allowed
        for mention in find_money_mentions(remainder)
    ):
        problems.append("an amount not computed by the server")
    percents = {float(percent) for percent in _PERCENT.findall(remainder)}
    if percents - {float(percent) for percent in allowed_percents}:
        problems.append("a percentage not computed by the server")
    if _PRICE_CONCESSION.search(remainder):
        problems.append("a discount or free-work promise")
    if _LINK.search(remainder):
        problems.append("a link")
    return problems


def fill_tokens(draft: str, tokens: Mapping[str, int], currency_code: str = "USD") -> str:
    def replace(match: re.Match[str]) -> str:
        return format_money(tokens[match.group(1)], currency_code)

    return _TOKEN.sub(replace, draft).replace("$$", "$")
