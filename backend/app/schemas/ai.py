"""Shared contract between the AI layer, the backend core, and the API. Change only via the PM."""

from typing import Literal

from pydantic import BaseModel, Field

Provenance = Literal["explicit", "inferred", "unknown"]
Classification = Literal["in_scope", "exceeds_limit", "out_of_scope", "question"]
AnalysisSource = Literal["live", "cached"]


class ExtractedField(BaseModel):
    value: str | None
    provenance: Provenance
    quote: str = ""
    # Set by the server, never by the model.
    quote_verified: bool = False
    needs_confirmation: bool = True


class IntakeAnalysis(BaseModel):
    source_language: str
    title: ExtractedField
    deliverables: list[ExtractedField]
    file_formats: list[ExtractedField]
    deadline: ExtractedField
    revisions: ExtractedField
    usage_rights: ExtractedField
    budget: ExtractedField
    # Parsed by the server from budget.value, never taken from the model as an authoritative amount.
    budget_minor_units: int | None = None
    currency_code: str | None = None
    client_email: ExtractedField
    sketch_review_requested: ExtractedField
    questions: list[str]
    reply_draft_client: str
    reply_draft_seller_translation: str
    source: AnalysisSource
    model_id: str | None = None


class RateCardEntry(BaseModel):
    code: str
    name: str
    unit_price_minor_units: int
    unit: str = "each"


class ScopeContext(BaseModel):
    scope_version: int
    title: str
    deliverables: list[str]
    file_formats: list[str]
    revisions_included: int
    revisions_used: int
    deadline: str | None
    usage_rights: str
    currency_code: str = "USD"


class ScopeGuardItem(BaseModel):
    request_summary: str
    quote: str
    quote_verified: bool = False
    classification: Classification
    # Which agreed term applies: deliverables, file_formats, revisions, deadline, usage_rights.
    clause_ref: str | None = None
    clause_text: str | None = None
    rate_card_code: str | None = None
    quantity: int = Field(default=1, ge=1)
    # Computed by the server from the rate card, never by the model.
    unit_price_minor_units: int | None = None
    amount_minor_units: int | None = None
    needs_price: bool = False
    billable: bool = False


class ScopeGuardResult(BaseModel):
    items: list[ScopeGuardItem]
    total_minor_units: int = 0
    reply_draft_client: str
    reply_draft_seller_translation: str
    source: AnalysisSource
    model_id: str | None = None


class LLMUnavailableError(RuntimeError):
    """Every model failed and no cached analysis exists for this input."""
