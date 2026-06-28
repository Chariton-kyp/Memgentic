"""Tests for the storage-backend default and legacy migration warning.

Covers:
  - Default MemgenticSettings uses QDRANT (server mode) — changed in W6a.
  - Explicit overrides to LOCAL and SQLITE_VEC still work.
  - Legacy Qdrant data detection warning fires when the old Qdrant dir exists
    and the live vector store has materially fewer vectors than active memories.
  - Warning is suppressed when counts match (fully migrated).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from memgentic.config import MemgenticSettings, StorageBackend


class TestDefaultStorageBackend:
    def test_default_is_qdrant(self, tmp_path: Path):
        """MemgenticSettings() without overrides must default to QDRANT (server mode).

        Changed in W6a: previous default was SQLITE_VEC. Existing installs that
        relied on the zero-config sqlite-vec backend must set
        MEMGENTIC_STORAGE_BACKEND=sqlite_vec explicitly.
        """
        settings = MemgenticSettings(data_dir=tmp_path / "data")
        assert settings.storage_backend == StorageBackend.QDRANT

    def test_can_override_to_sqlite_vec(self, tmp_path: Path):
        """Explicit SQLITE_VEC override still works for zero-config mode."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.SQLITE_VEC,
        )
        assert settings.storage_backend == StorageBackend.SQLITE_VEC

    def test_can_override_to_local(self, tmp_path: Path):
        """Explicit LOCAL override still works for file-based Qdrant."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
        )
        assert settings.storage_backend == StorageBackend.LOCAL


class TestLegacyQdrantMigrationWarning:
    """VectorStore legacy-Qdrant detection (RC1 fix: count-based, not DB-size).

    The previous guard silenced itself whenever the SQLite DB exceeded 100 KB,
    which hid the notice for every *established* user — exactly the population
    with stranded curated vectors. The new guard fires on a population gap:
    the live vector store holds materially fewer rows than there are active
    memories.
    """

    def _make_settings(self, tmp_path: Path) -> MemgenticSettings:
        return MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.SQLITE_VEC,
            embedding_dimensions=8,
        )

    def _get_store(self, settings: MemgenticSettings):
        from memgentic.storage.vectors import VectorStore

        return VectorStore(settings)

    # --- pure predicate ---------------------------------------------------

    def test_predicate_warns_when_vectors_below_memories(self, tmp_path: Path):
        """Stranded vectors (3 of 10) with the legacy dir present → warn."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        assert store._should_warn_legacy_qdrant(vector_count=3, memory_count=10) is True

    def test_predicate_quiet_when_counts_match(self, tmp_path: Path):
        """Every memory has a vector → no warning even with the legacy dir."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        assert store._should_warn_legacy_qdrant(vector_count=10, memory_count=10) is False

    def test_predicate_quiet_within_ten_percent(self, tmp_path: Path):
        """A small in-flight gap (9 of 10) is not material → quiet."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        assert store._should_warn_legacy_qdrant(vector_count=9, memory_count=10) is False

    def test_predicate_quiet_when_no_memories(self, tmp_path: Path):
        """Empty store → nothing to migrate → quiet."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        assert store._should_warn_legacy_qdrant(vector_count=0, memory_count=0) is False

    def test_predicate_quiet_when_qdrant_dir_absent(self, tmp_path: Path):
        """Clean install (no legacy dir) → quiet regardless of counts."""
        settings = self._make_settings(tmp_path)
        # qdrant_local_path intentionally NOT created
        store = self._get_store(settings)
        assert store._should_warn_legacy_qdrant(vector_count=0, memory_count=10) is False

    # --- async emit + throttle -------------------------------------------

    async def test_async_warns_then_throttles(self, tmp_path: Path, capsys):
        """First stranded-detection emits the notice; the second is throttled."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        # Fake a backend reporting 3 vectors and a metadata store with 10 memories.
        store._backend = AsyncMock()
        store._backend.get_collection_info.return_value = {"points_count": 3}
        metadata_store = AsyncMock()
        metadata_store.get_filtered_count.return_value = 10

        with patch("rich.console.Console.print"):  # suppress Rich console
            await store._maybe_warn_legacy_qdrant_data(metadata_store)
        first = capsys.readouterr()
        assert "legacy_qdrant_data_detected" in first.out

        with patch("rich.console.Console.print"):
            await store._maybe_warn_legacy_qdrant_data(metadata_store)
        second = capsys.readouterr()
        assert "legacy_qdrant_data_detected" not in second.out, (
            "Second call within the throttle window must stay quiet"
        )

    async def test_async_quiet_when_fully_migrated(self, tmp_path: Path, capsys):
        """Vector count == memory count → no warning emitted."""
        settings = self._make_settings(tmp_path)
        settings.qdrant_local_path.mkdir(parents=True)
        store = self._get_store(settings)
        store._backend = AsyncMock()
        store._backend.get_collection_info.return_value = {"points_count": 10}
        metadata_store = AsyncMock()
        metadata_store.get_filtered_count.return_value = 10

        await store._maybe_warn_legacy_qdrant_data(metadata_store)
        captured = capsys.readouterr()
        assert "legacy_qdrant_data_detected" not in captured.out
