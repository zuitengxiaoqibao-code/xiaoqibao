from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from qibao_api.settings_repository import (
    AISettings,
    AISettingsRepository,
    EffectiveAISettingsResolver,
)


# Local-admin trust boundary: the application binds locally and intentionally supports
# localhost/private OpenAI-compatible providers. Deployment authentication is out of scope here.
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class AISettingsView(BaseModel):
    configured: bool
    base_url: str | None
    model: str | None
    api_key_hint: str | None


def get_ai_settings_repository(request: Request) -> AISettingsRepository:
    return request.app.state.ai_settings_repository


def get_effective_ai_settings(request: Request) -> EffectiveAISettingsResolver:
    return request.app.state.effective_ai_settings


def _view(settings: AISettings | object) -> AISettingsView:
    if not isinstance(settings, AISettings):
        return AISettingsView(
            configured=False, base_url=None, model=None, api_key_hint=None
        )
    visible_count = min(4, max(0, len(settings.api_key) - 1))
    suffix = settings.api_key[-visible_count:] if visible_count else ""
    return AISettingsView(
        configured=True,
        base_url=settings.base_url,
        model=settings.model,
        api_key_hint=f"****{suffix}",
    )


@router.get("/ai", response_model=AISettingsView)
def get_ai_settings(
    settings: Annotated[EffectiveAISettingsResolver, Depends(get_effective_ai_settings)],
) -> AISettingsView:
    return _view(settings.resolve())


@router.put("/ai", response_model=AISettingsView)
async def put_ai_settings(
    request: Request,
    repository: Annotated[AISettingsRepository, Depends(get_ai_settings_repository)],
) -> AISettingsView:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"base_url", "model", "api_key"}:
            raise ValueError("invalid shape")
        if not all(isinstance(payload[field], str) for field in payload):
            raise ValueError("invalid types")
        settings = AISettings(**payload)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail="Invalid AI settings") from error
    repository.save(settings)
    return _view(settings)


@router.delete("/ai", response_model=AISettingsView)
def delete_ai_settings(
    repository: Annotated[AISettingsRepository, Depends(get_ai_settings_repository)],
    settings: Annotated[EffectiveAISettingsResolver, Depends(get_effective_ai_settings)],
) -> AISettingsView:
    repository.delete()
    return _view(settings.resolve())
