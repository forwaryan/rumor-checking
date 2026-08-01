"""Structured output validation for LLM responses.

Provides schema-enforced JSON parsing with automatic retry integration.
When a response fails validation, the `is_valid` callback returns False,
triggering the existing retry logic in `_request_completion`.

Usage:
    from backend.app.agent.structured_output import schema_validator, parse_validated

    # As is_valid callback (retry on schema mismatch):
    content = self._request_completion(..., is_valid=schema_validator(MySchema))

    # Parse the validated content:
    result = parse_validated(content, MySchema)
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.services.contract_utils import loads_lenient_json

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when LLM output cannot be validated against the expected schema."""

    def __init__(self, content: str, schema_name: str, errors: list[dict] | str):
        self.content = content
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"Schema validation failed for {schema_name}: {errors}")


def schema_validator(schema: type[T], *, lenient_json: bool = True) -> Callable[[str], bool]:
    """Return an `is_valid` callback for _request_completion that checks schema.

    Args:
        schema: A pydantic BaseModel class to validate against.
        lenient_json: If True, use the lenient JSON parser (handles markdown fences,
                     trailing commas, etc.) before validation.

    Returns:
        A callable(content: str) -> bool suitable for the `is_valid` parameter.
    """
    def validator(content: str) -> bool:
        if not content or not content.strip():
            return False
        try:
            payload = _extract_json(content, lenient=lenient_json)
            if payload is None:
                return False
            schema.model_validate(payload)
            return True
        except (ValidationError, json.JSONDecodeError, TypeError):
            return False
    return validator


def parse_validated(content: str, schema: type[T], *, lenient_json: bool = True) -> T | None:
    """Parse LLM content into a validated pydantic model.

    Returns None if parsing fails — caller should handle gracefully.
    """
    if not content or not content.strip():
        return None
    try:
        payload = _extract_json(content, lenient=lenient_json)
        if payload is None:
            return None
        return schema.model_validate(payload)
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        logger.debug("structured_output_parse_failed schema=%s error=%s", schema.__name__, str(exc)[:200])
        return None


def parse_validated_or_raise(content: str, schema: type[T], *, lenient_json: bool = True) -> T:
    """Parse LLM content into a validated pydantic model, raising on failure."""
    if not content or not content.strip():
        raise StructuredOutputError(content or "", schema.__name__, "empty content")
    payload = _extract_json(content, lenient=lenient_json)
    if payload is None:
        raise StructuredOutputError(content, schema.__name__, "no JSON found")
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(content, schema.__name__, exc.errors()) from exc


def _extract_json(content: str, *, lenient: bool = True) -> Any:
    """Extract a JSON object/array from LLM content.

    Handles: raw JSON, markdown-fenced JSON, trailing/leading text.
    """
    if lenient:
        result = loads_lenient_json(content)
        if result is not None:
            return result
    # Fallback: try strict JSON parse
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        return None


# --- Pre-built schemas for common LLM responses ---


class InvestigationPlanSchema(BaseModel):
    should_continue: bool
    follow_up_query: str | None = None
    reason: str = ""


class NextActionSchema(BaseModel):
    next_action: str
    reason: str = ""


class ActionSequenceSchema(BaseModel):
    actions: list[str]
    reason: str = ""


class QueryTermsSchema(BaseModel):
    entities: list[str] = []
    keywords: list[str] = []
    primary_query: str = ""
    aliases: list[str] = []


class SynthesisClaimSchema(BaseModel):
    claim: str
    claim_type: str = "fact"
    verdict: str = "insufficient"
    confidence: str = "medium"
    truth_probability: int | None = None
    probability_basis: str | None = None
    evidence_result_ids: list[str] = []
    notes: str = ""


class SynthesisResponseSchema(BaseModel):
    claims: list[SynthesisClaimSchema] = []


class CriticRevisionSchema(BaseModel):
    index: int
    keep: bool = True
    reason: str = ""


class CriticResponseSchema(BaseModel):
    revisions: list[CriticRevisionSchema] = []


class RefinedClaimSchema(BaseModel):
    index: int
    verdict: str
    confidence: str = "medium"
    evidence_result_ids: list[str] = []
    notes: str = ""


class RefineResponseSchema(BaseModel):
    refined_claims: list[RefinedClaimSchema] = []


class QuestionResolutionSchema(BaseModel):
    selected_result_id: str | None = None
    resolved_summary: str | None = None
    follow_up_query: str | None = None
    reason: str = ""


class EnrichmentScenarioSchema(BaseModel):
    label: str
    probability: int = 50
    basis: str = "prior"
    summary: str = ""


class EnrichmentTimelineSchema(BaseModel):
    node_type: str = "origin"
    result_id: str = ""
    summary: str = ""
    why_selected: str = ""


class EnrichmentEventSchema(BaseModel):
    title: str = ""
    summary: str = ""


class EnrichmentResponseSchema(BaseModel):
    event: EnrichmentEventSchema | None = None
    scenarios: list[EnrichmentScenarioSchema] = []
    timeline: list[EnrichmentTimelineSchema] = []
