from datetime import date

from app.schemas.ai import IntakeAnalysis


async def analyze_intake(message: str, *, today: date) -> IntakeAnalysis:
    raise NotImplementedError
