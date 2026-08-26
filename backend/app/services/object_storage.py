"""Durable dataset files via Supabase Storage (with a local disk fallback).

Hosted APIs often wipe local disks on redeploy. When
`SUPABASE_SERVICE_ROLE_KEY` is set, uploads go to a private Storage bucket and
are pulled into a local cache only when a query needs the bytes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._/-]+")


def storage_enabled() -> bool:
    return bool(
        settings.supabase_url.strip()
        and settings.supabase_service_role_key.strip()
        and settings.supabase_storage_bucket.strip()
    )


def _api_root() -> str:
    return f"{settings.supabase_url.rstrip('/')}/storage/v1"


def _headers(*, content_type: str | None = None) -> dict[str, str]:
    key = settings.supabase_service_role_key.strip()
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def sanitize_storage_key(key: str) -> str:
    cleaned = _SAFE_SEGMENT.sub("_", key.strip().lstrip("/"))
    if not cleaned or ".." in cleaned.split("/"):
        raise ValueError("Invalid storage key")
    return cleaned


def cache_dir() -> Path:
    path = Path(settings.upload_dir) / ".storage_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_path_for(storage_key: str) -> Path:
    safe = sanitize_storage_key(storage_key)
    # Keep folder structure under the cache so keys stay unique per user.
    dest = cache_dir() / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def content_type_for(filename: str, file_format: str) -> str:
    if file_format == "xlsx" or filename.lower().endswith((".xlsx", ".xls")):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "text/csv"


def upload_bytes(storage_key: str, content: bytes, *, content_type: str) -> None:
    """Put an object in the configured bucket. Overwrites if the key exists."""
    if not storage_enabled():
        raise RuntimeError("Object storage is not configured")
    key = sanitize_storage_key(storage_key)
    bucket = settings.supabase_storage_bucket.strip()
    url = f"{_api_root()}/object/{bucket}/{key}"
    with httpx.Client(timeout=120.0) as client:
        res = client.post(
            url,
            headers={
                **_headers(content_type=content_type),
                "x-upsert": "true",
            },
            content=content,
        )
        if res.status_code in (200, 201):
            return
        # Some projects prefer PUT for upsert.
        if res.status_code in (400, 409):
            put = client.put(
                url,
                headers=_headers(content_type=content_type),
                content=content,
            )
            if put.status_code in (200, 201):
                return
            res = put
        raise RuntimeError(
            f"Supabase Storage upload failed ({res.status_code}): {res.text[:300]}"
        )


def download_bytes(storage_key: str) -> bytes:
    if not storage_enabled():
        raise RuntimeError("Object storage is not configured")
    key = sanitize_storage_key(storage_key)
    bucket = settings.supabase_storage_bucket.strip()
    url = f"{_api_root()}/object/{bucket}/{key}"
    with httpx.Client(timeout=120.0) as client:
        res = client.get(url, headers=_headers())
        if res.status_code != 200:
            raise FileNotFoundError(
                f"Dataset not found in Supabase Storage ({res.status_code}). "
                "Re-upload the file under Data Sources."
            )
        return res.content


def delete_object(storage_key: str) -> None:
    if not storage_enabled():
        return
    key = sanitize_storage_key(storage_key)
    bucket = settings.supabase_storage_bucket.strip()
    url = f"{_api_root()}/object/{bucket}/{key}"
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.delete(url, headers=_headers())
            if res.status_code not in (200, 204, 404):
                logger.warning(
                    "Supabase Storage delete returned %s: %s",
                    res.status_code,
                    res.text[:200],
                )
    except Exception:
        logger.exception("Failed to delete storage object %s", key)


def ensure_local_file(config: dict) -> Path:
    """Return a readable local path, downloading from Storage when needed."""
    storage_key = (config.get("storage_key") or "").strip()
    backend = (config.get("storage_backend") or "").strip().lower()
    uses_storage = backend == "supabase" or bool(storage_key)

    if uses_storage and storage_key:
        if not storage_enabled():
            raise FileNotFoundError(
                "This dataset lives in Supabase Storage, but "
                "SUPABASE_SERVICE_ROLE_KEY is not set on the API. "
                "Add it on Render (or your host), then retry."
            )
        dest = cache_path_for(storage_key)
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        data = download_bytes(storage_key)
        dest.write_bytes(data)
        return dest

    raw = config.get("file_path")
    if not raw:
        raise FileNotFoundError(
            "Dataset has no file path. Re-upload it under Data Sources."
        )
    path = Path(raw)
    if path.exists():
        return path

    raise FileNotFoundError(
        "Dataset file is missing from this server (common after a redeploy "
        "when uploads are only on local disk). Delete the broken source and "
        "re-upload the file after enabling Supabase Storage — see "
        "docs/DEPLOYMENT.md."
    )


def remove_dataset_files(config: dict) -> None:
    """Delete local cache/disk copy and the Storage object, if any."""
    storage_key = (config.get("storage_key") or "").strip()
    if storage_key:
        delete_object(storage_key)
        cache = cache_path_for(storage_key)
        cache.unlink(missing_ok=True)

    file_path = config.get("file_path")
    if file_path:
        Path(file_path).unlink(missing_ok=True)
