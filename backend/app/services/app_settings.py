from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AppConfig

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-latest",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
    },
}

COLOR_SCHEMES: dict[str, dict[str, str]] = {
    "cobalt": {
        "primary": "#2036bd",
        "primary_container": "#3e52d5",
        "secondary": "#4648d4",
        "secondary_container": "#6063ee",
        "label": "Cobalt Indigo",
    },
    "slate": {
        "primary": "#334155",
        "primary_container": "#475569",
        "secondary": "#0f766e",
        "secondary_container": "#14b8a6",
        "label": "Slate & Teal",
    },
    "forest": {
        "primary": "#166534",
        "primary_container": "#15803d",
        "secondary": "#1e3a5f",
        "secondary_container": "#2563eb",
        "label": "Forest",
    },
    "copper": {
        "primary": "#9a3412",
        "primary_container": "#c2410c",
        "secondary": "#44403c",
        "secondary_container": "#78716c",
        "label": "Copper",
    },
}

DEFAULTS: dict[str, Any] = {
    "llm_provider": "openai",
    "openai_model": settings.openai_model or "gpt-4o-mini",
    "openai_api_key": settings.openai_api_key or "",
    "openai_base_url": settings.openai_base_url or "https://api.openai.com/v1",
    "platform_name": "Cognitive Logic",
    "platform_tagline": "Business Intelligence",
    "logo_url": None,
    "color_scheme": "cobalt",
}


def _mask_key(key: str) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:3]}{'•' * 24}{key[-4:]}"


async def _get_or_create_row(db: AsyncSession) -> AppConfig:
    row = await db.get(AppConfig, 1)
    if row:
        return row
    row = AppConfig(id=1, data_json=json.dumps({}))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _merge(raw: dict[str, Any]) -> dict[str, Any]:
    data = {**DEFAULTS}
    for k, v in raw.items():
        if k == "logo_url":
            data[k] = v
        elif v is not None:
            data[k] = v
    return data


async def load_app_settings(db: AsyncSession) -> dict[str, Any]:
    row = await _get_or_create_row(db)
    try:
        raw = json.loads(row.data_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return _merge(raw)


async def save_app_settings(db: AsyncSession, updates: dict[str, Any]) -> dict[str, Any]:
    row = await _get_or_create_row(db)
    try:
        current = json.loads(row.data_json or "{}")
    except json.JSONDecodeError:
        current = {}
    if not isinstance(current, dict):
        current = {}

    for key, value in updates.items():
        if key == "openai_api_key":
            if value is None or value == "" or set(str(value)) <= {"•", "."}:
                continue
            current[key] = value
            continue
        if key == "logo_url":
            current[key] = value  # allow None to clear
            continue
        if value is None:
            continue
        current[key] = value

    # Apply provider preset base URL when provider changes and no explicit base_url in updates
    if "llm_provider" in updates and updates["llm_provider"] is not None:
        if "openai_base_url" not in updates or updates.get("openai_base_url") in (None, ""):
            preset = PROVIDER_PRESETS.get(str(updates["llm_provider"]))
            if preset:
                current["openai_base_url"] = preset["base_url"]
                if "openai_model" not in updates or not updates.get("openai_model"):
                    current["openai_model"] = preset["default_model"]

    row.data_json = json.dumps(current)
    await db.commit()
    await db.refresh(row)
    return _merge(current)


def public_settings_view(data: dict[str, Any]) -> dict[str, Any]:
    key = data.get("openai_api_key") or ""
    return {
        "llm_provider": data.get("llm_provider", "openai"),
        "openai_model": data.get("openai_model", ""),
        "openai_base_url": data.get("openai_base_url", ""),
        "api_key_set": bool(key),
        "api_key_masked": _mask_key(key),
        "platform_name": data.get("platform_name", "Cognitive Logic"),
        "platform_tagline": data.get("platform_tagline", "Business Intelligence"),
        "logo_url": data.get("logo_url"),
        "color_scheme": data.get("color_scheme", "cobalt"),
        "color_schemes": [
            {"id": sid, **meta} for sid, meta in COLOR_SCHEMES.items()
        ],
        "providers": list(PROVIDER_PRESETS.keys()),
    }


async def get_ai_runtime(db: AsyncSession) -> dict[str, str]:
    data = await load_app_settings(db)
    return {
        "api_key": str(data.get("openai_api_key") or ""),
        "model": str(data.get("openai_model") or settings.openai_model),
        "base_url": str(data.get("openai_base_url") or settings.openai_base_url),
        "provider": str(data.get("llm_provider") or "openai"),
    }


def branding_upload_dir() -> Path:
    path = Path(settings.upload_dir) / "branding"
    path.mkdir(parents=True, exist_ok=True)
    return path
