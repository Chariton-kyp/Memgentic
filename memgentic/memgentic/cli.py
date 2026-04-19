"""Memgentic CLI — command-line interface for memory management."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
import structlog
from rich.console import Console
from rich.table import Table

from memgentic.__version__ import __version__
from memgentic.config import StorageBackend, settings

console = Console()
logger = structlog.get_logger()


@click.group()
@click.version_option(version=__version__, prog_name="memgentic")
def main():
    """Memgentic — Universal AI Memory Layer.

    Zero-effort knowledge capture across all AI tools. Source-aware memory
    with semantic search, filtering, and knowledge graphs.

    \b
    Quick start:
      memgentic init            Full onboarding: detect tools, models, hooks
      memgentic setup           Reconfigure models/backend only (no tool detect)
      memgentic doctor          Check prerequisites (Ollama, models, Qdrant)
      memgentic import-existing Import all existing AI conversations
      memgentic daemon          Watch for new conversations in real time
      memgentic search "query"  Semantic search over your memories
      memgentic serve           Start the MCP server for AI tool integration
    """


@main.command()
@click.option(
    "--watch/--no-watch",
    default=False,
    help=(
        "Also run the capture daemon in the same process (single SQLite "
        "writer, single Qdrant handle). Recommended — avoids running "
        "'memgentic daemon' as a second process."
    ),
)
def serve(watch: bool):
    """Start the MCP server (stdio transport).

    \b
    Launches the Memgentic MCP server over stdio, enabling AI tools like
    Claude Code to store and retrieve memories via MCP protocol.

    \b
    Pass --watch to also run the file-watching daemon inside the same
    process. This is the recommended mode for local use: it avoids the
    two-process split and the associated SQLite/Qdrant lock contention
    between ``memgentic serve`` and ``memgentic daemon``.

    \b
    Examples:
      memgentic serve             Start MCP server only (back-compat)
      memgentic serve --watch     Fused: MCP server + capture daemon
    """
    from memgentic.mcp.server import run_server, run_server_with_watcher
    from memgentic.observability import init_observability
    from memgentic.utils.process_lock import (
        ProcessLockError,
        acquire_lock,
        release_lock,
    )

    init_observability(
        service_name="memgentic",
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.enable_observability,
    )

    # MCP stdio reserves stdout for JSON-RPC framing. Every banner and warning
    # this function prints must go to stderr, not the default stdout Console.
    server_console = Console(stderr=True)

    # Plain serve — unchanged path (backwards compat).
    if not watch:
        server_console.print("[bold green]Starting Memgentic MCP server...[/]")
        run_server()
        return

    # --watch: try to acquire the daemon lock so we're the sole SQLite writer.
    # If a standalone 'memgentic daemon' already holds it, warn loudly and
    # fall back to MCP-only — do not crash, and do not silently swallow the
    # watcher (user needs to know ingestion isn't happening in this process).
    use_lock = False
    lock_path: Path | None = None
    lock_acquired = False
    if isinstance(settings.data_dir, Path):
        try:
            if settings.storage_backend.value != "qdrant":
                use_lock = True
        except Exception:
            use_lock = False
    if use_lock:
        lock_path = settings.data_dir / ".daemon.pid"
        try:
            acquire_lock(lock_path, role="serve-watch")
            lock_acquired = True
        except ProcessLockError as exc:
            server_console.print(
                "[yellow]Warning:[/] could not acquire daemon lock — another "
                "Memgentic process is already watching for conversations."
            )
            server_console.print(f"[dim]{exc}[/]")
            server_console.print(
                "[yellow]Continuing as MCP-only[/] "
                "(no file watcher in this process). "
                "Stop the other process and re-run with --watch to fuse them."
            )
            logger.warning(
                "serve.watch_lock_unavailable",
                lock_path=str(lock_path),
                fallback="mcp_only",
            )
            server_console.print("[bold green]Starting Memgentic MCP server...[/]")
            run_server()
            return

    try:
        server_console.print(
            "[bold green]Starting Memgentic MCP server[/] "
            "[dim](fused: serving MCP + watching for new conversations)[/]"
        )
        asyncio.run(run_server_with_watcher())
    finally:
        if lock_acquired and lock_path is not None:
            release_lock(lock_path)


@main.command()
@click.option("--scan/--no-scan", default=True, help="Scan existing conversations on startup")
def daemon(scan: bool):
    """Start the background daemon for automatic conversation capture.

    \b
    Watches AI tool directories (Claude Code, Gemini CLI, etc.) for new
    conversation files and automatically ingests them into Memgentic.

    \b
    Examples:
      memgentic daemon             Start with initial scan of existing files
      memgentic daemon --no-scan   Start watching only, skip initial scan
    """
    from memgentic.observability import init_observability
    from memgentic.utils.process_lock import (
        ProcessLockError,
        acquire_lock,
        release_lock,
    )

    init_observability(
        service_name="memgentic",
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.enable_observability,
    )

    # Skip lock when using Qdrant server mode (concurrent writers supported)
    # or when data_dir is not a real Path (e.g., under test mocks).
    use_lock = False
    lock_path: Path | None = None
    if isinstance(settings.data_dir, Path):
        try:
            if settings.storage_backend.value != "qdrant":
                use_lock = True
        except Exception:
            use_lock = False
    if use_lock:
        lock_path = settings.data_dir / ".daemon.pid"
        try:
            acquire_lock(lock_path, role="daemon")
        except ProcessLockError as exc:
            console.print(f"[red]{exc}[/]")
            return

    async def _run():
        from memgentic.adapters import get_daemon_adapters
        from memgentic.daemon.watcher import MemgenticDaemon
        from memgentic.processing.embedder import Embedder
        from memgentic.processing.pipeline import IngestionPipeline
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        # Initialize stores
        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)
        pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)

        try:
            # Register all daemon-capable adapters
            adapters = get_daemon_adapters()

            daemon_inst = MemgenticDaemon(
                settings, pipeline, adapters, metadata_store=metadata_store
            )

            if scan:
                console.print("[yellow]Scanning existing conversations...[/]")
                count = await daemon_inst.scan_existing()
                console.print(f"[green]Processed {count} existing files.[/]")

            console.print("[bold green]Daemon running. Watching for new conversations...[/]")
            console.print("[dim]Press Ctrl+C to stop.[/]")

            await daemon_inst.start()

            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopping daemon...[/]")
                await daemon_inst.stop()
        finally:
            await metadata_store.close()
            await vector_store.close()

    try:
        asyncio.run(_run())
    finally:
        if use_lock and lock_path is not None:
            release_lock(lock_path)


@main.command()
@click.argument("query")
@click.option(
    "--source",
    "-s",
    default=None,
    help="Filter by platform (e.g., claude_code, chatgpt, gemini_cli)",
)
@click.option(
    "--content-type",
    "-t",
    default=None,
    help="Filter by content type (e.g., decision, learning, preference, bug_fix)",
)
@click.option("--limit", "-n", default=10, help="Maximum number of results to return")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["full", "compact", "json"]),
    default="full",
    help="Output format (compact for shell hooks, json for programmatic use)",
)
def search(
    query: str,
    source: str | None,
    content_type: str | None,
    limit: int,
    output_format: str,
):
    """Search your memories using semantic similarity.

    \b
    Uses the embedding model to find memories that are conceptually
    similar to QUERY, even if the exact words differ.

    \b
    Examples:
      memgentic search "vector database decision"
      memgentic search "deployment setup" -s claude_code -n 5
      memgentic search "auth pattern" --format compact
      memgentic search "database" --format json
      memgentic search "bug fixes" -t bug_fix
    """

    async def _run():
        from memgentic.exceptions import EmbeddingError
        from memgentic.models import ContentType, Platform, SessionConfig
        from memgentic.processing.embedder import Embedder
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)

        try:
            config = SessionConfig()
            if source:
                config.include_sources = [Platform(source)]
            if content_type:
                config.include_content_types = [ContentType(content_type)]

            try:
                # Probe embedder so we surface a clear error before search.
                await embedder.embed(query)
            except EmbeddingError as e:
                console.print(f"[red]Embedding error:[/] {e}")
                console.print("[yellow]Run 'memgentic doctor' to check your setup.[/]")
                return

            try:
                from memgentic.graph.knowledge import create_knowledge_graph
                from memgentic.graph.search import hybrid_search

                graph = create_knowledge_graph(settings.graph_path)
                try:
                    await graph.load()
                except Exception:
                    graph = None
                results = await hybrid_search(
                    query=query,
                    metadata_store=metadata_store,
                    vector_store=vector_store,
                    embedder=embedder,
                    graph=graph,
                    session_config=config,
                    limit=limit,
                    settings=settings,
                )
            except ImportError:
                from memgentic.processing.search_basic import basic_search

                results = await basic_search(
                    query=query,
                    metadata_store=metadata_store,
                    vector_store=vector_store,
                    embedder=embedder,
                    session_config=config,
                    limit=limit,
                )

            if not results:
                if output_format == "compact":
                    return
                if output_format == "json":
                    print("[]")
                    return
                console.print(f"[yellow]No memories found for: '{query}'[/]")
                return

            if output_format == "compact":
                for r in results:
                    payload = r["payload"]
                    content = payload.get("content", "")[:100].replace("\n", " ")
                    ctype = payload.get("content_type", "?")
                    platform = payload.get("platform", "?")
                    created = payload.get("created_at", "")[:10]
                    print(f"[{ctype}] {content} | {platform} | {created}")
                return

            if output_format == "json":
                import json

                output = []
                for r in results:
                    payload = r["payload"]
                    output.append(
                        {
                            "score": round(r["score"], 3),
                            "content": payload.get("content", ""),
                            "content_type": payload.get("content_type", ""),
                            "platform": payload.get("platform", ""),
                            "created_at": payload.get("created_at", ""),
                            "topics": payload.get("topics", []),
                        }
                    )
                print(json.dumps(output, indent=2))
                return

            table = Table(title=f"Memory Search: '{query}'")
            table.add_column("Score", style="cyan", width=6)
            table.add_column("Platform", style="green", width=14)
            table.add_column("Type", style="magenta", width=14)
            table.add_column("Content", style="white")

            for r in results:
                payload = r["payload"]
                content = payload.get("content", "")[:80]
                table.add_row(
                    f"{r['score']:.2f}",
                    payload.get("platform", "?"),
                    payload.get("content_type", "?"),
                    content,
                )

            console.print(table)
        finally:
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


@main.command()
def sources():
    """Show a breakdown of stored memories by source platform.

    \b
    Displays a table of all platforms (Claude Code, ChatGPT, Gemini CLI,
    etc.) with memory counts and percentages.
    """

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()

        try:
            stats = await store.get_source_stats()
            total = await store.get_total_count()

            if not stats:
                console.print("[yellow]No memories stored yet.[/]")
                return

            table = Table(title=f"Memory Sources (Total: {total})")
            table.add_column("Platform", style="green")
            table.add_column("Memories", style="cyan", justify="right")
            table.add_column("%", style="dim", justify="right")

            for platform, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
                pct = (count / total * 100) if total > 0 else 0
                table.add_row(platform, str(count), f"{pct:.0f}%")

            console.print(table)
        finally:
            await store.close()

    asyncio.run(_run())


@main.command()
@click.argument("content")
@click.option(
    "--type",
    "-t",
    "content_type",
    default="fact",
    help="Content type (fact, decision, preference, code_snippet, action_item, learning)",
)
@click.option(
    "--source",
    "-s",
    default="unknown",
    help="Source platform (e.g., claude_code, chatgpt)",
)
@click.option("--topics", default=None, help="Comma-separated topic tags")
def remember(content: str, content_type: str, source: str, topics: str | None):
    """Manually store a memory with optional metadata.

    \b
    Examples:
      memgentic remember "Always use UTC for timestamps"
      memgentic remember "Use Qdrant for vectors" -t decision -s claude_code
      memgentic remember "Python 3.12 supports type syntax" --topics python,types
    """

    async def _run():
        from memgentic.exceptions import EmbeddingError
        from memgentic.models import ContentType, Platform
        from memgentic.processing.embedder import Embedder
        from memgentic.processing.pipeline import IngestionPipeline
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)
        pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)

        try:
            topic_list = [t.strip() for t in topics.split(",")] if topics else []

            try:
                ct = ContentType(content_type)
            except ValueError:
                ct = ContentType.FACT

            try:
                plat = Platform(source)
            except ValueError:
                plat = Platform.UNKNOWN

            try:
                memory = await pipeline.ingest_single(
                    content=content,
                    content_type=ct,
                    platform=plat,
                    topics=topic_list,
                )
            except EmbeddingError as e:
                console.print(f"[red]Embedding error:[/] {e}")
                console.print("[yellow]Run 'memgentic doctor' to check your setup.[/]")
                return

            console.print(f"[green]Remembered![/] ID: {memory.id}")
        finally:
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


@main.command()
@click.option(
    "--source",
    "-s",
    default=None,
    help="Only import from this platform (e.g., claude_code)",
)
def import_existing(source: str | None):
    """Import all existing conversations from supported AI tools.

    \b
    Scans known directories for Claude Code, Gemini CLI, Aider, ChatGPT
    exports, and other supported tools. Skips files that have already
    been imported (deduplication by file hash).

    \b
    Examples:
      memgentic import-existing                Import from all tools
      memgentic import-existing -s claude_code  Import only Claude Code
    """

    async def _run():
        from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

        from memgentic.adapters import get_import_adapters
        from memgentic.processing.embedder import Embedder
        from memgentic.processing.pipeline import IngestionPipeline
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)
        pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)

        try:
            adapters = get_import_adapters()
            sem = asyncio.Semaphore(settings.import_concurrency)
            total_imported = 0
            total_skipped = 0
            total_errors = 0

            async def _process_file(adapter, file_path):
                """Process a single file with semaphore for concurrency."""
                nonlocal total_imported, total_skipped, total_errors
                async with sem:
                    try:
                        session_id = await adapter.get_session_id(file_path)
                        chunks = await adapter.parse_file(file_path)
                        if not chunks:
                            total_skipped += 1
                            return 0

                        memories = await pipeline.ingest_conversation(
                            chunks=chunks,
                            platform=adapter.platform,
                            session_id=session_id,
                            file_path=str(file_path),
                        )
                        count = len(memories)
                        if count > 0:
                            total_imported += count
                        else:
                            total_skipped += 1
                        return count
                    except Exception:
                        total_errors += 1
                        return 0

            for adapter in adapters:
                if source and adapter.platform.value != source:
                    continue

                files = adapter.discover_files()

                if not files:
                    continue

                console.print(f"\n[cyan]{adapter.platform.value}:[/] {len(files)} files")

                with Progress(
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task(adapter.platform.value, total=len(files))

                    # Process files concurrently in batches
                    batch_size = settings.import_concurrency * 2
                    for i in range(0, len(files), batch_size):
                        batch = files[i : i + batch_size]
                        tasks = [_process_file(adapter, f) for f in batch]
                        await asyncio.gather(*tasks)
                        progress.advance(task, len(batch))

            console.print(
                f"\n[bold green]Import complete![/] "
                f"{total_imported} memories imported, "
                f"{total_skipped} skipped (empty/dedup), "
                f"{total_errors} errors"
            )
        finally:
            await embedder.close()
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


@main.command()
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output file path (default: mneme-backup-<timestamp>.tar.gz)",
)
def backup(output: str | None):
    """Create a compressed backup of the Memgentic SQLite database.

    \b
    Produces a tar.gz archive containing the database and metadata.
    Uses SQLite's backup API for safe concurrent access.

    \b
    Examples:
      memgentic backup
      memgentic backup -o /tmp/my-backup.tar.gz
    """
    import json
    import sqlite3
    import tarfile
    import tempfile
    from datetime import UTC, datetime

    sqlite_path = settings.sqlite_path
    if not sqlite_path.exists():
        console.print("[red]No database found. Nothing to back up.[/]")
        raise SystemExit(1)

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if output is None:
        output = f"mneme-backup-{timestamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Copy SQLite database using backup API (safe for concurrent access)
        src_conn = sqlite3.connect(str(sqlite_path))
        dst_conn = sqlite3.connect(str(tmp / "memgentic.db"))
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        # Create metadata marker
        meta = {
            "version": "0.1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "data_dir": str(settings.data_dir),
        }
        (tmp / "backup-metadata.json").write_text(json.dumps(meta, indent=2))

        # Create tar.gz
        with tarfile.open(output, "w:gz") as tar:
            tar.add(tmp / "memgentic.db", arcname="memgentic.db")
            tar.add(tmp / "backup-metadata.json", arcname="backup-metadata.json")

    console.print(f"[bold green]Backup created:[/] {output}")


@main.command()
@click.argument("backup_file", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Overwrite existing database without confirmation")
def restore(backup_file: str, force: bool):
    """Restore the Memgentic database from a backup archive.

    \b
    Examples:
      memgentic restore mneme-backup-20260401-120000.tar.gz
      memgentic restore backup.tar.gz --force
    """
    import json
    import shutil
    import tarfile
    import tempfile

    backup_path = Path(backup_file)

    if not tarfile.is_tarfile(str(backup_path)):
        console.print("[red]Invalid backup file — not a valid tar archive.[/]")
        raise SystemExit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Extract archive
        with tarfile.open(str(backup_path), "r:gz") as tar:
            tar.extractall(path=tmp, filter="data")

        db_file = tmp / "memgentic.db"
        meta_file = tmp / "backup-metadata.json"

        if not db_file.exists():
            console.print("[red]Invalid backup — missing memgentic.db.[/]")
            raise SystemExit(1)

        # Show metadata if available
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            console.print(f"[cyan]Backup version:[/] {meta.get('version', 'unknown')}")
            console.print(f"[cyan]Backup created:[/] {meta.get('created_at', 'unknown')}")

        target = settings.sqlite_path
        if (
            target.exists()
            and not force
            and not click.confirm(f"Overwrite existing database at {target}?")
        ):
            console.print("[yellow]Restore cancelled.[/]")
            return

        # Ensure target directory exists and copy
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_file, target)

    console.print(f"[bold green]Database restored to:[/] {target}")


@main.command("export-gdpr")
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Path(),
    help="Output file path (default: mneme-gdpr-export-<timestamp>.json)",
)
def export_gdpr(output: str | None):
    """Export all memories as JSON for GDPR Article 20 data portability.

    \b
    Produces a JSON file containing every stored memory with full
    metadata. Use this for data portability or migration.

    \b
    Examples:
      memgentic export-gdpr
      memgentic export-gdpr -o my-data.json
    """

    async def _run():
        import json as json_mod
        from datetime import UTC, datetime

        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()

        try:
            # Fetch all memories (no filter, high limit)
            memories = await store.get_memories_by_filter(limit=1_000_000)

            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            out_path = output or f"mneme-gdpr-export-{timestamp}.json"

            export_data = {
                "export_type": "gdpr_article_20",
                "exported_at": datetime.now(UTC).isoformat(),
                "total_memories": len(memories),
                "memories": [m.model_dump(mode="json") for m in memories],
            }

            Path(out_path).write_text(json_mod.dumps(export_data, indent=2, default=str))
            console.print(f"[bold green]GDPR export complete:[/] {out_path}")
            console.print(f"[cyan]Total memories exported:[/] {len(memories)}")
        finally:
            await store.close()

    asyncio.run(_run())


@main.command()
def consolidate():
    """Run memory consolidation: recompute importance and detect duplicates.

    \b
    Scans all active memories to update importance scores based on access
    frequency, detect near-duplicate memories for merging, and flag
    contradictions between memories from different sources.
    """

    async def _run():
        try:
            from memgentic.processing.consolidation import consolidate as run_consolidation
        except ImportError:
            console.print(
                "[red]Intelligence extras required for consolidation.[/]\n"
                "Install with: [cyan]pip install mneme-core[intelligence][/]"
            )
            return
        from memgentic.processing.embedder import Embedder
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)

        try:
            console.print("[cyan]Running consolidation...[/]")
            report = await run_consolidation(metadata_store, vector_store, embedder, settings)

            table = Table(title="Consolidation Report")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Importance scores updated", str(report.importance_updated))
            table.add_row("Duplicates merged", str(report.duplicates_merged))
            table.add_row("Contradictions flagged", str(report.contradictions_flagged))
            table.add_row("Errors", str(report.errors))
            console.print(table)

            for detail in report.details:
                console.print(f"  [dim]{detail}[/]")
        finally:
            await embedder.close()
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


@main.command()
def doctor():
    """Check system health and verify all prerequisites are met.

    \b
    Validates Python version, Ollama availability, embedding model,
    Qdrant connectivity, and data directory status. Provides actionable
    suggestions for any failed checks.
    """
    asyncio.run(_doctor())


async def _doctor() -> None:
    """Run health checks and print a summary table."""
    import sys

    import httpx

    from memgentic.system_info import (
        detect_cpu_cores,
        detect_gpu,
        detect_ram,
        get_loaded_models,
        recommend_tier,
    )

    checks: list[tuple[str, bool, str]] = []

    # 1. Python version
    py_ok = sys.version_info >= (3, 12)
    checks.append(("Python >= 3.12", py_ok, f"{sys.version.split()[0]}"))

    # 2. System resources
    gpu = detect_gpu()
    ram = detect_ram()
    if gpu:
        checks.append(
            (
                "GPU",
                True,
                f"{gpu.name} ({gpu.vram_total_gb:.0f}GB VRAM, {gpu.vram_free_gb:.0f}GB free)",
            )
        )
    else:
        checks.append(("GPU", False, "No NVIDIA GPU detected (will use CPU)"))
    if ram.total_mb > 0:
        ram_detail = f"{ram.total_gb:.0f}GB total, {ram.available_gb:.0f}GB free"
        checks.append(("RAM", True, ram_detail))
    else:
        checks.append(("RAM", True, "Could not detect (OK)"))

    # 3. Ollama & models
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            models = r.json().get("models", [])
            model_names = [m["name"] for m in models]
            has_emb = any(settings.embedding_model in n for n in model_names)
            has_llm = any(settings.local_llm_model in n for n in model_names)
            checks.append(("Ollama running", True, settings.ollama_url))
            checks.append(
                (
                    f"Embedding: {settings.embedding_model}",
                    has_emb,
                    "pulled" if has_emb else "not pulled",
                )
            )
            checks.append(
                (
                    f"LLM: {settings.local_llm_model}",
                    has_llm,
                    "pulled" if has_llm else "not pulled",
                )
            )

            # Show loaded models
            loaded = await get_loaded_models(settings.ollama_url)
            if loaded:
                for lm in loaded:
                    loc = "GPU" if lm.on_gpu else "RAM"
                    checks.append(
                        (
                            f"  Loaded: {lm.name}",
                            True,
                            f"{lm.size_gb:.1f}GB on {loc}",
                        )
                    )
    except Exception:
        checks.append(("Ollama running", False, f"Not responding at {settings.ollama_url}"))
        checks.append((f"Embedding: {settings.embedding_model}", False, "Ollama not available"))
        checks.append((f"LLM: {settings.local_llm_model}", False, "Ollama not available"))

    # 4. Vector backend — skip Qdrant probe when using sqlite-vec
    if settings.storage_backend == StorageBackend.SQLITE_VEC:
        try:
            import sqlite_vec  # type: ignore[import-untyped]  # noqa: F401

            checks.append(("sqlite-vec extension", True, "importable"))
        except ImportError:
            # Rich renders the detail column through its markup parser, which
            # would swallow the ``[sqlite-vec]`` extra as an (unknown) tag —
            # escape the square brackets so the install command prints
            # verbatim.
            checks.append(
                (
                    "sqlite-vec extension",
                    False,
                    r"Not installed — run: pip install 'memgentic\[sqlite-vec]'",
                )
            )
    else:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{settings.qdrant_url}/healthz")
                checks.append(("Qdrant server", r.status_code == 200, settings.qdrant_url))
        except Exception:
            checks.append(("Qdrant server", False, "Not running (will use local file mode)"))

    # 5. Data directory + SQLite
    data_exists = settings.data_dir.exists()
    checks.append(("Data directory", data_exists, str(settings.data_dir)))
    sqlite_exists = settings.sqlite_path.exists()
    checks.append(
        (
            "SQLite database",
            sqlite_exists,
            str(settings.sqlite_path) + (" (exists)" if sqlite_exists else " (will be created)"),
        )
    )

    # Print results
    table = Table(title="Memgentic Health Check")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    all_ok = True
    for name, ok, detail in checks:
        status = "[green]OK[/]" if ok else "[red]FAIL[/]"
        if not ok:
            all_ok = False
        table.add_row(name, status, str(detail))

    console.print(table)

    if not all_ok:
        console.print("\n[yellow]Some checks failed. Suggestions:[/]")
        for name, ok, detail in checks:
            if ok:
                continue
            is_ollama_base = "Ollama" in name and all(
                k not in name for k in ("Model", "Embedding", "LLM")
            )
            if is_ollama_base:
                console.print("  -> Install Ollama: https://ollama.com/download")
                console.print("  -> Or run via Docker: docker compose up ollama -d")
            if "Embedding" in name and "not pulled" in detail:
                console.print(f"  -> Pull model: ollama pull {settings.embedding_model}")
            if "LLM" in name and "not pulled" in detail:
                console.print(f"  -> Pull model: ollama pull {settings.local_llm_model}")
            if "Data" in name:
                console.print(f"  -> Will be created on first use: {settings.data_dir}")
    else:
        console.print("\n[bold green]All checks passed! Memgentic is ready.[/]")

    # --- Tier recommendation based on detected hardware ---
    cpu_cores = detect_cpu_cores()
    rec = recommend_tier(gpu, ram, cpu_cores, multilingual=True)

    tier_table = Table(title=f"Recommended tier: {rec.label}", title_justify="left")
    tier_table.add_column("Setting", style="bold")
    tier_table.add_column("Recommended")
    tier_table.add_column("Current")
    tier_table.add_column("")
    match_cells: list[tuple[str, str, str, str]] = [
        (
            "Embedding model",
            rec.embedding_model,
            settings.embedding_model,
            _tick(settings.embedding_model == rec.embedding_model),
        ),
        (
            "Dimensions",
            str(rec.embedding_dimensions),
            str(settings.embedding_dimensions),
            _tick(settings.embedding_dimensions == rec.embedding_dimensions),
        ),
        (
            "Local LLM",
            rec.local_llm_model,
            settings.local_llm_model,
            _tick(settings.local_llm_model == rec.local_llm_model),
        ),
    ]
    for row in match_cells:
        tier_table.add_row(*row)
    console.print()
    console.print(tier_table)
    console.print(f"[dim]Reason: {rec.reason}[/]")
    for note in rec.notes:
        console.print(f"[yellow]Note:[/] {note}")

    # Emit an actionable hint only when current != recommended.
    mismatched = [row for row in match_cells if row[3] == "[yellow]change[/]"]
    if mismatched:
        console.print(
            "\n[yellow]To apply the recommended tier:[/]"
            f"\n  ollama pull {rec.embedding_model}"
            f"\n  ollama pull {rec.local_llm_model}"
            "\n  setx MEMGENTIC_EMBEDDING_MODEL "
            f"{rec.embedding_model}  [dim]# PowerShell / cmd[/]"
            "\n  setx MEMGENTIC_EMBEDDING_DIMENSIONS "
            f"{rec.embedding_dimensions}"
            f"\n  setx MEMGENTIC_LOCAL_LLM_MODEL {rec.local_llm_model}"
            "\n  memgentic re-embed  [dim]# rebuild vectors with the new model[/]"
        )


def _tick(ok: bool) -> str:
    """Rich-coloured match indicator for tier comparison cells.

    Kept ASCII-only to avoid UnicodeEncodeError on Windows cp1253 consoles
    (Greek locale). Rich's default theme will still colour these.
    """
    return "[green]OK[/]" if ok else "[yellow]change[/]"


@main.command()
def status():
    """Show operational status: memory counts, last capture, service health.

    \b
    Complements ``memgentic doctor`` (which checks prerequisites) by
    reporting the live state of the memory system: how many memories are
    stored, when the most recent one was captured, per-platform counts,
    and whether Ollama and Qdrant are reachable.
    """
    asyncio.run(_status())


async def _status() -> None:
    """Report memgentic operational status."""
    import contextlib

    import httpx

    from memgentic.storage.metadata import MetadataStore

    # --- Services ---------------------------------------------------------
    services: list[tuple[str, bool, str]] = []

    # Ollama reachability (reuses the same check shape as `doctor`)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            services.append(("Ollama", r.status_code == 200, settings.ollama_url))
    except Exception:
        services.append(("Ollama", False, f"unreachable at {settings.ollama_url}"))

    # Qdrant reachability
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.qdrant_url}/healthz")
            services.append(("Qdrant", r.status_code == 200, settings.qdrant_url))
    except Exception:
        services.append(("Qdrant", False, "not running (local file mode may be in use)"))

    # --- Memory stats -----------------------------------------------------
    total = 0
    per_platform: dict[str, int] = {}
    last_ts: str | None = None
    db_ok = settings.sqlite_path.exists()

    if db_ok:
        store = MetadataStore(settings.sqlite_path)
        try:
            await store.initialize()
            total = await store.get_total_count()
            per_platform = await store.get_source_stats()
            # Most recent memory timestamp
            from datetime import UTC, datetime, timedelta

            recent = await store.get_memories_since(
                datetime.now(UTC) - timedelta(days=365 * 10), limit=1
            )
            if recent:
                last_ts = recent[0].created_at.strftime("%Y-%m-%d %H:%M UTC")
        except Exception as e:
            services.append(("SQLite", False, f"error: {e}"))
            db_ok = False
        finally:
            with contextlib.suppress(Exception):
                await store.close()

    # --- Render -----------------------------------------------------------
    svc_table = Table(title="Memgentic Status — Services")
    svc_table.add_column("Service", style="bold")
    svc_table.add_column("Status")
    svc_table.add_column("Details")
    for name, ok, detail in services:
        svc_table.add_row(name, "[green]UP[/]" if ok else "[red]DOWN[/]", detail)
    svc_table.add_row(
        "SQLite",
        "[green]UP[/]" if db_ok else "[red]MISSING[/]",
        str(settings.sqlite_path),
    )
    console.print(svc_table)

    mem_table = Table(title="Memgentic Status — Memories")
    mem_table.add_column("Metric", style="bold")
    mem_table.add_column("Value")
    mem_table.add_row("Total memories", str(total))
    mem_table.add_row("Last captured", last_ts or "(none)")
    if per_platform:
        for plat, cnt in sorted(per_platform.items(), key=lambda x: x[1], reverse=True):
            mem_table.add_row(f"  {plat}", str(cnt))
    console.print(mem_table)

    # --- Context file freshness (Phase 3.A) -------------------------------
    from datetime import UTC, datetime
    from pathlib import Path as _Path

    ctx_path = _Path(settings.context_file_path)
    ctx_table = Table(title="Memgentic Status — Context File")
    ctx_table.add_column("Metric", style="bold")
    ctx_table.add_column("Value")
    ctx_table.add_row("Path", str(ctx_path))
    if ctx_path.exists():
        mtime = datetime.fromtimestamp(ctx_path.stat().st_mtime, tz=UTC)
        age_seconds = (datetime.now(UTC) - mtime).total_seconds()
        stale = age_seconds > 3600
        ctx_table.add_row("Exists", "[green]yes[/]")
        ctx_table.add_row("Last updated", mtime.strftime("%Y-%m-%d %H:%M UTC"))
        ctx_table.add_row(
            "Freshness",
            "[yellow]stale (>1h)[/]" if stale else "[green]fresh[/]",
        )
    else:
        ctx_table.add_row("Exists", "[red]no[/]")
        ctx_table.add_row(
            "Hint",
            "run `memgentic daemon` to auto-generate",
        )
    console.print(ctx_table)

    console.print(
        "\n[dim]Daemon: run `memgentic daemon` to watch for new conversations."
        "\nMCP server: run `memgentic serve` to start the MCP stdio server.[/]"
    )


@main.command()
@click.option("--unload", "-u", help="Unload a specific model from memory")
@click.option("--unload-all", is_flag=True, help="Unload all models from memory")
@click.option("--load", "-l", help="Load a model (use --gpu/--cpu to control placement)")
@click.option("--gpu", is_flag=True, help="Force model onto GPU")
@click.option("--cpu", is_flag=True, help="Force model onto CPU/RAM only")
def models(unload: str | None, unload_all: bool, load: str | None, gpu: bool, cpu: bool):
    """Manage Ollama models: view loaded, load/unload, check resources.

    \b
    Shows GPU/RAM status and which models are currently loaded.
    Use --load/--unload to manage model placement.

    \b
    Examples:
      memgentic models                    Show status
      memgentic models --unload gemma4:e4b   Unload model from memory
      memgentic models --unload-all       Free all model memory
      memgentic models --load gemma4:e4b --gpu   Load onto GPU
      memgentic models --load gemma4:e2b --cpu   Load into RAM only
    """

    async def _run():
        from memgentic.system_info import (
            detect_gpu,
            detect_ram,
            get_loaded_models,
            load_model_with_options,
            unload_model,
        )

        gpu_info = detect_gpu()
        ram_info = detect_ram()

        # Show system resources
        res_table = Table(title="System Resources")
        res_table.add_column("Resource", style="bold")
        res_table.add_column("Details")

        if gpu_info:
            res_table.add_row(
                "GPU",
                f"{gpu_info.name} -- "
                f"{gpu_info.vram_free_mb}MB free / {gpu_info.vram_total_mb}MB total "
                f"({gpu_info.utilization_pct}% util)",
            )
        else:
            res_table.add_row("GPU", "No NVIDIA GPU detected")
        if ram_info.total_mb > 0:
            res_table.add_row(
                "RAM",
                f"{ram_info.available_mb}MB free / {ram_info.total_mb}MB total",
            )
        console.print(res_table)

        # Handle unload
        if unload:
            ok = await unload_model(settings.ollama_url, unload)
            if ok:
                console.print(f"\n[green]Unloaded {unload}[/]")
            else:
                console.print(f"\n[red]Failed to unload {unload}[/]")
            return

        if unload_all:
            loaded = await get_loaded_models(settings.ollama_url)
            for lm in loaded:
                ok = await unload_model(settings.ollama_url, lm.name)
                status = "[green]OK[/]" if ok else "[red]FAIL[/]"
                console.print(f"  {status} Unloaded {lm.name}")
            if not loaded:
                console.print("\n[dim]No models loaded[/]")
            return

        # Handle load
        if load:
            num_gpu_layers = None
            if cpu:
                num_gpu_layers = 0
                console.print(f"\n[cyan]Loading {load} onto CPU/RAM...[/]")
            elif gpu:
                num_gpu_layers = 999
                console.print(f"\n[cyan]Loading {load} onto GPU...[/]")
            else:
                console.print(f"\n[cyan]Loading {load} (auto placement)...[/]")

            ok = await load_model_with_options(
                settings.ollama_url,
                load,
                num_gpu=num_gpu_layers,
            )
            if ok:
                console.print(f"[green]Loaded {load}[/]")
            else:
                console.print(f"[red]Failed to load {load}[/]")
            return

        # Show loaded models
        loaded = await get_loaded_models(settings.ollama_url)
        if loaded:
            model_table = Table(title="Loaded Models")
            model_table.add_column("Model", style="bold")
            model_table.add_column("Size")
            model_table.add_column("Location")
            model_table.add_column("Expires")

            for lm in loaded:
                loc = "[green]GPU[/]" if lm.on_gpu else "[yellow]RAM[/]"
                model_table.add_row(
                    lm.name,
                    f"{lm.size_gb:.1f}GB",
                    loc,
                    lm.expires_at[:19],
                )
            console.print(model_table)
        else:
            console.print("\n[dim]No models currently loaded in memory.[/]")
            console.print(
                f"[dim]Configured: embedding={settings.embedding_model}, "
                f"llm={settings.local_llm_model}[/]"
            )
            console.print("[dim]Models load automatically when needed.[/]")

    asyncio.run(_run())


# --- LLM model presets (for intelligence: classification, extraction, summarization) ---
LLM_PRESETS = {
    "1": {
        "name": "gemma4:e2b",
        "label": "Gemma 4 E2B (default -- lightweight, ~5GB RAM)",
        "size": "3.1GB",
    },
    "2": {
        "name": "gemma4:e4b",
        "label": "Gemma 4 E4B (better quality, ~8GB RAM)",
        "size": "5.5GB",
    },
    "3": {
        "name": "gemma4:26b",
        "label": "Gemma 4 26B MoE (best -- only 3.8B active params, needs ~24GB RAM)",
        "size": "18GB",
    },
    "4": {
        "name": "gemma4:31b",
        "label": "Gemma 4 31B Dense (maximum quality, needs ~32GB RAM)",
        "size": "20GB",
    },
    "5": {
        "name": "gemma3:4b",
        "label": "Gemma 3 4B (older, proven, ~4GB RAM)",
        "size": "2.5GB",
    },
}

# --- Embedding model presets ---
EMBEDDING_PRESETS = {
    "1": {
        "name": "qwen3-embedding:0.6b",
        "label": "Qwen3 Embedding 0.6B (default — balanced, ~800MB VRAM)",
        "dims": 768,
        "size": "639MB",
    },
    "2": {
        "name": "qwen3-embedding:4b",
        "label": "Qwen3 Embedding 4B (best quality, needs 4GB+ VRAM)",
        "dims": 768,
        "size": "2.5GB",
    },
    "3": {
        "name": "embeddinggemma:300m",
        "label": "EmbeddingGemma 300M (Google, lightweight, ~500MB VRAM)",
        "dims": 768,
        "size": "622MB",
    },
    "4": {
        "name": "nomic-embed-text",
        "label": "Nomic Embed Text (compact, ~300MB VRAM, English-focused)",
        "dims": 768,
        "size": "274MB",
    },
    "5": {
        "name": "qwen3-embedding:8b",
        "label": "Qwen3 Embedding 8B (top quality, needs 8GB+ VRAM)",
        "dims": 768,
        "size": "5GB",
    },
}


@main.command()
@click.argument("entity")
@click.option("--depth", "-d", default=1, type=int, help="Traversal depth (1-3)")
def graph(entity: str, depth: int):
    """Explore the knowledge graph around an entity.

    \b
    Shows neighbors of the given entity/topic in the knowledge graph,
    revealing connections between concepts across your memories.

    \b
    Examples:
      memgentic graph python
      memgentic graph "FastAPI" --depth 2
    """

    async def _run():
        try:
            from memgentic.graph.knowledge import create_knowledge_graph
        except ImportError:
            console.print(
                "[red]Intelligence extras required for knowledge graph.[/]\n"
                "Install with: [cyan]pip install mneme-core[intelligence][/]"
            )
            return

        kg = create_knowledge_graph(settings.graph_path)
        await kg.load()

        result = await kg.query_neighbors(entity, depth=min(depth, 3))
        neighbors = result.get("neighbors", [])

        if not neighbors:
            console.print(f"[yellow]No neighbors found for '{entity}' in the knowledge graph.[/]")
            console.print("[dim]Try importing conversations first: memgentic import-existing[/]")
            return

        table = Table(title=f"Knowledge Graph: {entity} (depth={depth})")
        table.add_column("Entity", style="bold")
        table.add_column("Type")
        table.add_column("Count", justify="right")
        table.add_column("Depth", justify="right")

        for n in neighbors:
            table.add_row(
                n.get("name", ""),
                n.get("type", ""),
                str(n.get("count", 0)),
                str(n.get("depth", 1)),
            )

        console.print(table)

    asyncio.run(_run())


@main.command("re-embed")
@click.option(
    "--model",
    "model_name",
    default=None,
    help="New Ollama embedding model name (e.g., qwen3-embedding:4b)",
)
@click.option("--all", "reembed_all", is_flag=True, default=True, help="Re-embed all memories")
@click.option("--batch-size", default=100, help="Number of memories to embed per batch")
def re_embed(model_name: str | None, reembed_all: bool, batch_size: int):
    """Re-generate embeddings for all memories.

    \b
    Run this after changing the embedding model (via 'memgentic setup') to
    recompute all vectors with the new model. Progress is shown with a
    progress bar.

    \b
    Examples:
      memgentic re-embed
      memgentic re-embed --model qwen3-embedding:4b --batch-size 50
    """

    async def _run():
        from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

        from memgentic.config import MemgenticSettings
        from memgentic.processing.embedder import Embedder
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        # Optionally override model
        effective_settings = (
            MemgenticSettings(embedding_model=model_name) if model_name else settings
        )

        metadata_store = MetadataStore(effective_settings.sqlite_path)
        vector_store = VectorStore(effective_settings)
        embedder = Embedder(effective_settings)

        await metadata_store.initialize()

        # Re-embed is the one path that *intentionally* replaces the embedding
        # model. Clear the pinned config first so the safety check doesn't
        # abort — we'll re-pin the new model on success.
        if model_name:
            await metadata_store.clear_embedding_config()

        await vector_store.initialize(metadata_store)

        success_count = 0
        failure_count = 0

        try:
            if not reembed_all:
                console.print("[yellow]Only --all is currently supported.[/]")
                return

            # Fetch all active memories
            all_memories = await metadata_store.get_memories_by_filter(limit=1_000_000)
            total = len(all_memories)

            if total == 0:
                console.print("[yellow]No memories to re-embed.[/]")
                return

            model_label = model_name or effective_settings.embedding_model
            console.print(
                f"[cyan]Re-embedding {total} memories "
                f"with model '{model_label}' (batch size: {batch_size})...[/]"
            )

            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Re-embedding", total=total)

                for i in range(0, total, batch_size):
                    batch = all_memories[i : i + batch_size]
                    texts = [m.content for m in batch]

                    try:
                        embeddings = await embedder.embed_batch(texts)
                        await vector_store.upsert_memories_batch(batch, embeddings)
                        success_count += len(batch)
                    except Exception as e:
                        logger.error("re_embed.batch_failed", error=str(e), batch_start=i)
                        failure_count += len(batch)

                    progress.advance(task, len(batch))

            # Pin the (possibly new) model so the next startup passes the
            # dim/model safety check. Use the effective model even when
            # --model wasn't passed, to backfill any earlier corruption.
            if success_count and failure_count == 0:
                await metadata_store.set_embedding_config(
                    model=effective_settings.embedding_model,
                    dimensions=effective_settings.embedding_dimensions,
                )

            console.print(
                f"\n[bold green]Re-embed complete![/] "
                f"{success_count} succeeded, {failure_count} failed"
            )
        finally:
            await embedder.close()
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


def _pull_ollama_model(model_name: str) -> None:
    """Try to pull an Ollama model (Docker first, then local)."""
    import subprocess as sp

    console.print(f"[cyan]Pulling {model_name}...[/]")
    try:
        result = sp.run(
            ["docker", "compose", "exec", "ollama", "ollama", "pull", model_name],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            console.print("[green]Model pulled successfully (Docker)![/]")
            return
    except Exception:
        pass

    try:
        result = sp.run(["ollama", "pull", model_name], timeout=600)
        if result.returncode == 0:
            console.print("[green]Model pulled successfully (local)![/]")
        else:
            console.print("[yellow]Could not pull model. Pull manually:[/]")
            console.print(f"  ollama pull {model_name}")
    except Exception as e:
        console.print(f"[yellow]Pull failed: {e}[/]")
        console.print(f"  Pull manually: ollama pull {model_name}")


def _update_env(key: str, value: str, env_lines: list[str]) -> None:
    """Update or append an env var in the env_lines list."""
    for i, line in enumerate(env_lines):
        if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
            env_lines[i] = f"{key}={value}"
            return
    env_lines.append(f"{key}={value}")


STORAGE_BACKEND_CHOICES: dict[str, dict[str, str]] = {
    "1": {
        "value": "sqlite_vec",
        "label": "sqlite-vec (zero-config, recommended for local)",
        "note": (
            "  Co-locates vectors with the metadata DB. No server, "
            "multi-process safe.\n  Requires the sqlite-vec extra — "
            r"we can run `pip install 'memgentic\[sqlite-vec]'` for you."
        ),
    },
    "2": {
        "value": "local",
        "label": "Qdrant file-mode (no server; upgrades to server mode if one appears)",
        "note": "  File-based Qdrant under ~/.memgentic/data/. No extra install.",
    },
    "3": {
        "value": "qdrant",
        "label": "Qdrant server (Docker or Cloud — for multi-process/larger corpora)",
        "note": "  You'll need MEMGENTIC_QDRANT_URL pointing at a running Qdrant.",
    },
}


def _pick_storage_backend() -> tuple[str, str, bool]:
    """Ask the user to pick a vector backend.

    Returns ``(choice_key, backend_value, needs_sqlite_vec_install)`` so the
    caller can both persist the env var and optionally install the extra.
    """
    console.print("[bold]Step 1: Vector storage backend[/]\n")
    for key, opt in STORAGE_BACKEND_CHOICES.items():
        current = opt["value"] == settings.storage_backend.value
        marker = " [green](current)[/]" if current else ""
        console.print(f"  [bold]{key})[/] {opt['label']}{marker}")
        console.print(f"[dim]{opt['note']}[/]")
    console.print()

    choice = click.prompt(
        "Select storage backend",
        type=click.Choice(list(STORAGE_BACKEND_CHOICES.keys())),
        default="1",
    )
    picked = STORAGE_BACKEND_CHOICES[choice]
    needs_install = picked["value"] == "sqlite_vec"
    return choice, picked["value"], needs_install


def _install_sqlite_vec_extra() -> None:
    """Install the sqlite-vec extra in the current Python env, pip-first."""
    import subprocess
    import sys as _sys

    console.print("[dim]Installing sqlite-vec extra...[/]")
    # Deliberately NOT passing shell=True: avoids the `[sqlite-vec]` glob
    # landmine that bit users in v0.5.0 (see fix #27).
    cmd = [_sys.executable, "-m", "pip", "install", "memgentic[sqlite-vec]"]
    try:
        subprocess.run(cmd, check=True)
        console.print("[green]sqlite-vec installed.[/]")
    except subprocess.CalledProcessError as exc:
        console.print(
            f"[yellow]pip install failed ({exc.returncode}). "
            r"You can retry later with `pip install 'memgentic\[sqlite-vec]'`.[/]"
        )
    except FileNotFoundError:
        console.print(
            r"[yellow]pip not found. Install manually: "
            r"`pip install 'memgentic\[sqlite-vec]'`[/]"
        )


def _run_setup_steps() -> bool:
    """Run the interactive model/backend configuration wizard (Steps 1-4).

    This is the shared implementation used by both ``memgentic init`` (where it
    runs between tool detection and hook installation) and ``memgentic setup``
    (standalone reconfiguration).

    Returns ``True`` on success, ``False`` if the user provides an invalid
    choice and the wizard exits early.
    """
    # --- Step 1: Storage backend ---
    _, backend_value, needs_sqlite_vec = _pick_storage_backend()

    # --- Step 2: Embedding Model ---
    console.print("\n[bold]Step 2: Embedding Model[/] (for semantic search)\n")

    for key, preset in EMBEDDING_PRESETS.items():
        marker = " [green](current)[/]" if preset["name"] == settings.embedding_model else ""
        console.print(f"  [bold]{key})[/] {preset['label']} [{preset['size']}]{marker}")
    console.print("\n  [bold]6)[/] Custom model (enter Ollama model name)")
    console.print()

    emb_choice = click.prompt("Select embedding model", type=str, default="1")

    if emb_choice in EMBEDDING_PRESETS:
        emb_preset = EMBEDDING_PRESETS[emb_choice]
        emb_model = emb_preset["name"]
        emb_dims = emb_preset["dims"]
    elif emb_choice == "6":
        emb_model = click.prompt("Enter Ollama embedding model name")
        emb_dims = click.prompt("Enter embedding dimensions", type=int, default=768)
    else:
        console.print("[red]Invalid choice.[/]")
        return False

    # --- Step 3: Intelligence LLM ---
    console.print(
        "\n[bold]Step 3: Intelligence LLM[/] (for classification, extraction, summarization)\n"
    )
    console.print("  Classifies memories, extracts entities, summarizes conversations.")
    console.print("  Runs locally via Ollama -- no API key needed.\n")

    for key, preset in LLM_PRESETS.items():
        marker = " [green](current)[/]" if preset["name"] == settings.local_llm_model else ""
        console.print(f"  [bold]{key})[/] {preset['label']} [{preset['size']}]{marker}")
    console.print("\n  [bold]6)[/] Custom model (enter Ollama model name)")
    console.print("  [bold]7)[/] Skip -- use Gemini API instead (requires GOOGLE_API_KEY)")
    console.print("  [bold]8)[/] Skip -- use heuristics only (no LLM)")
    console.print()

    llm_choice = click.prompt("Select intelligence LLM", type=str, default="1")

    llm_model = None
    enable_local_llm = True
    if llm_choice in LLM_PRESETS:
        llm_model = LLM_PRESETS[llm_choice]["name"]
    elif llm_choice == "6":
        llm_model = click.prompt("Enter Ollama LLM model name")
    elif llm_choice == "7":
        enable_local_llm = False
        console.print("[dim]Using Gemini API. Set MEMGENTIC_GOOGLE_API_KEY in .env.[/]")
    elif llm_choice == "8":
        enable_local_llm = False
        console.print("[dim]Using heuristics only. No LLM will be used.[/]")
    else:
        console.print("[red]Invalid choice.[/]")
        return False

    # --- Write to .env ---
    env_path = Path.cwd() / ".env"
    env_lines: list[str] = []
    if env_path.exists():
        env_lines = env_path.read_text().splitlines()

    _update_env("MEMGENTIC_STORAGE_BACKEND", backend_value, env_lines)
    _update_env("MEMGENTIC_EMBEDDING_MODEL", emb_model, env_lines)
    _update_env("MEMGENTIC_EMBEDDING_DIMENSIONS", str(emb_dims), env_lines)

    if llm_model:
        _update_env("MEMGENTIC_LOCAL_LLM_MODEL", llm_model, env_lines)
        _update_env("MEMGENTIC_ENABLE_LOCAL_LLM", "true", env_lines)
    else:
        _update_env("MEMGENTIC_ENABLE_LOCAL_LLM", str(enable_local_llm).lower(), env_lines)

    env_path.write_text("\n".join(env_lines) + "\n")

    console.print("\n[green]Saved to .env:[/]")
    console.print(f"  Storage backend: {backend_value}")
    console.print(f"  Embedding: {emb_model} ({emb_dims}d)")
    if llm_model:
        console.print(f"  Intelligence LLM: {llm_model}")
    elif enable_local_llm:
        console.print("  Intelligence: Gemini API")
    else:
        console.print("  Intelligence: heuristics only")

    # --- Step 4: Install sqlite-vec extra if needed ---
    if needs_sqlite_vec:
        try:
            import sqlite_vec  # type: ignore[import-untyped]  # noqa: F401

            console.print("[dim]sqlite-vec extension already installed.[/]")
        except ImportError:
            if click.confirm(
                "\nsqlite-vec backend needs the `sqlite-vec` extra. Install it now?",
                default=True,
            ):
                _install_sqlite_vec_extra()

    # --- Pull models ---
    models_to_pull = [emb_model]
    if llm_model:
        models_to_pull.append(llm_model)

    if click.confirm(f"\nPull {len(models_to_pull)} model(s) now via Ollama?", default=True):
        for m in models_to_pull:
            _pull_ollama_model(m)

    return True


@main.command()
def setup():
    """Reconfigure Memgentic models and storage backend.

    \b
    Escape hatch for reconfiguring an existing installation. Runs only:
      1. Vector storage backend (sqlite-vec / Qdrant local / Qdrant server)
      2. Embedding model (for semantic search)
      3. Intelligence LLM (for classification, extraction, summarization)
      4. Pull models via Ollama

    \b
    Does NOT run AI-tool detection or hook installation. Use
    'memgentic init' for full onboarding of a new installation.

    \b
    Writes settings to .env and optionally pulls models via Ollama.
    Run 'memgentic doctor' afterward to verify.
    """

    console.print("\n[bold cyan]Memgentic Setup[/]\n")
    _run_setup_steps()
    console.print("\n[bold green]Setup complete![/] Run 'memgentic doctor' to verify.")


@main.command()
@click.option("--dry-run", is_flag=True, help="Preview changes without applying them")
@click.option("--skip-import", is_flag=True, help="Skip importing existing conversations")
@click.option(
    "--yes",
    "-y",
    "non_interactive",
    is_flag=True,
    default=False,
    help="Non-interactive mode: skip model/backend prompts and use current settings",
)
def init(dry_run: bool, skip_import: bool, non_interactive: bool):
    """Full onboarding: detect AI tools, configure models, install hooks.

    \b
    Step 0: Detect installed AI tools (Claude Code, Gemini CLI, Codex CLI)
            and configure Memgentic as their MCP memory server.
    Step 1: Vector storage backend  (sqlite-vec / Qdrant local / server)
    Step 2: Embedding model         (for semantic search)
    Step 3: Intelligence LLM        (for classification and extraction)
    Step 4: Pull models via Ollama
    Step 5: Inject memory instructions into each tool's context file.

    \b
    After init, your AI tools will:
      - Load context from past sessions automatically
      - Save important learnings to shared memory
      - Check memory before solving problems

    \b
    Use 'memgentic setup' to reconfigure models/backend without repeating
    tool detection or hook installation.

    \b
    Examples:
      memgentic init                  Full interactive onboarding
      memgentic init --dry-run        Preview changes without applying
      memgentic init --skip-import    Skip importing existing conversations
      memgentic init --yes            Use current settings, skip prompts
    """
    from memgentic.init_wizard import run_init

    asyncio.run(
        run_init(
            dry_run=dry_run,
            skip_import=skip_import,
            non_interactive=non_interactive,
        )
    )


@main.command(name="install-hooks")
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    help="Install hooks globally (all projects) instead of current project only",
)
def install_hooks(use_global: bool):
    """Install Memgentic auto-inject hooks into Claude Code.

    \b
    Adds two hooks to Claude Code settings:
    - UserPromptSubmit: searches memory on each prompt, injects top-3 results
    - SessionStart: injects recent cross-tool activity summary

    \b
    After install, Claude automatically receives relevant memory context
    on every prompt — zero manual effort required.

    \b
    Examples:
      memgentic install-hooks            Install for this project
      memgentic install-hooks --global   Install for all projects
    """
    from memgentic.hooks.install import install_hooks as _install

    if use_global:
        settings_path = Path.home() / ".claude" / "settings.json"
        console.print("[cyan]Installing Memgentic hooks globally...[/]")
    else:
        settings_path = Path.cwd() / ".claude" / "settings.json"
        console.print("[cyan]Installing Memgentic hooks for this project...[/]")

    _install(settings_path)
    console.print("\n[green]Done![/] Restart Claude Code to activate hooks.")


@main.command(name="update-context")
@click.option("--hours", default=72, help="Hours of history to include")
@click.option(
    "--output",
    "-o",
    default=".memgentic-context.md",
    help="Output file path (standalone, never modifies tool config files)",
)
def update_context(hours: int, output: str):
    """Generate a standalone memory context file.

    \b
    Creates a .memgentic-context.md file with recent decisions, learnings,
    and topics. This file is standalone — it never modifies CLAUDE.md,
    GEMINI.md, or other tool config files.

    \b
    For tools without MCP support, configure them to read this file:
      Aider:   aider --read .memgentic-context.md
      Cursor:  Add to .cursor/rules/
      Windsurf: Add to .windsurf/rules/

    \b
    Examples:
      memgentic update-context                Generate context file
      memgentic update-context --hours 24     Only last 24 hours
      memgentic update-context -o context.md  Custom output path
    """

    async def _run():
        from memgentic.processing.context_generator import generate_context_file
        from memgentic.storage.metadata import MetadataStore

        metadata_store = MetadataStore(settings.sqlite_path)
        await metadata_store.initialize()

        try:
            output_path = Path(output)
            ok = await generate_context_file(metadata_store, output_path, hours=hours)
            if ok:
                if output_path.exists():
                    console.print(f"[green]OK[/] Generated {output_path}")
                else:
                    console.print(f"[dim]No memories found in the last {hours} hours.[/]")
            else:
                console.print("[red]Failed to generate context file.[/]")
        finally:
            await metadata_store.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
