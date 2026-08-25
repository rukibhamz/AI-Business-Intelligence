import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_admin
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
    ensure_providers,
    get_ai_runtime,
    load_app_settings,
    member_settings_view,
    public_settings_view,
    save_app_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsPublic)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Branding for everyone; provider configuration for admins only."""
    data = await load_app_settings(db)
    view = public_settings_view(data)
    if not current_user.is_admin:
        return member_settings_view(view)
    return view


@router.put("", response_model=AppSettingsPublic)
async def update_settings(
    payload: AppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    updates = payload.model_dump(exclude_unset=True)
    try:
        data = await save_app_settings(db, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return public_settings_view(data)


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    payload: ConnectionTestRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> ConnectionTestResponse:
    try:
        return await _run_connection_test(payload, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Connection test failed: {exc}",
        ) from exc


async def _run_connection_test(
    payload: ConnectionTestRequest,
    db: AsyncSession,
) -> ConnectionTestResponse:
    data = await load_app_settings(db)
    providers = ensure_providers(data)

    api_key = payload.openai_api_key or ""
    if api_key and set(api_key) <= {"•", "."}:
        api_key = ""

    provider = payload.llm_provider
    model = payload.openai_model
    base_url = payload.openai_base_url
    label = provider or "provider"

    if payload.provider_id:
        match = next((p for p in providers if p["id"] == payload.provider_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Provider profile not found")
        api_key = api_key or str(match.get("api_key") or "")
        provider = provider or str(match.get("provider") or "openai")
        model = model or str(match.get("model") or "")
        base_url = base_url or str(match.get("base_url") or "")
        label = str(match.get("label") or provider)
    else:
        runtime = await get_ai_runtime(db)
        api_key = api_key or runtime["api_key"]
        provider = provider or runtime["provider"]
        model = model or runtime["model"]
        base_url = base_url or runtime["base_url"]
        label = runtime.get("label") or provider

    if not base_url and provider in PROVIDER_PRESETS:
        base_url = PROVIDER_PRESETS[provider]["base_url"]
    if not model and provider in PROVIDER_PRESETS:
        model = PROVIDER_PRESETS[provider]["default_model"]

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is not configured for this provider. Paste a key and try again.",
        )
    if not base_url:
        raise HTTPException(status_code=400, detail="API base URL is required")
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required")

    if provider == "anthropic" and "anthropic.com" in base_url and "compatible" not in base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Anthropic native API is not OpenAI-compatible. "
                "Set Base URL to an OpenAI-compatible gateway (e.g. OpenRouter) "
                "or use OpenAI / Groq / Gemini / Mistral instead."
            ),
        )

    url = f"{base_url.rstrip('/')}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                url,
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
                detail = res.text[:400]
                raise HTTPException(
                    status_code=400,
                    detail=f"{label} returned HTTP {res.status_code}: {detail}",
                )
            body = res.json()
            reply = ""
            try:
                reply = str(body["choices"][0]["message"]["content"]).strip()
            except (KeyError, IndexError, TypeError, ValueError):
                reply = ""
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Timed out reaching {base_url}. Check the base URL and network.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connection failed: {exc}") from exc

    suffix = f" - model replied: {reply[:40]}" if reply else ""
    return ConnectionTestResponse(
        ok=True,
        message=f"Connected to {label} ({provider} / {model}){suffix}",
    )


@router.post("/logo", response_model=AppSettingsPublic)
async def upload_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
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
    _: User = Depends(require_admin),
) -> dict:
    dest_dir = branding_upload_dir()
    for old in dest_dir.glob("logo.*"):
        old.unlink(missing_ok=True)
    data = await save_app_settings(db, {"logo_url": None})
    return public_settings_view(data)
