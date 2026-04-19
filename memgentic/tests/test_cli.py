"""Tests for the Memgentic CLI (Click commands)."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from memgentic.cli import main


class TestCLIHelp:
    """Tests for --help output of all commands."""

    def test_version(self):
        from memgentic.__version__ import __version__

        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Universal AI Memory Layer" in result.output

    def test_help_lists_commands(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        for cmd in (
            "serve",
            "daemon",
            "search",
            "sources",
            "remember",
            "import-existing",
            "backup",
            "restore",
            "export-gdpr",
        ):
            assert cmd in result.output, f"Expected command '{cmd}' in help output"

    def test_serve_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "MCP server" in result.output

    def test_serve_help_advertises_watch_flag(self):
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--watch" in result.output
        assert "--no-watch" in result.output

    def test_serve_watch_falls_back_to_mcp_only_when_lock_held(self):
        """If another process holds the daemon lock, --watch must warn and
        continue as MCP-only — never crash, never silently drop the watcher.
        """
        from memgentic.utils.process_lock import ProcessLockError

        runner = CliRunner()
        with (
            patch("memgentic.utils.process_lock.acquire_lock") as acquire,
            patch("memgentic.mcp.server.run_server") as run_server,
            patch("memgentic.mcp.server.run_server_with_watcher") as run_fused,
            patch("memgentic.observability.init_observability"),
        ):
            acquire.side_effect = ProcessLockError("pid=1234 role=daemon")
            result = runner.invoke(main, ["serve", "--watch"])

        assert result.exit_code == 0, result.output
        assert "Continuing as MCP-only" in result.output
        run_server.assert_called_once()
        run_fused.assert_not_called()

    def test_daemon_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "--scan" in result.output

    def test_search_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0
        assert "QUERY" in result.output

    def test_remember_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["remember", "--help"])
        assert result.exit_code == 0
        assert "CONTENT" in result.output

    def test_backup_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["backup", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output

    def test_restore_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["restore", "--help"])
        assert result.exit_code == 0
        assert "BACKUP_FILE" in result.output

    def test_export_gdpr_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["export-gdpr", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output


class TestSourcesCommand:
    """Tests for `memgentic sources`."""

    def test_sources_empty_database(self, tmp_path: Path):
        """sources with an empty database prints 'No memories stored yet.'"""
        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock()
        mock_store.get_source_stats = AsyncMock(return_value={})
        mock_store.get_total_count = AsyncMock(return_value=0)
        mock_store.close = AsyncMock()

        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            with patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_store,
            ):
                runner = CliRunner()
                result = runner.invoke(main, ["sources"])
                assert result.exit_code == 0
                assert "No memories stored yet" in result.output

    def test_sources_with_data(self, tmp_path: Path):
        """sources with data shows a table of platforms and counts."""
        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock()
        mock_store.get_source_stats = AsyncMock(return_value={"claude_code": 42, "chatgpt": 10})
        mock_store.get_total_count = AsyncMock(return_value=52)
        mock_store.close = AsyncMock()

        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            with patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_store,
            ):
                runner = CliRunner()
                result = runner.invoke(main, ["sources"])
                assert result.exit_code == 0
                assert "claude_code" in result.output
                assert "42" in result.output
                assert "chatgpt" in result.output


class TestRememberCommand:
    """Tests for `memgentic remember`."""

    def test_remember_basic(self, tmp_path: Path):
        """remember stores a memory and prints the ID."""
        mock_memory = MagicMock()
        mock_memory.id = "mem-test-123"

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_single = AsyncMock(return_value=mock_memory)

        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(main, ["remember", "Test memory content"])
            assert result.exit_code == 0
            assert "Remembered" in result.output
            assert "mem-test-123" in result.output

    def test_remember_with_topics_and_source(self, tmp_path: Path):
        """remember with --topics and --source passes correct parameters."""
        mock_memory = MagicMock()
        mock_memory.id = "mem-test-456"

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_single = AsyncMock(return_value=mock_memory)

        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "remember",
                    "Use Qdrant for vectors",
                    "--topics",
                    "qdrant,vectors",
                    "--source",
                    "claude_code",
                ],
            )
            assert result.exit_code == 0
            assert "Remembered" in result.output

            # Verify ingest_single was called with correct args
            call_kwargs = mock_pipeline.ingest_single.call_args.kwargs
            assert call_kwargs["content"] == "Use Qdrant for vectors"
            assert call_kwargs["topics"] == ["qdrant", "vectors"]
            assert call_kwargs["platform"].value == "claude_code"

    def test_remember_invalid_source_falls_back_to_unknown(self, tmp_path: Path):
        """remember with an invalid --source falls back to Platform.UNKNOWN."""
        mock_memory = MagicMock()
        mock_memory.id = "mem-test-789"

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_single = AsyncMock(return_value=mock_memory)

        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["remember", "Some fact", "--source", "totally_invalid_platform"],
            )
            assert result.exit_code == 0
            call_kwargs = mock_pipeline.ingest_single.call_args.kwargs
            assert call_kwargs["platform"].value == "unknown"


class TestSearchCommand:
    """Tests for `memgentic search`."""

    def test_search_no_results(self, tmp_path: Path):
        """search with no results prints appropriate message."""
        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.search = AsyncMock(return_value=[])
        mock_vector.close = AsyncMock()

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(main, ["search", "nonexistent query"])
            assert result.exit_code == 0
            assert "No memories found" in result.output

    def test_search_with_results(self, tmp_path: Path):
        """search with results displays a table."""
        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_results = [
            {
                "id": "mem-1",
                "score": 0.95,
                "payload": {
                    "content": "We use Qdrant for vector storage",
                    "platform": "claude_code",
                    "content_type": "decision",
                },
            },
            {
                "id": "mem-2",
                "score": 0.82,
                "payload": {
                    "content": "Embedding model is Qwen3-4B",
                    "platform": "chatgpt",
                    "content_type": "fact",
                },
            },
        ]

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.search = AsyncMock(return_value=mock_results)
        mock_vector.close = AsyncMock()

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.graph.search.hybrid_search",
                AsyncMock(return_value=mock_results),
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(main, ["search", "qdrant"])
            assert result.exit_code == 0, result.output
            assert "0.95" in result.output
            assert "claude_code" in result.output

    def test_search_with_source_filter(self, tmp_path: Path):
        """search with --source passes the filter to vector store."""
        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.search = AsyncMock(return_value=[])
        mock_vector.close = AsyncMock()

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 768)

        mock_hybrid = AsyncMock(return_value=[])

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch("memgentic.graph.search.hybrid_search", mock_hybrid),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            runner = CliRunner()
            result = runner.invoke(main, ["search", "test query", "--source", "claude_code"])
            assert result.exit_code == 0, result.output
            # Verify the SessionConfig was passed with include_sources
            session_config = mock_hybrid.call_args.kwargs["session_config"]
            assert len(session_config.include_sources) == 1
            assert session_config.include_sources[0].value == "claude_code"


class TestBackupCommand:
    """Tests for `memgentic backup`."""

    def test_backup_creates_archive(self, tmp_path: Path):
        """backup creates a valid tar.gz with memgentic.db and metadata."""
        # Create a real SQLite database
        import sqlite3

        db_path = tmp_path / "data" / "memgentic.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        output_path = str(tmp_path / "backup.tar.gz")

        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = db_path
            mock_settings.data_dir = tmp_path / "data"

            runner = CliRunner()
            result = runner.invoke(main, ["backup", "--output", output_path])
            assert result.exit_code == 0
            assert "Backup created" in result.output

            # Verify the tar.gz contents
            assert Path(output_path).exists()
            with tarfile.open(output_path, "r:gz") as tar:
                names = tar.getnames()
                assert "memgentic.db" in names
                assert "backup-metadata.json" in names

    def test_backup_no_database(self, tmp_path: Path):
        """backup with no database file exits with error."""
        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = tmp_path / "nonexistent.db"

            runner = CliRunner()
            result = runner.invoke(main, ["backup"])
            assert result.exit_code == 1
            assert "No database found" in result.output


class TestRestoreCommand:
    """Tests for `memgentic restore`."""

    def test_restore_from_backup(self, tmp_path: Path):
        """restore loads a backup archive into the database location."""
        import sqlite3

        # Create a source database and back it up
        src_db = tmp_path / "src" / "memgentic.db"
        src_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO memories VALUES ('mem-001')")
        conn.commit()
        conn.close()

        # Create a tar.gz backup
        backup_path = tmp_path / "backup.tar.gz"
        meta = {"version": "0.1.0", "created_at": "2026-03-30T00:00:00+00:00"}
        meta_path = tmp_path / "src" / "backup-metadata.json"
        meta_path.write_text(json.dumps(meta))

        with tarfile.open(str(backup_path), "w:gz") as tar:
            tar.add(str(src_db), arcname="memgentic.db")
            tar.add(str(meta_path), arcname="backup-metadata.json")

        # Restore to a new location
        target_db = tmp_path / "restored" / "memgentic.db"

        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = target_db

            runner = CliRunner()
            result = runner.invoke(main, ["restore", str(backup_path), "--force"])
            assert result.exit_code == 0
            assert "Database restored" in result.output

            # Verify restored database is valid
            assert target_db.exists()
            conn = sqlite3.connect(str(target_db))
            rows = conn.execute("SELECT id FROM memories").fetchall()
            conn.close()
            assert len(rows) == 1
            assert rows[0][0] == "mem-001"

    def test_restore_invalid_archive(self, tmp_path: Path):
        """restore with a non-tar file exits with error."""
        bad_file = tmp_path / "not_a_backup.txt"
        bad_file.write_text("this is not a tar file")

        runner = CliRunner()
        result = runner.invoke(main, ["restore", str(bad_file)])
        assert result.exit_code == 1
        assert "Invalid backup file" in result.output

    def test_restore_missing_db_in_archive(self, tmp_path: Path):
        """restore with a tar that lacks memgentic.db exits with error."""
        # Create a tar.gz without memgentic.db
        dummy_file = tmp_path / "dummy.txt"
        dummy_file.write_text("hello")
        backup_path = tmp_path / "bad_backup.tar.gz"
        with tarfile.open(str(backup_path), "w:gz") as tar:
            tar.add(str(dummy_file), arcname="dummy.txt")

        with patch("memgentic.cli.settings") as mock_settings:
            mock_settings.sqlite_path = tmp_path / "restored" / "memgentic.db"

            runner = CliRunner()
            result = runner.invoke(main, ["restore", str(backup_path), "--force"])
            assert result.exit_code == 1
            assert "Invalid backup" in result.output


class TestExportGdprCommand:
    """Tests for `memgentic export-gdpr`."""

    def test_export_gdpr_empty(self, tmp_path: Path):
        """export-gdpr with no memories produces valid empty JSON."""
        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock()
        mock_store.get_memories_by_filter = AsyncMock(return_value=[])
        mock_store.close = AsyncMock()

        output_path = str(tmp_path / "export.json")

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_store,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"

            runner = CliRunner()
            result = runner.invoke(main, ["export-gdpr", "--output", output_path])
            assert result.exit_code == 0
            assert "GDPR export complete" in result.output

            data = json.loads(Path(output_path).read_text())
            assert data["export_type"] == "gdpr_article_20"
            assert data["total_memories"] == 0
            assert data["memories"] == []

    def test_export_gdpr_with_memories(self, tmp_path: Path):
        """export-gdpr with memories exports them all."""
        from memgentic.models import (
            CaptureMethod,
            ContentType,
            Memory,
            Platform,
            SourceMetadata,
        )

        mock_memories = [
            Memory(
                id="mem-001",
                content="Test memory one",
                content_type=ContentType.FACT,
                source=SourceMetadata(
                    platform=Platform.CLAUDE_CODE,
                    capture_method=CaptureMethod.MCP_TOOL,
                ),
                topics=["testing"],
            ),
            Memory(
                id="mem-002",
                content="Test memory two",
                content_type=ContentType.DECISION,
                source=SourceMetadata(
                    platform=Platform.CHATGPT,
                    capture_method=CaptureMethod.JSON_IMPORT,
                ),
                topics=["architecture"],
            ),
        ]

        mock_store = AsyncMock()
        mock_store.initialize = AsyncMock()
        mock_store.get_memories_by_filter = AsyncMock(return_value=mock_memories)
        mock_store.close = AsyncMock()

        output_path = str(tmp_path / "export.json")

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_store,
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"

            runner = CliRunner()
            result = runner.invoke(main, ["export-gdpr", "--output", output_path])
            assert result.exit_code == 0

            data = json.loads(Path(output_path).read_text())
            assert data["total_memories"] == 2
            assert len(data["memories"]) == 2
            assert data["memories"][0]["id"] == "mem-001"
            assert data["memories"][1]["id"] == "mem-002"


class TestDaemonCommand:
    """Tests for `memgentic daemon`."""

    def test_daemon_no_scan(self, tmp_path: Path):
        """daemon --no-scan starts without scanning existing files."""
        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()
        mock_embedder.close = AsyncMock()
        mock_pipeline = MagicMock()

        mock_daemon_inst = AsyncMock()
        mock_daemon_inst.start = AsyncMock()
        mock_daemon_inst.stop = AsyncMock()
        mock_daemon_inst.scan_existing = AsyncMock(return_value=5)

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "memgentic.adapters.get_daemon_adapters",
                return_value=[],
            ),
            patch(
                "memgentic.daemon.watcher.MemgenticDaemon",
                return_value=mock_daemon_inst,
            ),
            patch("asyncio.sleep", side_effect=KeyboardInterrupt),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"

            runner = CliRunner()
            result = runner.invoke(main, ["daemon", "--no-scan"])
            # The command exits after KeyboardInterrupt
            assert result.exit_code == 0
            # scan_existing should NOT have been called
            mock_daemon_inst.scan_existing.assert_not_called()
            # start and stop should have been called
            mock_daemon_inst.start.assert_called_once()
            mock_daemon_inst.stop.assert_called_once()


class TestDoctorCommand:
    """Tests for `memgentic doctor` — specifically the Qdrant WARN vs FAIL logic."""

    def _make_settings(self, tmp_path: Path, backend: str):
        """Return a MagicMock that looks like MemgenticSettings."""
        from memgentic.config import StorageBackend

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        mock_settings = MagicMock()
        mock_settings.ollama_url = "http://localhost:11434"
        mock_settings.qdrant_url = "http://localhost:6333"
        mock_settings.embedding_model = "qwen3-embedding:0.6b"
        mock_settings.local_llm_model = "gemma4:e2b"
        mock_settings.embedding_dimensions = 768
        mock_settings.storage_backend = StorageBackend(backend)
        mock_settings.data_dir = data_dir
        mock_settings.sqlite_path = data_dir / "memgentic.db"
        mock_settings.graph_path = data_dir / "graph.pkl"
        mock_settings.context_file_path = str(tmp_path / ".memgentic-context.md")
        return mock_settings

    def _patch_doctor_deps(self, mock_settings, *, qdrant_reachable: bool):
        """Context-manager stack that stubs out all _doctor() side-effects.

        Ollama is always mocked as reachable with both models pulled so that
        the only variable between tests is the Qdrant reachability.
        """
        import contextlib

        import httpx

        # Fake Ollama /api/tags response — both models "pulled"
        ollama_resp = MagicMock()
        ollama_resp.status_code = 200
        ollama_resp.json = MagicMock(
            return_value={
                "models": [
                    {"name": "qwen3-embedding:0.6b"},
                    {"name": "gemma4:e2b"},
                ]
            }
        )

        qdrant_resp = MagicMock()
        qdrant_resp.status_code = 200

        def _make_client_class(ollama_r, qdrant_r, qdrant_ok):
            """Return a mock AsyncClient class whose instances behave correctly."""

            async def _get(url, **kwargs):
                if "11434" in url or "ollama" in url:
                    return ollama_r
                # Qdrant healthz
                if qdrant_ok:
                    return qdrant_r
                raise httpx.ConnectError("qdrant down")

            client_instance = AsyncMock()
            client_instance.get = AsyncMock(side_effect=_get)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)

            client_class = MagicMock(return_value=client_instance)
            return client_class

        mock_client_class = _make_client_class(ollama_resp, qdrant_resp, qdrant_reachable)

        from memgentic.system_info import RamInfo, Tier, TierRecommendation

        fake_gpu = None
        fake_ram = RamInfo(total_mb=16_000, available_mb=8_000)
        fake_rec = TierRecommendation(
            tier=Tier.BALANCED,
            label="Tier 1 — Balanced",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
            local_llm_model="gemma4:e2b",
            multilingual=True,
            reason="test",
            notes=[],
        )

        return contextlib.ExitStack(), [
            patch("memgentic.cli.settings", mock_settings),
            patch("httpx.AsyncClient", mock_client_class),
            patch("memgentic.system_info.detect_gpu", return_value=fake_gpu),
            patch("memgentic.system_info.detect_ram", return_value=fake_ram),
            patch("memgentic.system_info.detect_cpu_cores", return_value=8),
            patch("memgentic.system_info.get_loaded_models", AsyncMock(return_value=[])),
            patch("memgentic.system_info.recommend_tier", return_value=fake_rec),
        ]

    def test_qdrant_warn_when_backend_local(self, tmp_path: Path):
        """When storage_backend=LOCAL and Qdrant is unreachable, doctor shows WARN not FAIL."""
        mock_settings = self._make_settings(tmp_path, "local")
        _, patches = self._patch_doctor_deps(mock_settings, qdrant_reachable=False)

        runner = CliRunner()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = runner.invoke(main, ["doctor"])

        assert result.exit_code == 0, result.output
        # WARN must appear (the Qdrant row)
        assert "WARN" in result.output
        # The Qdrant row detail must mention "Not running" (file-mode fallback)
        assert "Not running" in result.output
        # Only FAILs trigger the "Some checks failed" banner — WARN must not.
        assert "Some checks failed" not in result.output
        # All checks passed banner should be visible
        assert "All checks passed" in result.output

    def test_qdrant_fail_when_backend_qdrant(self, tmp_path: Path):
        """When storage_backend=QDRANT and Qdrant is unreachable, doctor shows FAIL."""
        mock_settings = self._make_settings(tmp_path, "qdrant")
        _, patches = self._patch_doctor_deps(mock_settings, qdrant_reachable=False)

        runner = CliRunner()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = runner.invoke(main, ["doctor"])

        assert result.exit_code == 0, result.output
        assert "FAIL" in result.output
        assert "Some checks failed" in result.output

    def test_qdrant_pass_when_server_running(self, tmp_path: Path):
        """When Qdrant is reachable, doctor shows OK regardless of backend."""
        mock_settings = self._make_settings(tmp_path, "local")
        _, patches = self._patch_doctor_deps(mock_settings, qdrant_reachable=True)

        runner = CliRunner()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = runner.invoke(main, ["doctor"])

        assert result.exit_code == 0, result.output
        # Qdrant row should not be WARN or FAIL when reachable
        assert "Not running" not in result.output


class TestImportExistingCommand:
    """Tests for `memgentic import-existing`."""

    def test_import_existing_no_adapters(self, tmp_path: Path):
        """import-existing with no adapters prints 'Import complete!'"""
        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()
        mock_embedder.close = AsyncMock()
        mock_pipeline = MagicMock()

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "memgentic.adapters.get_import_adapters",
                return_value=[],
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            mock_settings.import_concurrency = 4

            runner = CliRunner()
            result = runner.invoke(main, ["import-existing"])
            assert result.exit_code == 0
            assert "Import complete!" in result.output

    def test_import_existing_with_source_filter(self, tmp_path: Path):
        """import-existing --source skips non-matching adapters."""
        from memgentic.models import Platform

        mock_metadata = AsyncMock()
        mock_metadata.initialize = AsyncMock()
        mock_metadata.close = AsyncMock()

        mock_vector = AsyncMock()
        mock_vector.initialize = AsyncMock()
        mock_vector.close = AsyncMock()

        mock_embedder = MagicMock()
        mock_embedder.close = AsyncMock()
        mock_pipeline = MagicMock()

        # Create two mock adapters
        adapter_claude = MagicMock()
        adapter_claude.platform = Platform.CLAUDE_CODE
        adapter_claude.discover_files = MagicMock(return_value=[])

        adapter_chatgpt = MagicMock()
        adapter_chatgpt.platform = Platform.CHATGPT
        adapter_chatgpt.discover_files = MagicMock(return_value=[])

        with (
            patch("memgentic.cli.settings") as mock_settings,
            patch(
                "memgentic.storage.metadata.MetadataStore",
                return_value=mock_metadata,
            ),
            patch(
                "memgentic.storage.vectors.VectorStore",
                return_value=mock_vector,
            ),
            patch(
                "memgentic.processing.embedder.Embedder",
                return_value=mock_embedder,
            ),
            patch(
                "memgentic.processing.pipeline.IngestionPipeline",
                return_value=mock_pipeline,
            ),
            patch(
                "memgentic.adapters.get_import_adapters",
                return_value=[adapter_claude, adapter_chatgpt],
            ),
        ):
            mock_settings.sqlite_path = tmp_path / "memgentic.db"
            mock_settings.import_concurrency = 4

            runner = CliRunner()
            result = runner.invoke(main, ["import-existing", "--source", "claude_code"])
            assert result.exit_code == 0
            # Only the claude adapter should have discover_files called
            adapter_claude.discover_files.assert_called_once()
            adapter_chatgpt.discover_files.assert_not_called()
