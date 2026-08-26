"""Object storage helpers for durable dataset files."""

from pathlib import Path

import pytest

from app.services.object_storage import (
    cache_path_for,
    ensure_local_file,
    sanitize_storage_key,
)


def test_sanitize_storage_key_rejects_traversal():
    with pytest.raises(ValueError):
        sanitize_storage_key("../etc/passwd")


def test_ensure_local_file_reads_existing_disk_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    f = tmp_path / "sample.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    path = ensure_local_file({"file_path": str(f), "format": "csv"})
    assert path == f
    assert path.read_text(encoding="utf-8").startswith("a,b")


def test_ensure_local_file_missing_local_explains_redeploy(tmp_path: Path):
    missing = tmp_path / "gone.csv"
    with pytest.raises(FileNotFoundError, match="redeploy|Re-upload|missing"):
        ensure_local_file({"file_path": str(missing), "format": "csv"})


def test_cache_path_keeps_user_prefix(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    # Settings were already loaded — patch cache_dir via upload_dir on settings.
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    path = cache_path_for("user_3/abc_sales.csv")
    assert path.name == "abc_sales.csv"
    assert "user_3" in str(path)
