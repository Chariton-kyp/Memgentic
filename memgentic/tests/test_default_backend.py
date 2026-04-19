"""Tests for the sqlite_vec default storage-backend change (v0.6.0).

Covers:
  - Default MemgenticSettings uses SQLITE_VEC.
  - Legacy Qdrant data detection warning fires when the old Qdrant dir exists
    but the sqlite-vec DB is empty (first start after upgrade).
  - Warning is suppressed when the sqlite-vec DB already has data.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from memgentic.config import MemgenticSettings, StorageBackend


class TestDefaultStorageBackend:
    def test_default_is_sqlite_vec(self, tmp_path: Path):
        """MemgenticSettings() without overrides must default to SQLITE_VEC."""
        settings = MemgenticSettings(data_dir=tmp_path / "data")
        assert settings.storage_backend == StorageBackend.SQLITE_VEC

    def test_can_override_to_local(self, tmp_path: Path):
        """Explicit LOCAL override still works for users keeping Qdrant."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
        )
        assert settings.storage_backend == StorageBackend.LOCAL

    def test_can_override_to_qdrant(self, tmp_path: Path):
        """Explicit QDRANT override still works for server mode."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.QDRANT,
        )
        assert settings.storage_backend == StorageBackend.QDRANT


class TestLegacyQdrantMigrationWarning:
    """VectorStore._warn_if_legacy_qdrant_data() detection logic."""

    def _make_settings(self, tmp_path: Path) -> MemgenticSettings:
        return MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.SQLITE_VEC,
            embedding_dimensions=8,
        )

    def _get_store(self, settings: MemgenticSettings):
        from memgentic.storage.vectors import VectorStore

        return VectorStore(settings)

    def test_warning_fires_when_qdrant_dir_exists_and_db_empty(
        self, tmp_path: Path, capsys
    ):
        """When old Qdrant dir exists and sqlite DB is tiny, warning is emitted."""
        settings = self._make_settings(tmp_path)
        # Create the legacy Qdrant directory (simulates 0.4.x/0.5.0 install)
        settings.qdrant_local_path.mkdir(parents=True)
        # sqlite DB either absent or very small — don't create it (absent case)

        store = self._get_store(settings)

        with patch("rich.console.Console.print"):  # suppress Rich console in tests
            store._warn_if_legacy_qdrant_data()

        # structlog emits to stdout by default in tests
        captured = capsys.readouterr()
        assert "legacy_qdrant_data_detected" in captured.out, (
            "Expected a structlog warning about legacy Qdrant data"
        )

    def test_warning_fires_with_tiny_db(self, tmp_path: Path, capsys):
        """Warning fires even when the DB exists but is under the 100 KB threshold."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        # Write a tiny DB (just a few bytes — schema-only, no memories)
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        settings.sqlite_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 48)

        store = self._get_store(settings)

        with patch("rich.console.Console.print"):
            store._warn_if_legacy_qdrant_data()

        captured = capsys.readouterr()
        assert "legacy_qdrant_data_detected" in captured.out

    def test_warning_suppressed_when_db_has_data(self, tmp_path: Path, capsys):
        """No warning when sqlite DB is above 100 KB — user already has data there."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        # Write a large-ish fake DB (> 100 KB)
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        settings.sqlite_path.write_bytes(b"\x00" * 110_000)

        store = self._get_store(settings)
        store._warn_if_legacy_qdrant_data()

        captured = capsys.readouterr()
        assert "legacy_qdrant_data_detected" not in captured.out, (
            "Warning should be suppressed when DB already has data"
        )

    def test_no_warning_when_qdrant_dir_absent(self, tmp_path: Path, capsys):
        """No warning when the old Qdrant directory doesn't exist (clean install)."""
        settings = self._make_settings(tmp_path)
        # qdrant_local_path NOT created

        store = self._get_store(settings)
        store._warn_if_legacy_qdrant_data()

        captured = capsys.readouterr()
        assert "legacy_qdrant_data_detected" not in captured.out, (
            "No warning expected for a clean install"
        )
