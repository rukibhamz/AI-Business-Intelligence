import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import (
    AppSettingsPublic,
    AppSettingsUpdate,
    ConnectionTestRequest,
    ConnectionTestResponse,
)
from app.services.app_settings import (
    PROVIDER_PRESETS,
    branding_upload_dir,
    get_ai_runtime,
    load_app_settings,
    public_settings_view,
    save_app_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsPublic)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    data = await load_app_settings(db)
    return public_settings_view(data)


@router.put("", response_model=AppSettingsPublic)
async def update_settings(
    payload: AppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    data = await save_app_settings(db, updates)
    return public_settings_view(data)


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ConnectionTestRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ConnectionTestResponse:
    runtime = await get_ai_runtime(db)
    api_key = payload.api_key or runtime["api_key"]
    if payload.api_key and set(payload.api_key) <= {"•", "."}:
        api_key = runtime["api_key"]

    provider = payload.llm_provider or runtime["provider"]
    model = payload.openai_model or runtime["model"]
    base_url = payload.openai_base_url or runtime["base_url"]
    if not payload.openai_base_url and provider in PROVIDER_PRESETS:
        base_url = PROVIDER_PRESETS[provider]["base_url"]

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is not configured")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "Reply with OK"}],
                },
            )
            if res.status_code >= 400:
                detail = res.text[:300]
                raise HTTPException(
                    status_code=400,
                    detail=f"Provider returned {res.status_code}: {detail}",
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ConnectionTestResponse(ok=True, message=f"Connected to {provider} ({model})")


@router.post("/logo", response_model=AppSettingsPublic)
async def upload_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise HTTPException(status_code=400, detail="Logo must be png, jpg, webp, or svg")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 2_000_000:
        raise HTTPException(status_code=400, detail="Logo must be under 2MB")

    dest_dir = branding_upload_dir()
    # Clear previous logos
    for old in dest_dir.glob("logo.*"):
        old.unlink(missing_ok=True)

    name = f"logo{ext}"
    path = dest_dir / name
    path.write_bytes(content)

    # cache-bust query
    logo_url = f"/api/settings/logo?v={uuid.uuid4().hex[:8]}"
    data = await save_app_settings(db, {"logo_url": logo_url})
    return public_settings_view(data)


# Route order: static logo before parameterized paths is fine under /settings
@router.get("/logo")
async def get_logo() -> FileResponse:
    dest_dir = branding_upload_dir()
    matches = list(dest_dir.glob("logo.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    path = matches[0]
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)


@router.delete("/logo", response_model=AppSettingsPublic)
async def delete_logo(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    dest_dir = branding_upload_dir()
    for old in dest_dir.glob("logo.*"):
        old.unlink(missing_ok=True)
    data = await save_app_settings(db, {"logo_url": None})
    return public_settings_view(data)
