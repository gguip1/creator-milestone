"""Recorded live analyses of the two seeded demo messages, used only when every model fails.

The JSON files are written by scripts/ai_eval.py from real model output after the server rules
have run. Do not edit them by hand.
"""

import json
from pathlib import Path
from typing import Any

from app.agent.hedging import normalize_text
from app.schemas.ai import IntakeAnalysis

CACHE_DIR = Path(__file__).parent
INTAKE_FILE = CACHE_DIR / "intake_message_1.json"
SCOPE_GUARD_FILE = CACHE_DIR / "scope_guard_message_2.json"


def _load(path: Path, message: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    same_message = normalize_text(payload["message"]).casefold() == (
        normalize_text(message).casefold()
    )
    return payload if same_message else None


def load_cached_intake(message: str) -> IntakeAnalysis | None:
    payload = _load(INTAKE_FILE, message)
    if payload is None:
        return None
    return IntakeAnalysis.model_validate({**payload["analysis"], "source": "cached"})


def load_cached_scope_guard(message: str) -> dict[str, Any] | None:
    """The recorded items and token-form drafts; scope_guard recomputes prices from them."""
    return _load(SCOPE_GUARD_FILE, message)


def write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
