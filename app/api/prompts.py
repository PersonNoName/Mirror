"""Prompt template API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.models import ApiErrorResponse, PromptTemplateListResponse, PromptTemplateResponse, api_error_response
from app.prompts import get_prompt_template, load_prompt_templates


router = APIRouter(tags=["prompts"])


@router.get(
    "/prompts",
    response_model=PromptTemplateListResponse,
)
async def list_prompt_templates() -> PromptTemplateListResponse:
    prompts = load_prompt_templates()
    items = [PromptTemplateResponse(key=key, content=value) for key, value in sorted(prompts.items())]
    return PromptTemplateListResponse(items=items, count=len(items))


@router.get(
    "/prompts/{key}",
    response_model=PromptTemplateResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def get_prompt_by_key(key: str):
    try:
        content = get_prompt_template(key)
    except KeyError:
        return api_error_response(
            status_code=404,
            code="prompt_not_found",
            message="No prompt template exists for the provided key.",
            details={"key": key},
        )
    return PromptTemplateResponse(key=key, content=content)
