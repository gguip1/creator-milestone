import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.agent import llm
from app.agent.llm import GeminiProvider, ProviderError, complete, model_chain, untrusted_block
from app.config import Settings
from app.schemas.ai import LLMUnavailableError
from tests.fixtures.ai_demo import FakeProvider, unavailable

SCHEMA = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}, "required": ["ok"]}
API_KEY = "test-key-not-real"


class Out(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def fast_chain(monkeypatch):
    monkeypatch.setattr(llm, "BACKOFF_SECONDS", (0.0, 0.0))
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            llm_provider="gemini",
            llm_model="gemini-3.5-flash-lite",
            llm_api_key=API_KEY,
        ),
    )
    yield
    llm.set_provider(None)


def use(provider: FakeProvider) -> FakeProvider:
    llm.set_provider(provider)
    return provider


async def run() -> llm.LLMResult[Out]:
    return await complete(system="s", user="u", output_model=Out, response_schema=SCHEMA)


async def test_chain_retries_transient_errors_then_falls_through_to_the_next_model():
    provider = use(FakeProvider([unavailable(), unavailable(), unavailable(), {"ok": True}]))
    result = await run()
    assert result.parsed.ok is True
    assert result.model_id == "gemini-3.1-flash-lite"
    assert provider.models == ["gemini-3.5-flash-lite"] * 3 + ["gemini-3.1-flash-lite"]


async def test_non_retryable_error_moves_straight_to_the_next_model():
    forbidden = ProviderError("Gemini returned HTTP 403", retryable=False, status=403)
    provider = use(FakeProvider([forbidden, {"ok": True}]))
    await run()
    assert provider.models == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


@pytest.mark.parametrize("bad", ["not json", '{"ok": "maybe"}', "{}"])
async def test_invalid_output_counts_as_a_failed_attempt(bad):
    provider = use(FakeProvider([bad, {"ok": True}]))
    result = await run()
    assert result.parsed.ok is True
    assert len(provider.calls) == 2


async def test_every_model_failing_raises_unavailable():
    provider = use(FakeProvider([unavailable() for _ in range(6)]))
    with pytest.raises(LLMUnavailableError):
        await run()
    assert len(provider.calls) == 6


async def test_missing_key_raises_unavailable(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(_env_file=None, llm_api_key=""))
    with pytest.raises(LLMUnavailableError):
        await run()


async def test_unknown_provider_raises_unavailable(monkeypatch):
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: Settings(_env_file=None, llm_provider="other", llm_api_key=API_KEY),
    )
    with pytest.raises(LLMUnavailableError):
        await run()


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("gemini-3.5-flash-lite", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
        ("gemini-3.1-flash-lite", ["gemini-3.1-flash-lite"]),
        ("", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
        ("gemini-2.5-flash", ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]),
    ],
)
def test_model_chain(monkeypatch, configured, expected):
    monkeypatch.setattr(llm, "get_settings", lambda: Settings(_env_file=None, llm_model=configured))
    assert model_chain() == expected


def gemini(handler) -> GeminiProvider:
    return GeminiProvider(API_KEY, transport=httpx.MockTransport(handler))


async def test_gemini_request_shape():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        text = '{"ok": true}'
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    text = await gemini(handler).generate(
        model="gemini-3.5-flash-lite", system="sys", user="usr", response_schema=SCHEMA
    )
    assert text == '{"ok": true}'
    assert seen["url"].endswith("/v1beta/models/gemini-3.5-flash-lite:generateContent")
    assert API_KEY not in seen["url"]
    assert seen["key"] == API_KEY
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "usr"
    config = seen["body"]["generationConfig"]
    assert config["temperature"] == 0
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == SCHEMA


@pytest.mark.parametrize(
    "status,retryable", [(429, True), (500, True), (503, True), (400, False), (403, False)]
)
async def test_gemini_status_mapping_and_no_secret_in_errors(status, retryable):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"bad key {API_KEY}"}})

    with pytest.raises(ProviderError) as caught:
        await gemini(handler).generate(model="m", system="s", user="u", response_schema=SCHEMA)
    assert caught.value.retryable is retryable
    assert caught.value.status == status
    assert API_KEY not in str(caught.value)


async def test_gemini_timeout_is_retryable_and_hides_details():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out with {API_KEY}")

    with pytest.raises(ProviderError) as caught:
        await gemini(handler).generate(model="m", system="s", user="u", response_schema=SCHEMA)
    assert caught.value.retryable is True
    assert API_KEY not in str(caught.value)


@pytest.mark.parametrize(
    "payload", [{}, {"candidates": []}, {"candidates": [{"finishReason": "SAFETY"}]}]
)
async def test_gemini_blocked_or_empty_response_is_a_retryable_failure(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(ProviderError) as caught:
        await gemini(handler).generate(model="m", system="s", user="u", response_schema=SCHEMA)
    assert caught.value.retryable is True


def test_untrusted_block_boundary_cannot_be_predicted():
    first, second = untrusted_block("X", "a"), untrusted_block("X", "a")
    assert first != second
    assert first.splitlines()[1] == "a"
