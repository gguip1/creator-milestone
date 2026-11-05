"""LLM access for the agent: a small provider interface, a model chain, and typed output.

The model never receives tools or PayPal access. Everything it returns is validated here and then
checked again by the deterministic rules in intake.py and scope_guard.py.
"""

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.schemas.ai import LLMUnavailableError

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODEL = "gemini-3.1-flash-lite"
# gemini-2.5-* requests reroute on Dec 1, during judging.
BANNED_MODEL_PREFIX = "gemini-2.5-"

MAX_INPUT_CHARS = 6_000
REQUEST_TIMEOUT_SECONDS = 25.0
CHAIN_DEADLINE_SECONDS = 70.0
ATTEMPTS_PER_MODEL = 2
BACKOFF_SECONDS = (0.5, 1.5)
RETRYABLE_STATUSES = frozenset({429, 500, 503})


class ProviderError(RuntimeError):
    """A failed provider call. Messages must never contain the API key or client text."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LLMProvider(Protocol):
    async def generate(
        self, *, model: str, system: str, user: str, response_schema: dict[str, Any]
    ) -> str:
        """Return the model's raw JSON text, or raise ProviderError."""
        ...


class GeminiProvider:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._transport = transport

    async def generate(
        self, *, model: str, system: str, user: str, response_schema: dict[str, Any]
    ) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{GEMINI_BASE_URL}/{model}:generateContent",
                    headers={"x-goog-api-key": self._api_key},
                    json=body,
                )
        except httpx.HTTPError as exc:
            # Only the type name: exception text is not guaranteed to be free of request details.
            raise ProviderError(f"{type(exc).__name__} from Gemini", retryable=True) from None
        if response.status_code != 200:
            raise ProviderError(
                f"Gemini returned HTTP {response.status_code}",
                retryable=response.status_code in RETRYABLE_STATUSES,
                status=response.status_code,
            )
        return _gemini_text(response)


def _gemini_text(response: httpx.Response) -> str:
    try:
        parts = response.json()["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ProviderError("Gemini returned no candidate text", retryable=True) from None
    if not text:
        raise ProviderError("Gemini returned empty text", retryable=True)
    return text


PROVIDERS: dict[str, Callable[[str], LLMProvider]] = {"gemini": GeminiProvider}

_provider_override: LLMProvider | None = None


def set_provider(provider: LLMProvider | None) -> None:
    """Replace the configured provider, for tests and the evaluation script."""
    global _provider_override
    _provider_override = provider


def get_provider() -> LLMProvider:
    if _provider_override is not None:
        return _provider_override
    settings = get_settings()
    build = PROVIDERS.get((settings.llm_provider or "gemini").strip().lower())
    api_key = settings.llm_api_key.get_secret_value()
    if build is None or not api_key:
        raise LLMUnavailableError("The LLM provider is not configured")
    return build(api_key)


def model_chain() -> list[str]:
    configured = get_settings().llm_model.strip()
    if not configured or configured.startswith(BANNED_MODEL_PREFIX):
        configured = DEFAULT_MODEL
    return list(dict.fromkeys([configured, FALLBACK_MODEL]))


def cap_input(text: str) -> str:
    return text[:MAX_INPUT_CHARS]


def untrusted_block(label: str, text: str) -> str:
    """Wrap client text in a delimiter the client cannot guess, so it cannot close the block."""
    boundary = f"{label}_{secrets.token_hex(8)}"
    return f"<<<BEGIN {boundary}>>>\n{text}\n<<<END {boundary}>>>"


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    parsed: T
    model_id: str


async def complete[T: BaseModel](
    *,
    system: str,
    user: str,
    output_model: type[T],
    response_schema: dict[str, Any],
    attempts_per_model: int = ATTEMPTS_PER_MODEL,
) -> LLMResult[T]:
    """Walk the model chain until one returns output that validates against output_model."""
    provider = get_provider()
    deadline = time.monotonic() + CHAIN_DEADLINE_SECONDS
    for model in model_chain():
        for attempt in range(attempts_per_model):
            if time.monotonic() > deadline:
                raise LLMUnavailableError("The LLM deadline passed")
            retry_same_model = True
            try:
                text = await provider.generate(
                    model=model, system=system, user=user, response_schema=response_schema
                )
                return LLMResult(output_model.model_validate_json(text), model)
            except ProviderError as exc:
                logger.warning("LLM attempt failed on %s: %s", model, exc)
                retry_same_model = exc.retryable
            except ValidationError as exc:
                # Pydantic's message embeds the input, so log only the error count.
                logger.warning("LLM output invalid on %s: %d errors", model, exc.error_count())
            if not retry_same_model:
                break
            if attempt + 1 < attempts_per_model:
                await asyncio.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise LLMUnavailableError("Every LLM model failed")


class RawReply(BaseModel):
    reply_draft_client: str
    reply_draft_seller_translation: str


REPLY_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "reply_draft_client": {"type": "STRING"},
        "reply_draft_seller_translation": {"type": "STRING"},
    },
    "required": ["reply_draft_client", "reply_draft_seller_translation"],
}

REPLY_ROUNDS = 2
REPLY_ATTEMPTS_PER_MODEL = 2


async def draft_reply(
    *,
    system: str,
    facts: dict[str, Any],
    find_problems: Callable[[RawReply], list[str]],
) -> RawReply | None:
    """Draft from server-approved facts; regenerate once on a failed check, else return None.

    Callers fall back to a code-written template on None, so a reply failure never loses a
    classification that already passed the server rules.
    """
    user = json.dumps(facts, ensure_ascii=False, indent=1)
    problems: list[str] = []
    for _ in range(REPLY_ROUNDS):
        correction = (
            "\n\nYour previous draft was rejected for containing: "
            + "; ".join(problems)
            + ". Write it again without these problems."
            if problems
            else ""
        )
        try:
            result = await complete(
                system=system,
                user=user + correction,
                output_model=RawReply,
                response_schema=REPLY_SCHEMA,
                attempts_per_model=REPLY_ATTEMPTS_PER_MODEL,
            )
        except LLMUnavailableError:
            return None
        problems = find_problems(result.parsed)
        if not problems:
            return result.parsed
        logger.warning("Reply draft rejected: %s", "; ".join(problems))
    return None
