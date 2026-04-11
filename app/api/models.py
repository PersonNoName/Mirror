"""Shared API-layer request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1)]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class ChatMetaResponse(BaseModel):
    task_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    user_id: str
    status: str
    meta: ChatMetaResponse | None = None


class HitlResponse(BaseModel):
    status: str
    task_id: str
    decision: str


class EvolutionJournalItemResponse(BaseModel):
    id: str
    user_id: str
    event_type: str
    summary: str
    details: dict[str, Any]
    created_at: datetime


class EvolutionJournalResponse(BaseModel):
    items: list[EvolutionJournalItemResponse]
    count: int


class MemoryItemResponse(BaseModel):
    memory_key: str
    content: str
    truth_type: str
    status: str
    source: str
    confidence: float
    confirmed_by_user: bool
    updated_at: datetime | str
    visibility: str


class MemoryListResponse(BaseModel):
    items: list[MemoryItemResponse]
    count: int


class MemoryGovernancePolicyResponse(BaseModel):
    user_id: str
    blocked_content_classes: list[str]
    retention_days: dict[str, int]
    updated_at: datetime | str


class MemoryGovernanceBlockResponse(BaseModel):
    user_id: str
    content_class: str
    blocked: bool
    policy: MemoryGovernancePolicyResponse


class MemoryCorrectionResponse(BaseModel):
    status: str
    item: MemoryItemResponse


class MemoryDeleteResponse(BaseModel):
    status: str
    memory_key: str


class MemoryCorrectionRequest(APIModel):
    user_id: NonEmptyStr
    memory_key: NonEmptyStr
    corrected_content: NonEmptyStr
    truth_type: NonEmptyStr
    subject: OptionalNonEmptyStr = None
    relation: OptionalNonEmptyStr = None
    object: OptionalNonEmptyStr = None


class MemoryDeleteRequest(APIModel):
    user_id: NonEmptyStr
    memory_key: NonEmptyStr
    reason: NonEmptyStr


class MemoryGovernanceBlockRequest(APIModel):
    user_id: NonEmptyStr
    content_class: NonEmptyStr
    blocked: bool


def api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(error=ApiErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
