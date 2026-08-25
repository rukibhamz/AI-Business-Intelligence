from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AppConfig

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        # Official Anthropic is Messages API; use an OpenAI-compatible gateway
        # (OpenRouter, etc.) or set a custom base URL that speaks /chat/completions.
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
    "custom": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
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

#: Currencies an admin can pick for every money figure in the product.
#: Naira is the default — this is built for a Nigerian retailer.
CURRENCIES: dict[str, dict[str, str]] = {
    "NGN": {"label": "Nigerian Naira", "symbol": "₦"},
    "USD": {"label": "US Dollar", "symbol": "$"},
    "GBP": {"label": "British Pound", "symbol": "£"},
    "EUR": {"label": "Euro", "symbol": "€"},
    "GHS": {"label": "Ghanaian Cedi", "symbol": "₵"},
    "KES": {"label": "Kenyan Shilling", "symbol": "KSh"},
    "ZAR": {"label": "South African Rand", "symbol": "R"},
    "XOF": {"label": "West African CFA Franc", "symbol": "CFA"},
    "CAD": {"label": "Canadian Dollar", "symbol": "CA$"},
    "AUD": {"label": "Australian Dollar", "symbol": "A$"},
    "INR": {"label": "Indian Rupee", "symbol": "₹"},
    "AED": {"label": "UAE Dirham", "symbol": "AED"},
}

DEFAULT_CURRENCY = "NGN"


DEFAULTS: dict[str, Any] = {
    "llm_provider": "openai",
    "openai_model": settings.openai_model or "gpt-4o-mini",
    "openai_api_key": settings.openai_api_key or "",
    "openai_base_url": settings.openai_base_url or "https://api.openai.com/v1",
    "llm_providers": [],
    "active_provider_id": None,
    "platform_name": "Cognitive Logic",
    "platform_tagline": "Business Intelligence",
    "logo_url": None,
    "color_scheme": "cobalt",
    "currency": DEFAULT_CURRENCY,
}


def _mask_key(key: str) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:3]}{'•' * 24}{key[-4:]}"


def _new_provider_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_provider(raw: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    provider = str(raw.get("provider") or "openai")
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["openai"])
    api_key = str(raw.get("api_key") or "")
    return {
        "id": str(raw.get("id") or _new_provider_id()),
        "label": str(raw.get("label") or f"{provider.title()} #{index + 1}"),
        "provider": provider,
        "model": str(raw.get("model") or preset["default_model"]),
        "base_url": str(raw.get("base_url") or preset["base_url"]),
        "api_key": api_key,
        "priority": int(raw.get("priority") if raw.get("priority") is not None else index + 1),
        "enabled": bool(raw.get("enabled", True)),
    }


def _legacy_as_provider(data: dict[str, Any]) -> dict[str, Any] | None:
    key = str(data.get("openai_api_key") or "")
    model = str(data.get("openai_model") or "")
    base = str(data.get("openai_base_url") or "")
    provider = str(data.get("llm_provider") or "openai")
    if not key and not model and not base:
        return None
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["openai"])
    return _normalize_provider(
        {
            "id": "legacy-default",
            "label": f"{provider.title()} (default)",
            "provider": provider,
            "model": model or preset["default_model"],
            "base_url": base or preset["base_url"],
            "api_key": key,
            "priority": 1,
            "enabled": True,
        }
    )


def ensure_providers(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_list = data.get("llm_providers")
    providers: list[dict[str, Any]] = []
    if isinstance(raw_list, list) and raw_list:
        for i, item in enumerate(raw_list):
            if isinstance(item, dict):
                providers.append(_normalize_provider(item, index=i))
    if not providers:
        legacy = _legacy_as_provider(data)
        if legacy:
            providers = [legacy]
    providers.sort(key=lambda p: (int(p.get("priority") or 99), str(p.get("label") or "")))
    return providers


def sync_legacy_fields(data: dict[str, Any], providers: list[dict[str, Any]], active_id: str | None) -> None:
    """Keep flat legacy keys in sync so older code paths still work."""
    active = None
    if active_id:
        active = next((p for p in providers if p["id"] == active_id), None)
    if active is None:
        enabled = [p for p in providers if p.get("enabled") and p.get("api_key")]
        active = enabled[0] if enabled else (providers[0] if providers else None)
    if not active:
        return
    data["llm_provider"] = active["provider"]
    data["openai_model"] = active["model"]
    data["openai_base_url"] = active["base_url"]
    data["openai_api_key"] = active.get("api_key") or ""
    data["active_provider_id"] = active["id"]


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
    providers = ensure_providers(data)
    data["llm_providers"] = providers
    active_id = data.get("active_provider_id")
    if active_id and not any(p["id"] == active_id for p in providers):
        active_id = providers[0]["id"] if providers else None
    if not active_id and providers:
        active_id = providers[0]["id"]
    data["active_provider_id"] = active_id
    sync_legacy_fields(data, providers, active_id)
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

    # Start from merged view so llm_providers exists
    merged = _merge(current)
    providers = list(merged["llm_providers"])

    for key, value in updates.items():
        if key in ("llm_providers", "active_provider_id"):
            continue
        if key == "openai_api_key":
            if value is None or value == "" or set(str(value)) <= {"•", "."}:
                continue
            current[key] = value
            continue
        if key == "logo_url":
            current[key] = value
            continue
        if value is None:
            continue
        current[key] = value

    if "llm_providers" in updates and updates["llm_providers"] is not None:
        incoming = updates["llm_providers"]
        if not isinstance(incoming, list):
            raise ValueError("llm_providers must be a list")
        existing_by_id = {p["id"]: p for p in providers}
        next_providers: list[dict[str, Any]] = []
        for i, item in enumerate(incoming):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or _new_provider_id())
            prev = existing_by_id.get(pid, {})
            api_key = item.get("api_key")
            if api_key is None or api_key == "" or set(str(api_key)) <= {"•", "."}:
                api_key = prev.get("api_key") or ""
            next_providers.append(
                _normalize_provider(
                    {
                        **item,
                        "id": pid,
                        "api_key": api_key,
                    },
                    index=i,
                )
            )
        providers = next_providers
        current["llm_providers"] = providers

    if "active_provider_id" in updates and updates["active_provider_id"] is not None:
        current["active_provider_id"] = str(updates["active_provider_id"])

    # Legacy single-provider updates: patch the active profile
    legacy_touch = any(
        k in updates and updates[k] is not None
        for k in ("llm_provider", "openai_model", "openai_base_url", "openai_api_key")
    )
    if legacy_touch and "llm_providers" not in updates:
        if not providers:
            providers = [
                _normalize_provider(
                    {
                        "provider": updates.get("llm_provider") or current.get("llm_provider") or "openai",
                        "model": updates.get("openai_model") or current.get("openai_model"),
                        "base_url": updates.get("openai_base_url") or current.get("openai_base_url"),
                        "api_key": updates.get("openai_api_key") or current.get("openai_api_key") or "",
                        "priority": 1,
                        "enabled": True,
                        "label": "Primary",
                    }
                )
            ]
        active_id = current.get("active_provider_id") or (providers[0]["id"] if providers else None)
        for p in providers:
            if p["id"] == active_id:
                if updates.get("llm_provider"):
                    p["provider"] = str(updates["llm_provider"])
                    preset = PROVIDER_PRESETS.get(p["provider"])
                    if preset and (
                        "openai_base_url" not in updates or not updates.get("openai_base_url")
                    ):
                        p["base_url"] = preset["base_url"]
                if updates.get("openai_model"):
                    p["model"] = str(updates["openai_model"])
                if updates.get("openai_base_url"):
                    p["base_url"] = str(updates["openai_base_url"])
                if updates.get("openai_api_key") and set(str(updates["openai_api_key"])) - {"•", "."}:
                    p["api_key"] = str(updates["openai_api_key"])
                break
        current["llm_providers"] = providers

    if "llm_provider" in updates and updates["llm_provider"] is not None:
        if "openai_base_url" not in updates or updates.get("openai_base_url") in (None, ""):
            preset = PROVIDER_PRESETS.get(str(updates["llm_provider"]))
            if preset:
                current["openai_base_url"] = preset["base_url"]
                if "openai_model" not in updates or not updates.get("openai_model"):
                    current["openai_model"] = preset["default_model"]

    merged = _merge(current)
    # Persist secrets from merged providers
    to_store = {k: v for k, v in merged.items() if k != "color_schemes"}
    # Only store serializable provider list with keys
    to_store["llm_providers"] = merged["llm_providers"]
    to_store["active_provider_id"] = merged["active_provider_id"]
    row.data_json = json.dumps(to_store)
    await db.commit()
    await db.refresh(row)
    return merged


def public_provider_view(p: dict[str, Any]) -> dict[str, Any]:
    key = p.get("api_key") or ""
    return {
        "id": p["id"],
        "label": p["label"],
        "provider": p["provider"],
        "model": p["model"],
        "base_url": p["base_url"],
        "priority": p["priority"],
        "enabled": p["enabled"],
        "api_key_set": bool(key),
        "api_key_masked": _mask_key(str(key)),
    }


def public_settings_view(data: dict[str, Any]) -> dict[str, Any]:
    providers = ensure_providers(data)
    active_id = data.get("active_provider_id")
    if active_id and not any(p["id"] == active_id for p in providers):
        active_id = None
    if not active_id and providers:
        active_id = providers[0]["id"]
    key = data.get("openai_api_key") or ""
    if not key and providers:
        key = providers[0].get("api_key") or ""
    return {
        "llm_provider": data.get("llm_provider", "openai"),
        "openai_model": data.get("openai_model", ""),
        "openai_base_url": data.get("openai_base_url", ""),
        "api_key_set": bool(key),
        "api_key_masked": _mask_key(str(key)),
        "llm_providers": [public_provider_view(p) for p in providers],
        "active_provider_id": active_id,
        "platform_name": data.get("platform_name", "Cognitive Logic"),
        "platform_tagline": data.get("platform_tagline", "Business Intelligence"),
        "logo_url": data.get("logo_url"),
        "color_scheme": data.get("color_scheme", "cobalt"),
        "color_schemes": [{"id": sid, **meta} for sid, meta in COLOR_SCHEMES.items()],
        "providers": list(PROVIDER_PRESETS.keys()),
        "currency": _valid_currency(data.get("currency")),
        "currencies": [
            {"code": code, "label": meta["label"], "symbol": meta["symbol"]}
            for code, meta in CURRENCIES.items()
        ],
    }


def _valid_currency(value: Any) -> str:
    code = str(value or "").strip().upper()
    return code if code in CURRENCIES else DEFAULT_CURRENCY


async def get_currency(db) -> str:
    """The currency every money figure should be rendered in."""
    data = await load_app_settings(db)
    return _valid_currency(data.get("currency"))


def pick_runtime_from_providers(
    providers: list[dict[str, Any]],
    active_id: str | None,
) -> dict[str, str] | None:
    ordered = sorted(
        [p for p in providers if p.get("enabled")],
        key=lambda p: (0 if p.get("id") == active_id else 1, int(p.get("priority") or 99)),
    )
    for p in ordered:
        if p.get("api_key"):
            return {
                "api_key": str(p["api_key"]),
                "model": str(p["model"]),
                "base_url": str(p["base_url"]),
                "provider": str(p["provider"]),
                "provider_id": str(p["id"]),
                "label": str(p.get("label") or p["provider"]),
            }
    return None


async def get_ai_runtime(db: AsyncSession) -> dict[str, str]:
    data = await load_app_settings(db)
    providers = ensure_providers(data)
    picked = pick_runtime_from_providers(providers, data.get("active_provider_id"))
    if picked:
        return picked
    return {
        "api_key": str(data.get("openai_api_key") or ""),
        "model": str(data.get("openai_model") or settings.openai_model),
        "base_url": str(data.get("openai_base_url") or settings.openai_base_url),
        "provider": str(data.get("llm_provider") or "openai"),
        "provider_id": str(data.get("active_provider_id") or ""),
        "label": str(data.get("llm_provider") or "openai"),
    }


async def list_failover_runtimes(db: AsyncSession) -> list[dict[str, str]]:
    """Enabled providers with keys, active first then by priority."""
    data = await load_app_settings(db)
    providers = ensure_providers(data)
    active_id = data.get("active_provider_id")
    ordered = sorted(
        [p for p in providers if p.get("enabled") and p.get("api_key")],
        key=lambda p: (0 if p.get("id") == active_id else 1, int(p.get("priority") or 99)),
    )
    return [
        {
            "api_key": str(p["api_key"]),
            "model": str(p["model"]),
            "base_url": str(p["base_url"]),
            "provider": str(p["provider"]),
            "provider_id": str(p["id"]),
            "label": str(p.get("label") or p["provider"]),
        }
        for p in ordered
    ]


def branding_upload_dir() -> Path:
    path = Path(settings.upload_dir) / "branding"
    path.mkdir(parents=True, exist_ok=True)
    return path


#: What a member is allowed to read from settings: the things the app has to
#: render (name, logo, theme, currency). Provider names, models, endpoints and
#: key state are configuration, and configuration is the admin's.
MEMBER_VISIBLE_FIELDS = (
    "platform_name",
    "platform_tagline",
    "logo_url",
    "color_scheme",
    "currency",
)


def member_settings_view(view: dict[str, Any]) -> dict[str, Any]:
    """Strip a settings payload down to what a non-admin needs to render."""
    redacted: dict[str, Any] = {
        "llm_provider": "",
        "openai_model": "",
        "openai_base_url": "",
        "api_key_set": False,
        "api_key_masked": None,
        "llm_providers": [],
        "active_provider_id": None,
        "providers": [],
        "color_schemes": [],
        "currencies": [],
    }
    for field in MEMBER_VISIBLE_FIELDS:
        if field in view:
            redacted[field] = view[field]
    return redacted
