"""Tests for ``memgentic migrate-storage`` CLI command.

Covers:
- sqlite_vec → sqlite_vec (exercises the wiring with a shared SQLite file)
- sqlite_vec → sqlite_vec with --dry-run (no writes)
- --force override when destination already has data
- all_points() unit tests on SqliteVecBackend directly

Design note: CLI tests are *synchronous* (no ``async def``) so that
``asyncio.run()`` inside the command works — pytest-asyncio's running event
loop would block a second ``asyncio.run()`` call. Async helpers use
``asyncio.run()`` directly for the same reason.
"""

from __future__ import annotations

import asyncio
import struct
import uuid

import pytest
from click.testing import CliRunner

from memgentic.cli import main
from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.storage.metadata import MetadataStore

pytest.importorskip("sqlite_vec", reason="sqlite-vec optional extra not installed")

from memgentic.storage.backends.sqlite_vec import SqliteVecBackend  # noqa: E402

DIMS = 8  # small, fast


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.01 for i in range(DIMS)]


def _make_memory(content: str = "test memory", mid: str | None = None) -> Memory:
    return Memory(
        id=mid or str(uuid.uuid4()),
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
    )


def _settings(tmp_path, dims: int = DIMS) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.SQLITE_VEC,
        embedding_dimensions=dims,
        # Silence Qdrant connection attempts
        qdrant_url="http://localhost:1",
    )


async def _seed_backend_async(
    settings: MemgenticSettings,
    memories: list[Memory],
    embeddings: list[list[float]],
) -> None:
    """Insert memories into an sqlite-vec backend and also persist to metadata."""
    backend = SqliteVecBackend(settings)
    try:
        await backend.initialize()
    except Exception as exc:
        pytest.skip(f"sqlite-vec could not load: {exc}")

    metadata_store = MetadataStore(settings.sqlite_path)
    await metadata_store.initialize()

    try:
        for mem in memories:
            await metadata_store.save_memory(mem)
        await backend.upsert_memories_batch(memories, embeddings)
    finally:
        await metadata_store.close()
        await backend.close()


def _seed_backend(
    settings: MemgenticSettings,
    memories: list[Memory],
    embeddings: list[list[float]],
) -> None:
    asyncio.run(_seed_backend_async(settings, memories, embeddings))


async def _read_all_points_async(settings: MemgenticSettings) -> dict[str, list[float]]:
    """Return {id: embedding} for every point in an sqlite-vec backend."""
    backend = SqliteVecBackend(settings)
    try:
        await backend.initialize()
    except Exception as exc:
        pytest.skip(f"sqlite-vec could not load: {exc}")
    result = {}
    async for mid, emb in backend.all_points():
        result[mid] = emb
    await backend.close()
    return result


def _read_all_points(settings: MemgenticSettings) -> dict[str, list[float]]:
    return asyncio.run(_read_all_points_async(settings))


def _cli_env(tmp_path) -> dict[str, str]:
    return {
        "MEMGENTIC_DATA_DIR": str(tmp_path / "data"),
        "MEMGENTIC_STORAGE_BACKEND": "sqlite_vec",
        "MEMGENTIC_EMBEDDING_DIMENSIONS": str(DIMS),
        "MEMGENTIC_QDRANT_URL": "http://localhost:1",
    }


# ---------------------------------------------------------------------------
# CLI Tests  (sync — so asyncio.run() inside the command works fine)
# ---------------------------------------------------------------------------


class TestMigrateStorageSqliteVecToSqliteVec:
    """sqlite_vec → sqlite_vec: exercises the whole wiring end-to-end."""

    def test_all_ids_present_in_destination(self, tmp_path):
        """Every id from source appears in destination after migration."""
        settings = _settings(tmp_path)

        memories = [_make_memory(f"memory {i}") for i in range(3)]
        embeddings = [_embedding(seed=0.1 * (i + 1)) for i in range(3)]
        _seed_backend(settings, memories, embeddings)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "migrate-storage",
                "--from",
                "sqlite_vec",
                "--to",
                "sqlite_vec",
                "--force",  # destination already seeded above
            ],
            catch_exceptions=False,
            env=_cli_env(tmp_path),
        )
        assert result.exit_code == 0, result.output

        dest_points = _read_all_points(settings)
        src_ids = {m.id for m in memories}
        assert src_ids.issubset(dest_points.keys()), f"Missing ids: {src_ids - dest_points.keys()}"

    def test_embeddings_match_within_fp_precision(self, tmp_path):
        """Embeddings in destination match source to float32 precision."""
        settings = _settings(tmp_path)

        memories = [_make_memory("precise embedding test")]
        seed = 0.123456789
        embeddings = [_embedding(seed=seed)]
        _seed_backend(settings, memories, embeddings)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["migrate-storage", "--from", "sqlite_vec", "--to", "sqlite_vec", "--force"],
            catch_exceptions=False,
            env=_cli_env(tmp_path),
        )
        assert result.exit_code == 0, result.output

        dest_points = _read_all_points(settings)
        mem_id = memories[0].id
        assert mem_id in dest_points

        dest_emb = dest_points[mem_id]
        # Round-trip through float32 to get the expected precision floor.
        expected = list(struct.unpack(f"<{DIMS}f", struct.pack(f"<{DIMS}f", *embeddings[0])))
        for got, exp in zip(dest_emb, expected, strict=True):
            assert abs(got - exp) < 1e-6, f"Embedding mismatch: {got} vs {exp}"


class TestDryRun:
    """--dry-run must not write any vectors."""

    def test_dry_run_writes_nothing(self, tmp_path):
        """After --dry-run, the backend's point count stays the same."""
        settings = _settings(tmp_path)

        memories = [_make_memory("dry run test")]
        embeddings = [_embedding()]
        _seed_backend(settings, memories, embeddings)

        # Count how many points exist before the dry-run
        before = _read_all_points(settings)
        pre_count = len(before)
        assert pre_count >= 1

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["migrate-storage", "--from", "sqlite_vec", "--to", "sqlite_vec", "--dry-run"],
            catch_exceptions=False,
            env=_cli_env(tmp_path),
        )
        assert result.exit_code == 0, result.output
        assert "dry run" in result.output.lower() or "Dry run" in result.output

        # Point count must be unchanged (no writes happened)
        after = _read_all_points(settings)
        assert len(after) == pre_count


class TestForceFlag:
    """--force allows overwriting a non-empty destination."""

    def test_refuses_without_force_when_destination_has_data(self, tmp_path):
        """Without --force the command exits cleanly with a refusal message."""
        settings = _settings(tmp_path)

        memories = [_make_memory("pre-existing")]
        embeddings = [_embedding()]
        _seed_backend(settings, memories, embeddings)

        runner = CliRunner()
        result = runner.invoke(
            main,
            # No --force: destination is non-empty → should refuse
            ["migrate-storage", "--from", "sqlite_vec", "--to", "sqlite_vec"],
            catch_exceptions=False,
            env=_cli_env(tmp_path),
        )
        # Command exits cleanly (exit 0) but prints a refusal message
        assert result.exit_code == 0, result.output
        output_lower = result.output.lower()
        assert "force" in output_lower or "already contains" in output_lower

    def test_succeeds_with_force(self, tmp_path):
        """With --force the command copies everything even when dest has data."""
        settings = _settings(tmp_path)

        memories = [_make_memory(f"force test {i}") for i in range(2)]
        embeddings = [_embedding(seed=0.2 * (i + 1)) for i in range(2)]
        _seed_backend(settings, memories, embeddings)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["migrate-storage", "--from", "sqlite_vec", "--to", "sqlite_vec", "--force"],
            catch_exceptions=False,
            env=_cli_env(tmp_path),
        )
        assert result.exit_code == 0, result.output
        output_lower = result.output.lower()
        assert "complete" in output_lower or "migrat" in output_lower

        dest_points = _read_all_points(settings)
        for mem in memories:
            assert mem.id in dest_points


# ---------------------------------------------------------------------------
# Unit tests for all_points() on SqliteVecBackend  (async — fine here)
# ---------------------------------------------------------------------------


class TestAllPoints:
    """Unit tests for the all_points() method on SqliteVecBackend directly."""

    async def test_all_points_empty(self, tmp_path):
        backend = SqliteVecBackend(_settings(tmp_path))
        try:
            await backend.initialize()
        except Exception as exc:
            pytest.skip(f"sqlite-vec could not load: {exc}")
        points = [p async for p in backend.all_points()]
        await backend.close()
        assert points == []

    async def test_all_points_returns_correct_ids_and_embeddings(self, tmp_path):
        settings = _settings(tmp_path)
        backend = SqliteVecBackend(settings)
        try:
            await backend.initialize()
        except Exception as exc:
            pytest.skip(f"sqlite-vec could not load: {exc}")

        memories = [_make_memory(f"point {i}") for i in range(3)]
        embeddings = [_embedding(seed=0.1 + i * 0.05) for i in range(3)]
        await backend.upsert_memories_batch(memories, embeddings)

        points = {mid: emb async for mid, emb in backend.all_points()}
        await backend.close()

        assert set(points.keys()) == {m.id for m in memories}
        for mem, orig_emb in zip(memories, embeddings, strict=True):
            got = points[mem.id]
            # float32 round-trip is the precision floor
            expected = list(struct.unpack(f"<{DIMS}f", struct.pack(f"<{DIMS}f", *orig_emb)))
            for g, e in zip(got, expected, strict=True):
                assert abs(g - e) < 1e-6
