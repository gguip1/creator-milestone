from datetime import date

from app.schemas.ai import RateCardEntry, ScopeContext, ScopeGuardResult


async def guard_scope(
    message: str,
    *,
    scope: ScopeContext,
    rate_card: list[RateCardEntry],
    today: date,
) -> ScopeGuardResult:
    raise NotImplementedError
