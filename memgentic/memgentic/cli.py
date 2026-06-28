"""Memgentic CLI — command-line interface for memory management."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

import click
import structlog
from rich.console import Console
from rich.table import Table

# Windows defaults to a legacy ANSI codepage (cp1253 on Greek locales) that
# can't render UTF-8 content stored in the DB (Greek/Turkish/Chinese/etc.
# memories, evidence strings produced by remote LLMs). Reconfigure stdout/
# stderr to UTF-8 so commands like ``memgentic dream show`` render correctly.
# ``errors="replace"`` ensures that a single un-mappable codepoint never
# crashes the CLI mid-output. Safe no-op on POSIX (already UTF-8).
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from memgentic.__version__ import __version__
from memgentic.config import StorageBackend, settings

console = Console()
logger = structlog.get_logger()

# Key used to persist the default capture profile in ``runtime_settings``.
_CAPTURE_PROFILE_SETTING_KEY = "default_capture_profile"
_VALID_CAPTURE_PROFILES = ("raw", "enriched", "dual")


async def _build_intelligence_components(
    settings_obj,
) -> tuple[object | None, object | None]:
    """Build (LLMClient, KnowledgeGraph) when [intelligence] extras are installed.

    Without these, the IngestionPipeline silently runs heuristic-only —
    a months-long footgun where ``daemon``/``import-existing``/``remember``
    skipped LLM classification even with a valid GOOGLE_API_KEY or local
    Ollama setup. The MCP server already wired this correctly; the CLI did
    not. Returning (None, None) on ImportError preserves the graceful
    fallback for slim installs.
    """
    llm_client: object | None = None
    graph: object | None = None
    try:
        from memgentic.processing.llm import LLMClient

        llm_client = LLMClient(settings_obj)
    except ImportError:
        pass
    try:
        from memgentic.graph.knowledge import create_knowledge_graph

        graph = create_knowledge_graph(settings_obj.graph_path)
        await graph.load()  # type: ignore[attr-defined]
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("cli.graph_load_failed", error=str(exc))
        graph = None
    return llm_client, graph


async def _apply_persisted_capture_profile(metadata_store) -> None:
    """Load the persisted default capture profile (if any) into ``settings``.

    Kept here — rather than in ``config.py`` — because Pydantic Settings is
    constructed once at import time and has no DB access. Each CLI command
    that touches the ingestion pipeline calls this after opening the
    metadata store so runtime mutations via ``memgentic capture-profile set``
    take effect without requiring an env-var restart.
    """
    try:
        stored = await metadata_store.get_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY)
    except Exception:
        stored = None
    if stored and stored in _VALID_CAPTURE_PROFILES:
        settings.default_capture_profile = stored  # type: ignore[assignment]


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
        llm_client, graph = await _build_intelligence_components(settings)
        pipeline = IngestionPipeline(
            settings,
            metadata_store,
            vector_store,
            embedder,
            llm_client=llm_client,
            graph=graph,
        )

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)
        await _apply_persisted_capture_profile(metadata_store)

        try:
            # Register all daemon-capable adapters
            adapters = get_daemon_adapters()

            daemon_inst = MemgenticDaemon(
                settings,
                pipeline,
                adapters,
                metadata_store=metadata_store,
                vector_store=vector_store,
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
@click.option(
    "--project",
    "-p",
    default=None,
    help=(
        "Filter by project key (e.g., memgentic-public-export, vetervo). "
        "Pass 'auto' to use the current working directory."
    ),
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
    project: str | None,
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
      memgentic search "auth flow" --project auto
      memgentic search "deployment" -p memgentic-public-export
    """

    async def _run():
        from memgentic.exceptions import EmbeddingError
        from memgentic.models import ContentType, Platform, SessionConfig
        from memgentic.processing.embedder import Embedder
        from memgentic.processing.project import project_from_cwd
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
            if project:
                resolved = project
                if project.strip().lower() == "auto":
                    from pathlib import Path as _Path

                    resolved = project_from_cwd(str(_Path.cwd()))
                    if not resolved:
                        console.print(
                            "[yellow]project=auto could not derive a name "
                            "from the current cwd; ignoring filter.[/]"
                        )
                        resolved = None
                if resolved:
                    config.include_projects = [resolved.lower()]
                    if output_format == "full":
                        console.print(f"[dim]Filtering by project: {resolved.lower()}[/]")

            try:
                # Probe embedder so we surface a clear error before search.
                await embedder.embed_query(query)
            except EmbeddingError as e:
                console.print(f"[red]Embedding error:[/] {e}")
                console.print("[yellow]Run 'memgentic doctor' to check your setup.[/]")
                return

            # Optional cross-encoder reranker (llama-server). No-op when off;
            # graceful fallback to fused order when the server is unreachable.
            from memgentic.retrieval.reranker import LlamaCppReranker

            reranker = (
                LlamaCppReranker.from_settings(settings) if settings.enable_reranker else None
            )
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
                    reranker=reranker,
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
                    settings=settings,
                    reranker=reranker,
                )
            finally:
                if reranker is not None:
                    await reranker.aclose()

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
                    project_label = payload.get("project") or "—"
                    created = payload.get("created_at", "")[:10]
                    print(f"[{ctype}] {content} | {platform} | {project_label} | {created}")
                return

            if output_format == "json":
                import json

                output = []
                for r in results:
                    payload = r["payload"]
                    output.append(
                        {
                            "score": round(r["score"], 3),
                            "relevance": round(r.get("relevance", r.get("score", 0.0)), 3),
                            "reranked": bool(r.get("reranked", False)),
                            "content": payload.get("content", ""),
                            "content_type": payload.get("content_type", ""),
                            "platform": payload.get("platform", ""),
                            "project": payload.get("project", ""),
                            "created_at": payload.get("created_at", ""),
                            "topics": payload.get("topics", []),
                        }
                    )
                print(json.dumps(output, indent=2))
                return

            table = Table(title=f"Memory Search: '{query}'")
            # Show the normalized [0,1] relevance (the rerank score when reranked,
            # otherwise the RRF/cosine relevance) rather than the raw RRF score,
            # which is in tiny, non-intuitive units. A ✓ marks reranked rows.
            table.add_column("Rel.", style="cyan", width=6)
            table.add_column("RR", style="cyan", width=2)
            table.add_column("Platform", style="green", width=14)
            table.add_column("Type", style="magenta", width=14)
            table.add_column("Content", style="white")

            for r in results:
                payload = r["payload"]
                content = payload.get("content", "")[:80]
                relevance = r.get("relevance", r.get("score", 0.0))
                table.add_row(
                    f"{relevance:.2f}",
                    "✓" if r.get("reranked") else "",
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
@click.option(
    "--limit",
    "-n",
    default=20,
    help="How many projects to show (default: 20).",
)
def projects(limit: int):
    """Show a breakdown of stored memories by project.

    \b
    A "project" is the friendly key derived from the originating working
    directory (Path(cwd).name lowercased). Memories without a derivable
    project — manual remember calls, ChatGPT imports, Antigravity sessions
    — show under "(unknown)".

    \b
    Examples:
      memgentic projects
      memgentic projects -n 50
    """

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()

        try:
            stats = await store.get_project_stats()
            total = sum(stats.values())

            if not stats:
                console.print("[yellow]No memories stored yet.[/]")
                return

            table = Table(title=f"Memory Projects (Total: {total})")
            table.add_column("Project", style="green")
            table.add_column("Memories", style="cyan", justify="right")
            table.add_column("%", style="dim", justify="right")

            ordered = sorted(stats.items(), key=lambda x: x[1], reverse=True)
            for project, count in ordered[:limit]:
                pct = (count / total * 100) if total > 0 else 0
                label = project if project else "[dim](unknown)[/]"
                table.add_row(label, str(count), f"{pct:.0f}%")

            console.print(table)
            if len(ordered) > limit:
                console.print(
                    f"[dim]... {len(ordered) - limit} more projects (use --limit to see them).[/]"
                )
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
@click.option(
    "--profile",
    "capture_profile",
    type=click.Choice(["raw", "enriched", "dual"]),
    default=None,
    help="Capture profile override (raw skips LLM, dual stores both).",
)
def remember(
    content: str,
    content_type: str,
    source: str,
    topics: str | None,
    capture_profile: str | None,
):
    """Manually store a memory with optional metadata.

    \b
    Examples:
      memgentic remember "Always use UTC for timestamps"
      memgentic remember "Use Qdrant for vectors" -t decision -s claude_code
      memgentic remember "Python 3.12 supports type syntax" --topics python,types
      memgentic remember "Verbatim note" --profile raw
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
        llm_client, graph = await _build_intelligence_components(settings)
        pipeline = IngestionPipeline(
            settings,
            metadata_store,
            vector_store,
            embedder,
            llm_client=llm_client,
            graph=graph,
        )

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)
        await _apply_persisted_capture_profile(metadata_store)

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
                    capture_profile=capture_profile,  # type: ignore[arg-type]
                )
            except EmbeddingError as e:
                console.print(f"[red]Embedding error:[/] {e}")
                console.print("[yellow]Run 'memgentic doctor' to check your setup.[/]")
                return

            console.print(
                f"[green]Remembered![/] ID: {memory.id} "
                f"(profile: [cyan]{memory.capture_profile}[/])"
            )
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
@click.option(
    "--profile",
    "capture_profile",
    type=click.Choice(["raw", "enriched", "dual"]),
    default=None,
    help="Capture profile for imported memories (raw skips LLM, dual stores both).",
)
def import_existing(source: str | None, capture_profile: str | None):
    """Import all existing conversations from supported AI tools.

    \b
    Scans known directories for Claude Code, Gemini CLI, Aider, ChatGPT
    exports, and other supported tools. Skips files that have already
    been imported (deduplication by file hash).

    \b
    Examples:
      memgentic import-existing                Import from all tools
      memgentic import-existing -s claude_code  Import only Claude Code
      memgentic import-existing --profile raw   Verbatim-only bulk import
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
        llm_client, graph = await _build_intelligence_components(settings)
        pipeline = IngestionPipeline(
            settings,
            metadata_store,
            vector_store,
            embedder,
            llm_client=llm_client,
            graph=graph,
        )

        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)
        await _apply_persisted_capture_profile(metadata_store)

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
                        project = await adapter.get_project(file_path)
                        chunks = await adapter.parse_file(file_path)
                        if not chunks:
                            total_skipped += 1
                            return 0

                        memories = await pipeline.ingest_conversation(
                            chunks=chunks,
                            platform=adapter.platform,
                            session_id=session_id,
                            file_path=str(file_path),
                            capture_profile=capture_profile,  # type: ignore[arg-type]
                            project=project,
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
    help="Output file path (default: memgentic-backup-<timestamp>.tar.gz)",
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
        output = f"memgentic-backup-{timestamp}.tar.gz"

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
      memgentic restore memgentic-backup-20260401-120000.tar.gz
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
    help="Output file path (default: memgentic-gdpr-export-<timestamp>.json)",
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
            out_path = output or f"memgentic-gdpr-export-{timestamp}.json"

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
                "Install with: [cyan]pip install memgentic[intelligence][/]"
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


# ---------------------------------------------------------------------------
# memgentic guard ...  (Agentic CI — check AI-written diffs against repo rules)
# ---------------------------------------------------------------------------


@main.group("guard", invoke_without_command=True)
@click.option("--repo", default=".", help="Repository path")
@click.option(
    "--base", default=None, help="Base ref to diff against (defaults to 'main' when unset)"
)
@click.option("--staged", is_flag=True, help="Check staged changes")
@click.option("--rules", "rules_path", default=None, help="Path to decisions.yaml")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.pass_context
def guard(ctx, repo, base, staged, rules_path, fmt):
    """Agentic CI: check AI-written diffs against repo rules (decisions.yaml)."""
    if ctx.invoked_subcommand is not None:
        return
    from pathlib import Path

    from rich.console import Console
    from rich.markup import escape

    from memgentic.guard import engine, formatters

    console = Console(stderr=True)
    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists():
        console.print(f"[red]Not a git repository:[/red] {escape(str(repo_path))}")
        ctx.exit(2)
    rp = Path(rules_path) if rules_path else repo_path / "decisions.yaml"
    if not rp.exists():
        if rules_path is not None:
            # User explicitly supplied a --rules path that doesn't exist → error
            console.print(f"[red]Rules file not found:[/red] {escape(str(rp))}")
            ctx.exit(2)
        else:
            # Default path missing → soft advisory, not an error
            console.print(
                f"[yellow]No rules at {escape(str(rp))} (run `guard init` — phase 2)[/yellow]"
            )
            ctx.exit(0)
    try:
        rules = engine.load_rules(rp)
        violations = engine.run(repo_path, rules, base=base, staged=staged)
    except (click.exceptions.Exit, click.exceptions.Abort):
        raise
    except Exception as exc:
        console.print(f"[red]guard error:[/red] {escape(str(exc))}")
        ctx.exit(2)
    if fmt == "json":
        output = formatters.format_json(violations)
    else:
        # Fall back to ASCII markers when stdout is a legacy codepage (e.g. a
        # Greek Windows cp1253 console, or a redirected/hook stream) that can't
        # encode the ✓/✗/⚠ glyphs — otherwise click.echo raises
        # UnicodeEncodeError and the guard crashes instead of reporting.
        ascii_only = not formatters.stream_supports_unicode(sys.stdout)
        output = formatters.format_text(violations, ascii_only=ascii_only)
    click.echo(output)
    # Only error-severity violations fail the guard; warn-only output exits 0.
    has_error = any(v.severity == "error" for v in violations)
    ctx.exit(1 if has_error else 0)


@guard.command("rules")
@click.option("--repo", default=".", help="Repository path")
@click.option("--rules", "rules_path", default=None, help="Path to decisions.yaml")
@click.pass_context
def guard_rules(ctx, repo, rules_path):
    """Show the loaded rules."""
    from pathlib import Path

    from memgentic.guard import engine

    rp = Path(rules_path) if rules_path else Path(repo).resolve() / "decisions.yaml"
    if not rp.exists():
        if rules_path is not None:
            # User explicitly supplied a --rules path that doesn't exist → error
            click.echo(f"Rules file not found: {rp}", err=True)
            ctx.exit(2)
        else:
            click.echo(f"No rules at {rp}", err=True)
        return
    try:
        for r in engine.load_rules(rp):
            click.echo(f"{r.id} ({r.type.value}) scope={r.scope} targets={r.targets}")
    except (click.exceptions.Exit, click.exceptions.Abort):
        raise
    except Exception as exc:
        click.echo(f"guard rules error: {exc}", err=True)
        ctx.exit(2)


@guard.command("suggest")
@click.option("--repo", default=".", help="Repository path to scan for prose rule files")
@click.option(
    "--model",
    default=None,
    help=(
        "Override the LLM for this run. Same routing as dream's --model: "
        "'claude-haiku-4-5', 'gemini-3.1-flash-lite', 'gemma4:e4b', "
        "'qwen3.6:35b-a3b'. Defaults to the configured provider chain "
        "(Gemini -> OpenAI-compat -> Ollama)."
    ),
)
@click.pass_context
def guard_suggest(ctx, repo, model):
    """LLM-assisted rule DISCOVERY — propose decisions.yaml rules for review.

    \b
    Reads the target repo's prose rule files (AGENTS.md, CLAUDE.md, cursor
    rules, ADRs, ...) and PROPOSES machine-checkable guard rules as
    ready-to-paste YAML on stdout. It NEVER enforces and NEVER writes any
    file — you review the output and save it as decisions.yaml yourself.

    \b
    Requires the [intelligence] extra and a reachable LLM provider. Ollama
    works out of the box when running.

    \b
    Examples:
      memgentic guard suggest --repo .
      memgentic guard suggest --repo ../other --model qwen3.6:35b-a3b
    """
    import asyncio
    from pathlib import Path

    from memgentic.guard.suggest import SuggestUnavailableError, render_yaml, suggest_rules

    repo_path = Path(repo).resolve()
    try:
        result = asyncio.run(suggest_rules(repo_path, settings=settings, model=model))
    except SuggestUnavailableError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    except (click.exceptions.Exit, click.exceptions.Abort):
        raise
    except Exception as exc:  # noqa: BLE001 — advisory tool, surface cleanly
        click.echo(f"guard suggest error: {exc}", err=True)
        ctx.exit(2)

    # Advisory summary goes to stderr so stdout stays a clean, pasteable YAML.
    click.echo(
        f"# scanned {len(result.sources_found)} source file(s); "
        f"proposed {result.total_proposed} rule(s) "
        f"({len(result.warnings)} dropped). Review before enforcing.",
        err=True,
    )
    click.echo(render_yaml(result))
    ctx.exit(0)


# Starter ``decisions.yaml`` written by ``guard init``. Every example rule is
# COMMENTED OUT so nothing is enforced until the user opts in — the file parses
# to an empty ruleset on day one. Prose/header lines use ``##`` so a simple
# "strip a leading '# '" uncomment leaves them as comments; example rule lines
# use ``# `` so the same strip turns them into live YAML.
_GUARD_INIT_TEMPLATE = """\
## Memgentic Guard — architectural rules for THIS repo.
##
## `memgentic guard` diffs your branch against its base and fails only on
## rules you define here. Nothing below is enforced yet: every example is
## commented out. Uncomment + edit the ones you want, then run `memgentic guard`.
##
## Tip: `memgentic guard suggest` can draft rules from your AGENTS.md / CLAUDE.md
## / ADRs using an LLM ([intelligence] extra). Review its output before saving.
##
## Four rule types (severity: error blocks the commit/CI, warn just prints):
##   import_direction  — forbid a layer importing another (enforces dependency
##                        direction). Python + C# (`using`).
##   banned_import     — forbid importing specific modules/packages in code.
##                        Python `import`/`from`, C# `using`.
##   banned_dependency — forbid adding a package to a manifest (pyproject.toml,
##                        package.json, requirements.txt, *.csproj,
##                        Directory.Packages.props).
##   forbidden_path    — forbid touching files matching a glob (secrets,
##                        generated code, vendored dirs).

rules:
# - id: no-reverse-dependency
#   type: import_direction
#   scope: "core/**"                # only files under core/ are checked
#   targets: ["app", "web"]         # core/ must NOT import app or web
#   message: "core is the dependency root — it must not import app/web layers."
#   severity: error
#
# - id: no-requests
#   type: banned_import
#   scope: "**"                     # all files (default)
#   targets: ["requests"]           # ban `import requests` — use httpx
#   message: "Use httpx, not requests (async-friendly, already a dependency)."
#   severity: error
#   # C# note: targets match `using` namespaces too, e.g. targets: ["MediatR"]
#   #          bans `using MediatR;` in any .cs file in scope.
#
# - id: no-moment
#   type: banned_dependency
#   scope: "**"
#   targets: ["moment"]             # ban adding `moment` to package.json
#   message: "moment is in maintenance mode — use date-fns or Temporal."
#   severity: error
#
# - id: no-committed-secrets
#   type: forbidden_path
#   targets: ["**/.env", "**/*.pem"]   # never commit env files or private keys
#   message: "Secrets must not be committed. Use a secret manager."
#   severity: error
"""


@guard.command("init")
@click.option("--repo", default=".", help="Repository path to write decisions.yaml into")
@click.pass_context
def guard_init(ctx, repo):
    """Write a STARTER decisions.yaml (all rules commented out, ready to edit).

    \b
    Honest template — NOT auto-discovery. It scaffolds fully-commented examples
    for all four rule types (import_direction, banned_import, banned_dependency,
    forbidden_path) with severity examples and a C# note. Nothing is enforced
    until you uncomment and edit the rules you want.

    \b
    Refuses (exit 2) if decisions.yaml already exists. For LLM-assisted drafting
    from your existing AGENTS.md / CLAUDE.md / ADRs, see `guard suggest`.
    """
    from pathlib import Path

    repo_path = Path(repo).resolve()
    target = repo_path / "decisions.yaml"
    if target.exists():
        click.echo(
            f"decisions.yaml already exists at {target} — refusing to overwrite. "
            "Edit it directly, or `guard suggest` for LLM-drafted rules.",
            err=True,
        )
        ctx.exit(2)
    target.write_text(_GUARD_INIT_TEMPLATE, encoding="utf-8")
    click.echo(f"Wrote starter rules to {target}")
    click.echo("Next: uncomment + edit the rules you want, then run `memgentic guard`.")
    ctx.exit(0)


# Marker that identifies a pre-commit hook installed by ``guard install-hook``.
# Used to decide whether ``--uninstall`` may safely remove it.
_GUARD_HOOK_MARKER = "# memgentic-guard-hook (managed by `memgentic guard install-hook`)"


def _guard_hook_body(python_exe: str) -> str:
    """POSIX-sh pre-commit hook that runs the staged guard via this interpreter.

    Fails OPEN (exit 0 with a note) if the interpreter is gone, so a relocated
    venv never wedges the user's commits. Sets PYTHONIOENCODING=utf-8 because
    hooks run in whatever console the user has (often a legacy codepage).
    """
    # python_exe is embedded literally; quote for sh safety.
    return (
        "#!/bin/sh\n"
        f"{_GUARD_HOOK_MARKER}\n"
        "# Edit rules in decisions.yaml; "
        "run `memgentic guard install-hook --uninstall` to remove.\n"
        'PYTHON="' + python_exe.replace('"', '\\"') + '"\n'
        'if [ ! -x "$PYTHON" ] && ! command -v "$PYTHON" >/dev/null 2>&1; then\n'
        '  echo "memgentic guard: interpreter $PYTHON not found — skipping (fail-open)." >&2\n'
        "  exit 0\n"
        "fi\n"
        'PYTHONIOENCODING=utf-8 "$PYTHON" -m memgentic.cli guard --staged\n'
    )


def _resolve_hooks_dir(repo_path):
    """Return the directory git uses for hooks, honoring core.hooksPath."""
    import subprocess
    from pathlib import Path

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "core.hooksPath"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        res = None
    if res is not None and res.returncode == 0 and res.stdout.strip():
        hp = Path(res.stdout.strip())
        return hp if hp.is_absolute() else (repo_path / hp)
    return repo_path / ".git" / "hooks"


@guard.command("install-hook")
@click.option("--repo", default=".", help="Repository to install the pre-commit hook into")
@click.option("--force", is_flag=True, help="Back up an existing hook to pre-commit.backup")
@click.option("--uninstall", is_flag=True, help="Remove the guard hook (only if it's ours)")
@click.pass_context
def guard_install_hook(ctx, repo, force, uninstall):
    """Install (or remove) a pre-commit hook that runs `guard --staged`.

    \b
    The hook invokes THIS interpreter on your staged diff before each commit,
    blocking the commit on any error-severity violation. Honors core.hooksPath.

    \b
    If a pre-commit hook already exists, install refuses (exit 2) unless --force
    (which backs the old one up to pre-commit.backup). --uninstall removes the
    hook only when it carries our marker, so foreign hooks are never touched.
    """
    import sys as _sys
    from pathlib import Path

    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists():
        click.echo(f"Not a git repository: {repo_path}", err=True)
        ctx.exit(2)

    hooks_dir = _resolve_hooks_dir(repo_path)
    hook = hooks_dir / "pre-commit"

    if uninstall:
        if not hook.exists():
            click.echo("No pre-commit hook to remove.")
            ctx.exit(0)
        if _GUARD_HOOK_MARKER not in hook.read_text(encoding="utf-8"):
            click.echo(
                f"{hook} is not a memgentic guard hook — refusing to remove it.",
                err=True,
            )
            ctx.exit(2)
        hook.unlink()
        click.echo(f"Removed guard hook at {hook}")
        ctx.exit(0)

    hooks_dir.mkdir(parents=True, exist_ok=True)
    if hook.exists():
        existing = hook.read_text(encoding="utf-8")
        is_ours = _GUARD_HOOK_MARKER in existing
        if not force and not is_ours:
            click.echo(
                f"A pre-commit hook already exists at {hook}. "
                "Re-run with --force to back it up (pre-commit.backup) and replace it.",
                err=True,
            )
            ctx.exit(2)
        if not is_ours:  # --force on a foreign hook → back it up first
            backup = hooks_dir / "pre-commit.backup"
            backup.write_text(existing, encoding="utf-8")
            click.echo(f"Backed up existing hook to {backup}")

    hook.write_text(_guard_hook_body(_sys.executable), encoding="utf-8")
    with contextlib.suppress(OSError):
        # Make executable where the filesystem honors the bit (POSIX); harmless on Windows.
        hook.chmod(0o755)
    click.echo(f"Installed guard pre-commit hook at {hook}")
    ctx.exit(0)


# ---------------------------------------------------------------------------
# memgentic dream ...
# ---------------------------------------------------------------------------


def _resolve_dream_project(explicit: str | None) -> str:
    """Pick the project key for a dream invocation.

    Falls back to ``derive_project(cwd=os.getcwd())`` when no explicit
    project is given. An empty string means "no project filter".
    """
    if explicit is not None:
        return explicit
    try:
        import os

        from memgentic.processing.project import derive_project

        return derive_project(cwd=os.getcwd())
    except Exception:
        return ""


@main.group("dream")
def dream():
    """LLM-driven memory consolidation (auto-dream).

    \b
    A dream reads recent session transcripts and the live memory store,
    proposes patches (merge/supersede/archive/normalize_date/insert_insight),
    and saves them as 'proposed'. Live memories are NEVER mutated by the
    pipeline — apply patches explicitly with `dream apply <id>`.

    \b
    Examples:
      memgentic dream run --project memgentic
      memgentic dream show drm_01H...
      memgentic dream apply drm_01H... --yes
      memgentic dream reject drm_01H...
      memgentic dream list
    """


@dream.command("run")
@click.option(
    "--project",
    default=None,
    help="Project scope (defaults to cwd-derived). Pass empty string for all projects.",
)
@click.option(
    "--signal-model",
    default=None,
    help=(
        "Override Phase 2 (Gather Signal) model for this run only. Examples: "
        "'claude-haiku-4-5', 'gemini-3.1-flash-lite', 'gemma4:e4b', "
        "'qwen3.6:35b-a3b'. Empty string forces the default LLMClient chain."
    ),
)
@click.option(
    "--consolidate-model",
    default=None,
    help=(
        "Override Phase 3 (Consolidate) model for this run only. Same routing "
        "rules as --signal-model. Recommended local: qwen3.6:35b-a3b "
        "(MoE, 5/5 schema reliability)."
    ),
)
@click.option(
    "--instructions",
    default="",
    help="Optional LLM guidance (max 4096 chars).",
)
@click.option(
    "--limit-sessions",
    default=None,
    type=int,
    help="Max recent sessions to ingest (default: settings.dream_default_session_limit).",
)
@click.option(
    "--auto-apply",
    is_flag=True,
    help=(
        "Auto-apply NON-destructive patches (normalize_date, insert_insight, "
        "update_field). Destructive patches (merge, supersede, archive_stale) "
        "always require explicit `dream apply`."
    ),
)
def dream_run_cmd(
    project: str | None,
    signal_model: str | None,
    consolidate_model: str | None,
    instructions: str,
    limit_sessions: int | None,
    auto_apply: bool,
):
    """Run a dream consolidation cycle."""

    async def _run():
        try:
            from memgentic.processing.dream import (
                apply_dream,
                run_dream,
            )
        except ImportError:
            console.print(
                "[red]Intelligence extras required for dream.[/]\n"
                "Install with: [cyan]pip install memgentic[intelligence][/]"
            )
            return

        from memgentic.processing.embedder import Embedder
        from memgentic.storage.metadata import MetadataStore

        scope = _resolve_dream_project(project)
        metadata_store = MetadataStore(settings.sqlite_path)
        embedder = Embedder(settings)
        await metadata_store.initialize()

        try:
            phase_models = []
            if signal_model is not None:
                phase_models.append(f"P2={signal_model or '(default)'}")
            if consolidate_model is not None:
                phase_models.append(f"P3={consolidate_model or '(default)'}")
            override_str = f" [{' '.join(phase_models)}]" if phase_models else ""
            console.print(
                f"[cyan]Running dream...[/] project=[bold]{scope or '(all)'}[/]{override_str}"
            )
            run = await run_dream(
                project=scope,
                metadata_store=metadata_store,
                embedder=embedder,
                settings=settings,
                signal_model=signal_model,
                consolidate_model=consolidate_model,
                instructions=instructions,
                limit_sessions=limit_sessions,
            )

            patches = await metadata_store.get_dream_patches(run.id)
            counts: dict[str, int] = {}
            for p in patches:
                counts[p.action.value] = counts.get(p.action.value, 0) + 1

            table = Table(title=f"Dream {run.id[:12]} — {run.status.value}")
            table.add_column("Action", style="bold")
            table.add_column("Proposed", style="cyan", justify="right")
            for action, count in sorted(counts.items()):
                table.add_row(action, str(count))
            if not counts:
                table.add_row("(no patches)", "0")
            console.print(table)

            if run.error:
                console.print(f"[red]Error:[/] {run.error}")

            if auto_apply and patches:
                console.print("[cyan]Auto-applying non-destructive patches...[/]")
                report = await apply_dream(
                    run.id, metadata_store=metadata_store, only_non_destructive=True
                )
                console.print(
                    f"[green]Applied[/] {report.applied} | "
                    f"[yellow]Skipped destructive[/] {report.skipped_destructive} | "
                    f"[red]Errors[/] {len(report.errors)}"
                )

            console.print(
                f"\n[dim]Review with:[/] memgentic dream show {run.id}\n"
                f"[dim]Apply with: [/] memgentic dream apply {run.id} --yes\n"
                f"[dim]Reject with:[/] memgentic dream reject {run.id}"
            )
        finally:
            await embedder.close()
            await metadata_store.close()

    asyncio.run(_run())


@dream.command("show")
@click.argument("dream_id")
def dream_show_cmd(dream_id: str):
    """Print a diff-style view of a dream's proposed patches."""

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            run = await store.get_dream_run(dream_id)
            if not run:
                console.print(f"[red]Dream {dream_id} not found[/]")
                return
            console.print(
                f"[bold]Dream[/] {run.id} | project=[cyan]{run.project or '(all)'}[/] | "
                f"status=[yellow]{run.status.value}[/] | model={run.model}"
            )
            console.print(
                f"[dim]created={run.created_at} ended={run.ended_at} "
                f"applied={run.applied_at} memories_in_scope={run.input_memory_count}[/]"
            )
            if run.error:
                console.print(f"[red]Error:[/] {run.error}")

            patches = await store.get_dream_patches(dream_id)
            if not patches:
                console.print("[dim]No patches.[/]")
                return

            for patch in patches:
                marker = {
                    "proposed": "[yellow][P][/]",
                    "applied": "[green][A][/]",
                    "rejected": "[red][R][/]",
                    "superseded_by_apply": "[dim][S][/]",
                }.get(patch.status.value, "?")
                console.print(
                    f"\n{marker} [bold]{patch.action.value}[/] "
                    f"id={patch.id[:8]} status={patch.status.value}"
                )
                if patch.target_memory_ids:
                    console.print(
                        "  targets: "
                        + ", ".join(t[:8] for t in patch.target_memory_ids[:5])
                        + (" ..." if len(patch.target_memory_ids) > 5 else "")
                    )
                if patch.evidence:
                    console.print(f"  [dim]why:[/] {patch.evidence}")
                if patch.new_content:
                    preview = patch.new_content[:160].replace("\n", " ")
                    console.print(f"  [dim]new:[/] {preview}")
                if patch.new_metadata:
                    console.print(f"  [dim]meta:[/] {patch.new_metadata}")
        finally:
            await store.close()

    asyncio.run(_run())


@dream.command("apply")
@click.argument("dream_id")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.option(
    "--non-destructive-only",
    is_flag=True,
    help="Apply only normalize_date / insert_insight / update_field.",
)
def dream_apply_cmd(dream_id: str, yes: bool, non_destructive_only: bool):
    """Apply a dream's proposed patches."""

    async def _run():
        from memgentic.processing.dream import apply_dream
        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        await store.initialize()
        await vector_store.initialize(store)
        try:
            patches = await store.get_dream_patches(dream_id, status="proposed")
            if not patches:
                console.print("[yellow]No proposed patches to apply.[/]")
                return
            console.print(
                f"[cyan]About to apply[/] {len(patches)} patch(es) for dream {dream_id[:12]}..."
            )
            if not yes and not click.confirm("Continue?"):
                return

            # Pass the vector store so reductive consolidation (archived /
            # superseded sources) is also dropped from recall.
            report = await apply_dream(
                dream_id,
                metadata_store=store,
                vector_store=vector_store,
                only_non_destructive=non_destructive_only,
            )
            table = Table(title=f"Apply Report — {dream_id[:12]}")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Applied", str(report.applied))
            table.add_row("Skipped (destructive)", str(report.skipped_destructive))
            table.add_row("Inserted memories", str(len(report.inserted_memories)))
            table.add_row("Superseded memories", str(len(report.superseded_memories)))
            table.add_row("Archived memories", str(len(report.archived_memories)))
            table.add_row("Chronograph triples", str(report.chronograph_triples))
            table.add_row("Errors", str(len(report.errors)))
            console.print(table)
            for err in report.errors:
                console.print(f"  [red]{err}[/]")
        finally:
            await store.close()
            await vector_store.close()

    asyncio.run(_run())


@dream.command("reject")
@click.argument("dream_id")
def dream_reject_cmd(dream_id: str):
    """Mark every proposed patch in a dream as rejected (no mutation)."""

    async def _run():
        from memgentic.processing.dream import reject_dream
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            count = await reject_dream(dream_id, metadata_store=store)
            console.print(f"[green]Rejected[/] {count} proposed patch(es)")
        finally:
            await store.close()

    asyncio.run(_run())


@dream.command("models")
def dream_models_cmd():
    """Show configured + available LLM providers for the dream pipeline.

    \b
    Routing rules:
      claude-*       -> Anthropic (needs MEMGENTIC_ANTHROPIC_API_KEY)
      gemini-*       -> Google API (needs MEMGENTIC_GOOGLE_API_KEY)
      gpt-* / o1-*   -> OpenAI-compat (needs MEMGENTIC_OPENAI_COMPAT_BASE_URL)
      anything else  -> Ollama tag (needs Ollama running)

    \b
    Examples:
      memgentic dream models
      memgentic dream run --signal-model gemma4:e4b --consolidate-model qwen3.6:35b-a3b
    """
    import urllib.error
    import urllib.request

    async def _run():
        from memgentic.processing.dream import _detect_provider

        # --- Configured models ---
        signal = settings.dream_signal_model or "(unset → default LLMClient)"
        consolidate = settings.dream_consolidate_model or "(unset → default LLMClient)"

        sig_prov = _detect_provider(settings.dream_signal_model or "")
        con_prov = _detect_provider(settings.dream_consolidate_model or "")

        cfg_table = Table(title="Dream pipeline — configured models")
        cfg_table.add_column("Phase", style="bold")
        cfg_table.add_column("Model")
        cfg_table.add_column("Provider", style="cyan")
        cfg_table.add_row("Phase 2 (Gather Signal)", signal, sig_prov or "default")
        cfg_table.add_row("Phase 3 (Consolidate)", consolidate, con_prov or "default")
        console.print(cfg_table)

        # --- Provider availability ---
        avail = Table(title="Provider availability")
        avail.add_column("Provider", style="bold")
        avail.add_column("Status", justify="center")
        avail.add_column("Detail")

        avail.add_row(
            "Anthropic",
            "[green]ok[/]" if settings.anthropic_api_key else "[red]no key[/]",
            (
                "MEMGENTIC_ANTHROPIC_API_KEY set"
                if settings.anthropic_api_key
                else "set MEMGENTIC_ANTHROPIC_API_KEY in .env"
            ),
        )
        avail.add_row(
            "Google (Gemini)",
            "[green]ok[/]" if settings.google_api_key else "[red]no key[/]",
            (
                "MEMGENTIC_GOOGLE_API_KEY set"
                if settings.google_api_key
                else "set MEMGENTIC_GOOGLE_API_KEY in .env"
            ),
        )
        avail.add_row(
            "OpenAI-compat",
            "[green]ok[/]" if settings.openai_compat_base_url else "[dim]inactive[/]",
            settings.openai_compat_base_url or "set MEMGENTIC_OPENAI_COMPAT_BASE_URL",
        )

        # Ollama: try to list installed models (informational, non-fatal)
        ollama_models: list[str] = []
        ollama_status = "[red]unreachable[/]"
        ollama_detail = f"{settings.ollama_url} — start with `ollama serve`"
        try:
            req = urllib.request.Request(f"{settings.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as r:  # nosec B310
                import json as _json

                data = _json.loads(r.read().decode())
                ollama_models = sorted(m["name"] for m in data.get("models", []))
                ollama_status = "[green]ok[/]"
                ollama_detail = f"{len(ollama_models)} model(s) installed"
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        except Exception as exc:
            ollama_detail = f"error: {exc}"

        avail.add_row("Ollama (local)", ollama_status, ollama_detail)
        console.print(avail)

        if ollama_models:
            mtable = Table(title="Ollama — installed models")
            mtable.add_column("Tag")
            for tag in ollama_models:
                mtable.add_row(tag)
            console.print(mtable)

        # --- Recommended configurations ---
        console.print()
        console.print("[bold]Recommended configurations[/]")
        console.print(
            "  [cyan]Cheapest cloud[/]    "
            "Phase 2=[bold]claude-haiku-4-5[/]  Phase 3=[bold]claude-haiku-4-5[/]  "
            "[dim](~$0.10/run)[/]"
        )
        console.print(
            "  [cyan]Best balanced[/]     "
            "Phase 2=[bold]claude-haiku-4-5[/]  Phase 3=[bold]qwen3.6:35b-a3b[/]  "
            "[dim](~$0.005/run + local)[/]"
        )
        console.print(
            "  [cyan]Fully local[/]       "
            "Phase 2=[bold]gemma4:e4b[/]        Phase 3=[bold]qwen3.6:35b-a3b[/]  "
            "[dim]($0)[/]"
        )
        console.print(
            "  [cyan]Portable (16 GB)[/]  "
            "Phase 2=[bold]gemma4:e4b[/]        Phase 3=[bold]gemma4:26b-a4b[/]  "
            "[dim](mmap streams from NVMe)[/]"
        )
        console.print()
        console.print(
            "[dim]Configure via .env (MEMGENTIC_DREAM_SIGNAL_MODEL / "
            "MEMGENTIC_DREAM_CONSOLIDATE_MODEL) or per-run via "
            "`memgentic dream run --signal-model X --consolidate-model Y`.[/]"
        )

    asyncio.run(_run())


@dream.command("list")
@click.option("--project", default=None, help="Filter by project.")
@click.option("--status", default=None, help="Filter by status.")
@click.option("--limit", default=20, type=int)
def dream_list_cmd(project: str | None, status: str | None, limit: int):
    """List recent dream runs."""

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        store = MetadataStore(settings.sqlite_path)
        await store.initialize()
        try:
            runs = await store.list_dream_runs(project=project, status=status, limit=limit)
            if not runs:
                console.print("[yellow]No dreams.[/]")
                return
            table = Table(title="Dream Runs")
            table.add_column("ID", style="cyan")
            table.add_column("Project", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Patches", justify="right")
            table.add_column("Created")
            for run in runs:
                patches = await store.get_dream_patches(run.id)
                table.add_row(
                    run.id[:12],
                    run.project or "(all)",
                    run.status.value,
                    str(len(patches)),
                    run.created_at.strftime("%Y-%m-%d %H:%M"),
                )
            console.print(table)
        finally:
            await store.close()

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

    # Each check is a 3-tuple: (name, state, detail)
    # state is one of: "pass" | "warn" | "fail"
    checks: list[tuple[str, str, str]] = []

    # 1. Python version
    py_ok = sys.version_info >= (3, 12)
    checks.append(("Python >= 3.12", "pass" if py_ok else "fail", f"{sys.version.split()[0]}"))

    # 2. System resources
    gpu = detect_gpu()
    ram = detect_ram()
    if gpu:
        checks.append(
            (
                "GPU",
                "pass",
                f"{gpu.name} ({gpu.vram_total_gb:.0f}GB VRAM, {gpu.vram_free_gb:.0f}GB free)",
            )
        )
    else:
        checks.append(("GPU", "warn", "No NVIDIA GPU detected (will use CPU)"))
    if ram.total_mb > 0:
        ram_detail = f"{ram.total_gb:.0f}GB total, {ram.available_gb:.0f}GB free"
        checks.append(("RAM", "pass", ram_detail))
    else:
        checks.append(("RAM", "pass", "Could not detect (OK)"))

    # 3. Ollama & models
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            models = r.json().get("models", [])
            model_names = [m["name"] for m in models]
            has_emb = any(settings.embedding_model in n for n in model_names)
            has_llm = any(settings.local_llm_model in n for n in model_names)
            checks.append(("Ollama running", "pass", settings.ollama_url))
            checks.append(
                (
                    f"Embedding: {settings.embedding_model}",
                    "pass" if has_emb else "fail",
                    "pulled" if has_emb else "not pulled",
                )
            )
            checks.append(
                (
                    f"LLM: {settings.local_llm_model}",
                    "pass" if has_llm else "fail",
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
                            "pass",
                            f"{lm.size_gb:.1f}GB on {loc}",
                        )
                    )
    except Exception:
        checks.append(("Ollama running", "fail", f"Not responding at {settings.ollama_url}"))
        checks.append((f"Embedding: {settings.embedding_model}", "fail", "Ollama not available"))
        checks.append((f"LLM: {settings.local_llm_model}", "fail", "Ollama not available"))

    # 4. Vector backend — skip Qdrant probe when using sqlite-vec
    if settings.storage_backend == StorageBackend.SQLITE_VEC:
        try:
            import sqlite_vec  # type: ignore[import-untyped]  # noqa: F401

            checks.append(("sqlite-vec extension", "pass", "importable"))
        except ImportError:
            # Rich renders the detail column through its markup parser, which
            # would swallow the ``[sqlite-vec]`` extra as an (unknown) tag —
            # escape the square brackets so the install command prints
            # verbatim.
            checks.append(
                (
                    "sqlite-vec extension",
                    "fail",
                    r"Not installed — run: pip install 'memgentic\[sqlite-vec]'",
                )
            )
    else:
        # Probe Qdrant server.
        # When storage_backend=LOCAL, file-mode Qdrant is the intended
        # zero-config path — a missing server is a WARN, not a FAIL.
        # When storage_backend=QDRANT, the user explicitly chose server mode,
        # so a missing server is genuinely broken (FAIL).
        qdrant_reachable = False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{settings.qdrant_url}/healthz")
                qdrant_reachable = r.status_code == 200
        except Exception:
            qdrant_reachable = False

        if qdrant_reachable:
            checks.append(("Qdrant server", "pass", settings.qdrant_url))
        elif settings.storage_backend == StorageBackend.LOCAL:
            checks.append(
                (
                    "Qdrant server",
                    "warn",
                    "Not running — will use local file mode (zero-config)",
                )
            )
        else:
            # StorageBackend.QDRANT — server mode explicitly selected but unreachable
            checks.append(
                (
                    "Qdrant server",
                    "fail",
                    f"Not running at {settings.qdrant_url} — required when storage_backend=qdrant",
                )
            )

    # 5. Data directory + SQLite
    data_exists = settings.data_dir.exists()
    checks.append(("Data directory", "pass" if data_exists else "fail", str(settings.data_dir)))
    sqlite_exists = settings.sqlite_path.exists()
    checks.append(
        (
            "SQLite database",
            "pass",
            str(settings.sqlite_path) + (" (exists)" if sqlite_exists else " (will be created)"),
        )
    )

    # Print results
    table = Table(title="Memgentic Health Check")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    _state_to_label = {
        "pass": "[green]OK[/]",
        "warn": "[yellow]WARN[/]",
        "fail": "[red]FAIL[/]",
    }

    any_fail = False
    for name, state, detail in checks:
        status = _state_to_label.get(state, "[red]FAIL[/]")
        if state == "fail":
            any_fail = True
        table.add_row(name, status, str(detail))

    console.print(table)

    if any_fail:
        console.print("\n[yellow]Some checks failed. Suggestions:[/]")
        for name, state, detail in checks:
            if state != "fail":
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
            if "Qdrant server" in name and "storage_backend=qdrant" in detail:
                console.print(
                    "  -> Start Qdrant: docker compose up qdrant -d"
                    "\n     or set MEMGENTIC_STORAGE_BACKEND=local to use file mode"
                )
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

    # --- Context file freshness -------------------------------------------
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

# --- Dream pipeline preset bundles ---
# Each preset configures BOTH dream phases at once. The default LLMClient is
# used implicitly when ``signal_model`` / ``consolidate_model`` is empty.
DREAM_PRESETS = {
    "1": {
        "label": "Cheapest cloud — Haiku x2 (~$0.10/run, no GPU/RAM needed)",
        "signal": "claude-haiku-4-5",
        "consolidate": "claude-haiku-4-5",
        "needs": "MEMGENTIC_ANTHROPIC_API_KEY",
    },
    "2": {
        "label": "Best balanced — Haiku P2 + local Qwen 3.6 P3 (~$0.005/run)",
        "signal": "claude-haiku-4-5",
        "consolidate": "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S",
        "needs": "MEMGENTIC_ANTHROPIC_API_KEY + Ollama running",
    },
    "3": {
        "label": "Fully local — Gemma 4 P2 + Qwen 3.6 35B-A3B P3 ($0)",
        "signal": "gemma4:e4b",
        "consolidate": "hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S",
        "needs": "Ollama running (~25 GB disk)",
    },
    "4": {
        "label": "Portable local — Gemma 4 E4B + 26B-A4B (works on 16 GB via NVMe mmap)",
        "signal": "gemma4:e4b",
        "consolidate": "gemma4:26b-a4b",
        "needs": "Ollama running (~22 GB disk)",
    },
    "5": {
        "label": "Quality cloud — Sonnet P3 (~$0.90/run, top quality)",
        "signal": "claude-haiku-4-5",
        "consolidate": "claude-sonnet-4-6",
        "needs": "MEMGENTIC_ANTHROPIC_API_KEY",
    },
    "6": {
        "label": "Skip — keep my current dream config",
        "signal": None,
        "consolidate": None,
        "needs": "",
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
    "6": {
        "name": "bge-m3",
        "label": "BGE-M3 (multilingual incl. Greek, 1024-dim, fast — best for non-English)",
        "dims": 1024,
        "size": "1.2GB",
    },
}


@main.command("graph-neighbors")
@click.argument("entity")
@click.option("--depth", "-d", default=1, type=int, help="Traversal depth (1-3)")
def graph_neighbors(entity: str, depth: int):
    """Explore the co-occurrence graph around an entity.

    \b
    Shows neighbors of the given entity/topic in the NetworkX
    co-occurrence graph (memories where terms appear together).

    For the bitemporal triple store use ``memgentic graph query``
    instead.

    \b
    Examples:
      memgentic graph-neighbors python
      memgentic graph-neighbors "FastAPI" --depth 2
    """

    async def _run():
        try:
            from memgentic.graph.knowledge import create_knowledge_graph
        except ImportError:
            console.print(
                "[red]Intelligence extras required for knowledge graph.[/]\n"
                "Install with: [cyan]pip install memgentic[intelligence][/]"
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

        # A model change means existing vectors are incomparable — rebuild the
        # collection from scratch (drop + recreate) rather than aborting on the
        # dimension/model compatibility guard.
        await vector_store.initialize(metadata_store, force_recreate=bool(model_name))

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
                        embeddings = await embedder.embed_batch_documents(texts)
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


@main.command("migrate-storage")
@click.option(
    "--from",
    "from_backend",
    required=True,
    type=click.Choice([b.value for b in StorageBackend], case_sensitive=False),
    help="Source backend to read memories from.",
)
@click.option(
    "--to",
    "to_backend",
    required=True,
    type=click.Choice([b.value for b in StorageBackend], case_sensitive=False),
    help="Destination backend to write memories into.",
)
@click.option(
    "--batch-size",
    default=100,
    show_default=True,
    help="Number of (id, embedding) pairs to copy per batch.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be migrated without writing anything.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite destination even if it already contains vectors.",
)
def migrate_storage(
    from_backend: str,
    to_backend: str,
    batch_size: int,
    dry_run: bool,
    force: bool,
) -> None:
    """Copy every memory + embedding from one vector backend to another.

    \b
    The metadata (SQLite) is shared and untouched — only vectors are copied.
    The source backend is never modified; migration is purely additive.

    \b
    Examples:
      memgentic migrate-storage --from local --to sqlite_vec
      memgentic migrate-storage --from sqlite_vec --to sqlite_vec --dry-run
    """

    async def _run() -> None:
        from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

        from memgentic.storage.metadata import MetadataStore
        from memgentic.storage.vectors import VectorStore

        src_backend_enum = StorageBackend(from_backend)
        dst_backend_enum = StorageBackend(to_backend)

        # Build ad-hoc settings for each backend, inheriting everything except
        # the storage_backend field.
        src_settings = settings.model_copy(update={"storage_backend": src_backend_enum})
        dst_settings = settings.model_copy(update={"storage_backend": dst_backend_enum})

        # Shared metadata store (same SQLite file for both backends).
        metadata_store = MetadataStore(settings.sqlite_path)
        src_store = VectorStore(src_settings)
        dst_store = VectorStore(dst_settings)

        await metadata_store.initialize()

        try:
            # Initialize source — read the existing pin to validate.
            await src_store.initialize(metadata_store)

            # Check destination for existing data and refuse unless --force.
            if not dry_run:
                # Initialize the destination without passing metadata_store so
                # we don't accidentally re-pin or validate the src pin.
                await dst_store.initialize()
                dst_info = await dst_store.get_collection_info()
                dst_count = dst_info.get("points_count", 0) or 0
                if dst_count > 0 and not force:
                    console.print(
                        f"[red]Destination '{to_backend}' already contains "
                        f"{dst_count} vector(s).[/]\n"
                        "[yellow]Pass --force to overwrite, or choose an empty backend.[/]"
                    )
                    # Non-zero exit so scripts checking $? notice the refusal.
                    raise click.Abort()

            # Count source memories for the progress bar.
            all_memories = await metadata_store.get_memories_by_filter(limit=1_000_000)
            total = len(all_memories)

            if total == 0:
                console.print("[yellow]No memories found in source — nothing to migrate.[/]")
                return

            if dry_run:
                console.print(
                    f"[cyan]Dry run:[/] would migrate [bold]{total}[/] "
                    f"memories from [bold]{from_backend}[/] → [bold]{to_backend}[/]."
                )
                return

            console.print(
                f"[cyan]Migrating [bold]{total}[/] memories from "
                f"[bold]{from_backend}[/] → [bold]{to_backend}[/]...[/]"
            )

            # Build an id→memory lookup so we can pass Memory objects to upsert_memories_batch.
            memory_by_id = {m.id: m for m in all_memories}

            migrated = 0
            failed = 0

            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Migrating", total=total)

                batch_memories: list = []
                batch_embeddings: list = []

                try:
                    async for mem_id, embedding in src_store.all_points():
                        mem = memory_by_id.get(mem_id)
                        if mem is None:
                            # Vector exists in source but not in metadata — skip orphan.
                            logger.warning("migrate_storage.orphan_vector", id=mem_id)
                            continue

                        batch_memories.append(mem)
                        batch_embeddings.append(embedding)

                        if len(batch_memories) >= batch_size:
                            try:
                                await dst_store.upsert_memories_batch(
                                    batch_memories, batch_embeddings
                                )
                                migrated += len(batch_memories)
                            except Exception as exc:
                                logger.error(
                                    "migrate_storage.batch_failed",
                                    error=str(exc),
                                    count=len(batch_memories),
                                )
                                failed += len(batch_memories)
                                console.print(
                                    f"\n[red]Batch failed: {exc}[/]\n"
                                    "[yellow]Destination may be in a partial state. "
                                    "Delete the partial data and retry.[/]"
                                )
                                return
                            finally:
                                progress.advance(task, len(batch_memories))
                                batch_memories = []
                                batch_embeddings = []

                    # Flush any remaining items.
                    if batch_memories:
                        try:
                            await dst_store.upsert_memories_batch(batch_memories, batch_embeddings)
                            migrated += len(batch_memories)
                        except Exception as exc:
                            logger.error(
                                "migrate_storage.final_batch_failed",
                                error=str(exc),
                                count=len(batch_memories),
                            )
                            failed += len(batch_memories)
                            console.print(
                                f"\n[red]Final batch failed: {exc}[/]\n"
                                "[yellow]Destination may be in a partial state. "
                                "Delete the partial data and retry.[/]"
                            )
                            return
                        finally:
                            progress.advance(task, len(batch_memories))

                except Exception as exc:
                    logger.error("migrate_storage.stream_failed", error=str(exc))
                    console.print(
                        f"\n[red]Migration stream error: {exc}[/]\n"
                        "[yellow]Destination may be in a partial state. "
                        "Delete the partial data and retry.[/]"
                    )
                    return

            # Safety pin check: destination pin should match source.
            src_pin = await metadata_store.get_embedding_config()
            if src_pin:
                dst_info_final = await dst_store.get_collection_info()
                dst_count_final = dst_info_final.get("points_count", 0) or 0
                if dst_count_final != migrated:
                    console.print(
                        f"[yellow]Warning: destination has {dst_count_final} points "
                        f"but {migrated} were written — possible partial overlap from --force.[/]"
                    )

            console.print(
                f"\n[bold green]Migration complete![/] "
                f"{migrated} migrated, {failed} failed.\n"
                f"[dim]Tip: update MEMGENTIC_STORAGE_BACKEND={to_backend} in your .env "
                "to switch permanently.[/]"
            )

        finally:
            await src_store.close()
            if not dry_run:
                await dst_store.close()
            await metadata_store.close()

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

    # --- Step 3b: Dream pipeline models (auto-consolidation) ---
    console.print("\n[bold]Step 3b: Dream pipeline (auto-memory-consolidation)[/]\n")
    console.print("  `memgentic dream` periodically reviews recent sessions and proposes")
    console.print(
        "  patches to the live memory store (merge / supersede / archive / insert insights)."
    )
    console.print("  Phase 2 = bulk transcript scan (cheap), Phase 3 = patch generation (quality).")
    console.print()
    for key, preset in DREAM_PRESETS.items():
        marker = ""
        cur_sig = settings.dream_signal_model or ""
        cur_con = settings.dream_consolidate_model or ""
        if preset["signal"] == cur_sig and preset["consolidate"] == cur_con:
            marker = " [green](current)[/]"
        console.print(f"  [bold]{key})[/] {preset['label']}{marker}")
        if preset["needs"]:
            console.print(f"     [dim]needs: {preset['needs']}[/]")
    console.print()

    dream_choice = click.prompt("Select dream pipeline preset", type=str, default="6")
    dream_preset = DREAM_PRESETS.get(dream_choice)
    if dream_preset is None:
        console.print("[yellow]Invalid choice — keeping current config.[/]")
        dream_preset = DREAM_PRESETS["6"]

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

    if dream_preset["signal"] is not None:
        _update_env("MEMGENTIC_DREAM_SIGNAL_MODEL", dream_preset["signal"], env_lines)
    if dream_preset["consolidate"] is not None:
        _update_env("MEMGENTIC_DREAM_CONSOLIDATE_MODEL", dream_preset["consolidate"], env_lines)

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
    if dream_preset["signal"] is not None:
        console.print(f"  Dream Phase 2 (signal): {dream_preset['signal']}")
        console.print(f"  Dream Phase 3 (consolidate): {dream_preset['consolidate']}")
    else:
        console.print("  Dream pipeline: kept existing config")

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


@main.group("capture-profile")
def capture_profile():
    """Inspect or change the default memory capture profile.

    \b
    Profiles:
      raw       Verbatim chunks, no LLM enrichment (~0 LLM calls)
      enriched  Current default — topics, entities, LLM importance
      dual      Both rows written and linked (2x storage, best fidelity)

    \b
    Examples:
      memgentic capture-profile show
      memgentic capture-profile set raw
    """


@capture_profile.command("show")
def capture_profile_show():
    """Print the effective default capture profile."""

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        metadata_store = MetadataStore(settings.sqlite_path)
        await metadata_store.initialize()
        try:
            stored = await metadata_store.get_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY)
            effective = (
                stored if stored in _VALID_CAPTURE_PROFILES else (settings.default_capture_profile)
            )
            console.print(f"Default capture profile: [cyan]{effective}[/]")
            if stored:
                console.print(
                    f"(persisted via 'capture-profile set'; env baseline "
                    f"is [dim]{settings.default_capture_profile}[/])"
                )
            else:
                console.print("[dim](from config / env — not overridden at runtime)[/]")
        finally:
            await metadata_store.close()

    asyncio.run(_run())


@capture_profile.command("set")
@click.argument("profile", type=click.Choice(list(_VALID_CAPTURE_PROFILES)))
def capture_profile_set(profile: str):
    """Persist ``profile`` as the new default capture profile.

    The value is written to the ``runtime_settings`` table and picked up by
    all subsequent ingestion calls (CLI, REST API, MCP). Env var
    ``MEMGENTIC_DEFAULT_CAPTURE_PROFILE`` is still honoured as the baseline
    when no runtime override exists.
    """

    async def _run():
        from memgentic.storage.metadata import MetadataStore

        metadata_store = MetadataStore(settings.sqlite_path)
        await metadata_store.initialize()
        try:
            previous = await metadata_store.get_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY)
            await metadata_store.set_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY, profile)
            settings.default_capture_profile = profile  # type: ignore[assignment]
            console.print(
                f"[green]OK[/] default capture profile: "
                f"[dim]{previous or settings.default_capture_profile}[/] -> "
                f"[cyan]{profile}[/]"
            )
            if profile == "dual":
                console.print("[yellow]Note:[/] 'dual' doubles storage per ingested memory.")
        finally:
            await metadata_store.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# memgentic persona ...
# ---------------------------------------------------------------------------


@main.group(name="persona")
def persona_group():
    """Manage the Persona card (T0 of Recall Tiers).

    \b
    The persona is a structured "who is this agent" card stored at
    ~/.memgentic/persona.yaml. It's loaded at the top of every session
    and sets identity, people, projects, and behavioural preferences.

    \b
    Subcommands:
      init          Bootstrap a persona from recent memories (LLM)
      show          Print the current persona (raw or rendered)
      edit          Open the persona in $EDITOR
      validate      Schema-check the current file
      path          Print the on-disk file path
      set           Set a field via a dotted path
      add-person    Add a person to the persona
      add-project   Add a project to the persona
    """


def _run_async(coro):
    """Run an async coroutine from a Click command."""
    return asyncio.run(coro)


def _format_persona_yaml(persona) -> str:
    """Render a Persona as YAML for CLI display."""
    from memgentic.persona.loader import _persona_to_yaml

    return _persona_to_yaml(persona)


def _diff_personas(old, new) -> str:
    """Return a unified diff between two personas (for bootstrap preview)."""
    import difflib

    old_text = _format_persona_yaml(old) if old is not None else ""
    new_text = _format_persona_yaml(new)
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile="current",
        tofile="proposed",
    )
    return "".join(diff)


@persona_group.command("init")
@click.option("--yes", is_flag=True, help="Auto-accept the LLM bootstrap without prompting")
@click.option(
    "--from",
    "source",
    type=click.Choice(["recent", "skills"]),
    default="recent",
    help="What the LLM should scan: recent memories (default) or top skills",
)
@click.option("--limit", default=100, help="How many items to feed the LLM (default 100)")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing persona.yaml without confirmation",
)
def persona_init(yes: bool, source: str, limit: int, force: bool):
    """LLM-powered bootstrap from recent memories or skills.

    \b
    Examples:
      memgentic persona init                LLM proposes a draft (requires confirmation)
      memgentic persona init --yes          Auto-accept the bootstrap
      memgentic persona init --from skills  Use the skills list instead of memories
    """
    from memgentic.persona import bootstrap as bootstrap_persona
    from memgentic.persona import load as persona_load
    from memgentic.persona import save as persona_save
    from memgentic.persona.loader import PersonaLockError

    async def _run():
        try:
            current = persona_load()
        except Exception as exc:
            console.print(f"[yellow]Warning:[/] existing persona is invalid: {exc}")
            current = None

        if current is not None and not force and not yes:
            console.print(
                "[yellow]A persona already exists.[/] "
                "Re-run with --force to overwrite, or `memgentic persona edit` to tweak."
            )
            return 1

        console.print("[bold]Asking the LLM to propose a persona...[/]")
        try:
            proposed = await bootstrap_persona(source=source, limit=limit)  # type: ignore[arg-type]
        except Exception as exc:
            console.print(f"[red]Bootstrap failed:[/] {exc}")
            return 1

        if proposed is None:
            console.print(
                "[red]Bootstrap could not produce a persona.[/] "
                "Check that GOOGLE_API_KEY or a local Ollama LLM is configured, "
                "then try again. Falling back: `memgentic persona edit`."
            )
            return 1

        console.print("\n[bold]Proposed persona:[/]")
        console.print(_format_persona_yaml(proposed))

        if current is not None:
            console.print("\n[bold]Diff vs. current:[/]")
            diff = _diff_personas(current, proposed)
            console.print(diff or "(identical)")

        if not yes and not click.confirm("Save this persona?", default=True):
            console.print("[dim]Aborted. Nothing written.[/]")
            return 1

        try:
            path = persona_save(proposed)
        except PersonaLockError as exc:
            console.print(f"[red]Could not acquire persona lock:[/] {exc}")
            return 1
        console.print(f"[green]OK[/] Wrote {path}")
        return 0

    raise SystemExit(_run_async(_run()) or 0)


@persona_group.command("show")
@click.option(
    "--render",
    is_flag=True,
    help="Render the T0 briefing (~100 tokens) instead of the raw YAML",
)
def persona_show(render: bool):
    """Print the current persona (raw YAML, or T0-rendered briefing)."""
    from memgentic.persona import load as persona_load
    from memgentic.persona import load_or_default, render_t0

    if render:
        console.print(render_t0(load_or_default()))
        return

    try:
        persona = persona_load()
    except Exception as exc:
        console.print(f"[red]Invalid persona.yaml:[/] {exc}")
        raise SystemExit(1) from exc

    if persona is None:
        console.print(
            "[yellow]No persona file yet.[/] "
            "Run `memgentic persona init` to bootstrap one from your memories, "
            "or `memgentic persona edit` to write one by hand."
        )
        return
    console.print(_format_persona_yaml(persona))


@persona_group.command("edit")
def persona_edit():
    """Open the persona in $EDITOR (creates the file with defaults first if missing)."""
    from memgentic.persona import default_persona
    from memgentic.persona import load as persona_load
    from memgentic.persona import save as persona_save
    from memgentic.persona.loader import get_persona_path

    path = get_persona_path()
    if not path.exists():
        persona_save(default_persona())

    click.edit(filename=str(path))

    # Re-validate after the user closes the editor
    try:
        persona_load()
    except Exception as exc:
        console.print(f"[red]Saved file failed validation:[/] {exc}")
        console.print("Fix the file or run `memgentic persona validate` for details.")
        raise SystemExit(1) from exc
    console.print(f"[green]OK[/] {path}")


@persona_group.command("validate")
def persona_validate():
    """Validate ~/.memgentic/persona.yaml against the schema."""
    from memgentic.persona import load as persona_load
    from memgentic.persona.loader import get_persona_path

    path = get_persona_path()
    if not path.exists():
        console.print(f"[yellow]No file at[/] {path}")
        raise SystemExit(1)

    try:
        persona_load()
    except Exception as exc:
        console.print(f"[red]Invalid persona.yaml:[/] {exc}")
        raise SystemExit(2) from exc
    console.print(f"[green]OK[/] {path}")


@persona_group.command("path")
def persona_path():
    """Print the persona file path."""
    from memgentic.persona.loader import get_persona_path

    # click.echo bypasses Rich's console width wrapping so the path stays
    # on a single line — important for piping into other tools.
    click.echo(str(get_persona_path()))


def _coerce_scalar(value: str):
    """Coerce a CLI string to bool/int/float when possible, else leave as str."""
    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


@persona_group.command("set")
@click.argument("field")
@click.argument("value")
def persona_set(field: str, value: str):
    """Set a field via a dotted path (e.g. `identity.name Atlas`).

    \b
    Examples:
      memgentic persona set identity.name Atlas
      memgentic persona set metadata.workspace_inherit true
      memgentic persona set preferences.remember "decisions,stack choices"
    """
    from memgentic.persona import default_persona
    from memgentic.persona import load as persona_load
    from memgentic.persona import save as persona_save

    try:
        persona = persona_load()
    except Exception as exc:
        console.print(f"[red]Invalid persona.yaml:[/] {exc}")
        raise SystemExit(1) from exc

    if persona is None:
        persona = default_persona()

    parts = field.split(".")
    if not parts or not all(parts):
        console.print("[red]Field must be a non-empty dotted path, e.g. 'identity.name'[/]")
        raise SystemExit(1)

    data = persona.model_dump(mode="json")
    # List-valued leaves accept a comma-separated string.
    coerced: object
    if "," in value and field.split(".")[-1] in {
        "preferences",
        "do_not",
        "remember",
        "avoid",
        "stack",
    }:
        coerced = [v.strip() for v in value.split(",") if v.strip()]
    else:
        coerced = _coerce_scalar(value)

    cursor = data
    for part in parts[:-1]:
        if not isinstance(cursor, dict) or part not in cursor:
            console.print(f"[red]Path '{field}' does not exist in the persona[/]")
            raise SystemExit(1)
        cursor = cursor[part]
    if not isinstance(cursor, dict):
        console.print(f"[red]Path '{field}' resolves to a non-mapping node[/]")
        raise SystemExit(1)
    cursor[parts[-1]] = coerced

    from memgentic.persona.schema import validate as validate_persona

    try:
        updated = validate_persona(data)
    except Exception as exc:
        console.print(f"[red]Update would make the persona invalid:[/] {exc}")
        raise SystemExit(1) from exc
    updated.metadata.generated_by = "edited"
    persona_save(updated)
    console.print(f"[green]OK[/] {field} = {coerced!r}")


@persona_group.command("add-person")
@click.argument("name")
@click.option("--relationship", default=None)
@click.option(
    "--preferences",
    default=None,
    help="Comma-separated preferences (e.g. 'PostgreSQL,mornings only')",
)
@click.option(
    "--do-not",
    "do_not",
    default=None,
    help="Comma-separated do-not rules",
)
def persona_add_person(
    name: str,
    relationship: str | None,
    preferences: str | None,
    do_not: str | None,
):
    """Append a person to the persona."""
    from memgentic.persona import default_persona
    from memgentic.persona import load as persona_load
    from memgentic.persona import save as persona_save
    from memgentic.persona.schema import Person

    persona = persona_load() or default_persona()
    person = Person(
        name=name,
        relationship=relationship,
        preferences=[p.strip() for p in (preferences or "").split(",") if p.strip()],
        do_not=[d.strip() for d in (do_not or "").split(",") if d.strip()],
    )
    persona.people.append(person)
    persona.metadata.generated_by = "edited"
    persona_save(persona)
    console.print(f"[green]OK[/] added person: {name}")


@persona_group.command("add-project")
@click.argument("name")
@click.option(
    "--status",
    type=click.Choice(["active", "paused", "archived"]),
    default="active",
)
@click.option(
    "--stack",
    default=None,
    help="Comma-separated tech stack tags (e.g. 'next.js,postgres')",
)
@click.option("--tldr", default=None, help="One-line project summary")
def persona_add_project(
    name: str,
    status: str,
    stack: str | None,
    tldr: str | None,
):
    """Append a project to the persona."""
    from memgentic.persona import default_persona
    from memgentic.persona import load as persona_load
    from memgentic.persona import save as persona_save
    from memgentic.persona.schema import Project

    persona = persona_load() or default_persona()
    project = Project(
        name=name,
        status=status,  # type: ignore[arg-type]
        stack=[s.strip() for s in (stack or "").split(",") if s.strip()],
        tldr=tldr,
    )
    persona.projects.append(project)
    persona.metadata.generated_by = "edited"
    persona_save(persona)
    console.print(f"[green]OK[/] added project: {name}")


# ---------------------------------------------------------------------------
# memgentic graph ...  (Chronograph — bitemporal entity-relationship graph)
# ---------------------------------------------------------------------------


@main.group(name="graph")
def graph_group():
    """Inspect and manage the Chronograph (bitemporal triple store).

    \b
    The Chronograph stores subject-predicate-object triples with
    validity windows. LLM-proposed triples land as 'proposed' and must
    be accepted via the validation queue before they surface in queries.

    \b
    Subcommands:
      status          Show entity / triple counts
      query ENTITY    Current facts about an entity
      timeline ENT    Chronological fact stream
      add S P O       Add and accept a triple manually
      invalidate ...  Close an open validity window
      proposed        Show the LLM validation queue
      accept ID       Accept a proposed triple
      reject ID       Reject a proposed triple
      edit ID ...     Edit a triple (predicate / dates / confidence)
      extract         Re-run extractor on a memory
      backfill        Extract from existing enriched memories
    """


def _display_triples(triples, title: str) -> None:
    table = Table(title=title)
    table.add_column("id", style="dim")
    table.add_column("subject", style="cyan")
    table.add_column("predicate", style="magenta")
    table.add_column("object", style="cyan")
    table.add_column("valid_from")
    table.add_column("valid_to")
    table.add_column("status")
    table.add_column("conf", justify="right")
    for t in triples:
        table.add_row(
            t.id[:10],
            t.subject,
            t.predicate,
            t.object,
            t.valid_from.isoformat() if t.valid_from else "",
            t.valid_to.isoformat() if t.valid_to else "",
            t.status,
            f"{t.confidence:.2f}",
        )
    console.print(table)


@graph_group.command("status")
def graph_status():
    """Print counts for the Chronograph (entities / triples by status)."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        stats = await cg.stats()
        console.print(
            f"[cyan]entities:[/] {stats['entities']}   "
            f"[cyan]triples:[/] {stats['triples']}   "
            f"[cyan]predicates:[/] {stats['predicates']}"
        )
        console.print(
            f"  accepted={stats['accepted']}  proposed={stats['proposed']}  "
            f"rejected={stats['rejected']}  edited={stats['edited']}"
        )

    asyncio.run(_run())


@graph_group.command("query")
@click.argument("entity")
@click.option("--as-of", default=None, help="ISO date (YYYY-MM-DD). Default: today.")
@click.option(
    "--direction",
    type=click.Choice(["subject", "object", "both"]),
    default="both",
)
@click.option(
    "--status",
    type=click.Choice(["proposed", "accepted", "rejected", "edited", "any"]),
    default="accepted",
)
def graph_query(entity: str, as_of: str | None, direction: str, status: str):
    """List triples touching ENTITY valid at AS_OF (default: today)."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        triples = await cg.query_entity(
            entity,
            as_of=as_of,
            direction=direction,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
        )
        if not triples:
            console.print(f"[dim]no {status} triples for {entity} at {as_of or 'today'}[/]")
            return
        _display_triples(triples, f"triples for {entity}")

    asyncio.run(_run())


@graph_group.command("timeline")
@click.argument("entity", required=False)
@click.option("--limit", default=100, type=int)
@click.option(
    "--status",
    type=click.Choice(["proposed", "accepted", "rejected", "edited", "any"]),
    default="accepted",
)
def graph_timeline(entity: str | None, limit: int, status: str):
    """Show the timeline of triples for ENTITY (or all entities)."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        triples = await cg.timeline(entity=entity, status=status, limit=limit)  # type: ignore[arg-type]
        if not triples:
            console.print("[dim]no triples[/]")
            return
        _display_triples(triples, f"timeline — {entity or 'all'}")

    asyncio.run(_run())


@graph_group.command("add")
@click.argument("subject")
@click.argument("predicate")
@click.argument("object_")
@click.option("--from", "valid_from", default=None, help="ISO date (YYYY-MM-DD)")
@click.option("--to", "valid_to", default=None, help="ISO date (YYYY-MM-DD)")
@click.option("--confidence", default=1.0, type=float)
@click.option(
    "--status",
    type=click.Choice(["proposed", "accepted", "edited"]),
    default="accepted",
)
def graph_add(
    subject: str,
    predicate: str,
    object_: str,
    valid_from: str | None,
    valid_to: str | None,
    confidence: float,
    status: str,
):
    """Add a triple — SUBJECT PREDICATE OBJECT (accepted by default)."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        triple = await cg.add_triple(
            subject=subject,
            predicate=predicate,
            object=object_,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=confidence,
            proposer="user",
            status=status,  # type: ignore[arg-type]
        )
        console.print(
            f"[green]OK[/] {triple.id[:10]} {triple.subject} {triple.predicate} {triple.object}"
        )

    asyncio.run(_run())


@graph_group.command("invalidate")
@click.argument("subject")
@click.argument("predicate")
@click.argument("object_")
@click.option("--ended", default=None, help="ISO date when the fact stopped being true")
def graph_invalidate(subject: str, predicate: str, object_: str, ended: str | None):
    """Close the validity window for SUBJECT PREDICATE OBJECT."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        await cg.invalidate(subject, predicate, object_, ended=ended)
        console.print("[green]OK[/] invalidated")

    asyncio.run(_run())


@graph_group.command("proposed")
@click.option("--limit", default=50, type=int)
def graph_proposed(limit: int):
    """List LLM-proposed triples waiting for validation."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        triples = await cg.list_proposed(limit=limit)
        if not triples:
            console.print("[dim]no proposed triples[/]")
            return
        _display_triples(triples, "validation queue")

    asyncio.run(_run())


@graph_group.command("accept")
@click.argument("triple_id")
def graph_accept(triple_id: str):
    """Accept a proposed triple by id."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        try:
            triple = await cg.accept(triple_id)
        except LookupError:
            console.print(f"[red]no triple[/] {triple_id}")
            return
        console.print(f"[green]accepted[/] {triple.id[:10]}")

    asyncio.run(_run())


@graph_group.command("reject")
@click.argument("triple_id")
def graph_reject(triple_id: str):
    """Reject a proposed triple by id."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        try:
            triple = await cg.reject(triple_id)
        except LookupError:
            console.print(f"[red]no triple[/] {triple_id}")
            return
        console.print(f"[yellow]rejected[/] {triple.id[:10]}")

    asyncio.run(_run())


@graph_group.command("edit")
@click.argument("triple_id")
@click.option("--predicate", default=None)
@click.option("--valid-from", default=None)
@click.option("--valid-to", default=None)
@click.option("--confidence", default=None, type=float)
def graph_edit(
    triple_id: str,
    predicate: str | None,
    valid_from: str | None,
    valid_to: str | None,
    confidence: float | None,
):
    """Edit a triple by id — changes identity fields create a new row."""

    async def _run():
        from memgentic.graph import get_chronograph

        cg = await get_chronograph()
        fields: dict = {}
        if predicate is not None:
            fields["predicate"] = predicate
        if valid_from is not None:
            fields["valid_from"] = valid_from
        if valid_to is not None:
            fields["valid_to"] = valid_to
        if confidence is not None:
            fields["confidence"] = confidence
        try:
            triple = await cg.edit(triple_id, **fields)
        except LookupError:
            console.print(f"[red]no triple[/] {triple_id}")
            return
        console.print(f"[green]updated[/] {triple.id[:10]}")

    asyncio.run(_run())


@graph_group.command("extract")
@click.option("--memory", "memory_id", required=True, help="Memory id to extract triples from")
def graph_extract(memory_id: str):
    """Re-run the LLM triple extractor on a single memory."""

    async def _run():
        from memgentic.graph import get_chronograph
        from memgentic.graph.extractor import extract_triples, store_proposed
        from memgentic.processing.llm import LLMClient
        from memgentic.storage.metadata import MetadataStore

        metadata_store = MetadataStore(settings.sqlite_path)
        await metadata_store.initialize()
        try:
            memory = await metadata_store.get_memory(memory_id)
            if memory is None:
                console.print(f"[red]memory not found:[/] {memory_id}")
                return
            llm = LLMClient(settings)
            if not llm.available:
                console.print("[red]no LLM configured[/] — set GOOGLE_API_KEY or enable Ollama")
                return
            cg = await get_chronograph()
            proposed = await extract_triples(memory, llm, cg)
            ids = await store_proposed(proposed, cg)
            console.print(f"[green]proposed[/] {len(ids)} triple(s) from memory {memory_id[:8]}")
        finally:
            await metadata_store.close()

    asyncio.run(_run())


@graph_group.command("backfill")
@click.option("--batch", default=50, type=int, help="Max memories per run")
@click.option("--dry-run", is_flag=True, default=False)
def graph_backfill(batch: int, dry_run: bool):
    """Extract triples from already-ingested enriched memories."""

    async def _run():
        from memgentic.graph import get_chronograph
        from memgentic.graph.extractor import extract_triples, store_proposed
        from memgentic.processing.llm import LLMClient
        from memgentic.storage.metadata import MetadataStore

        metadata_store = MetadataStore(settings.sqlite_path)
        await metadata_store.initialize()
        try:
            llm = LLMClient(settings)
            if not llm.available:
                console.print("[red]no LLM configured[/]")
                return
            cg = await get_chronograph()
            memories = await metadata_store.get_memories_by_filter(limit=batch)
            total = 0
            for mem in memories:
                if mem.capture_profile == "raw":
                    continue
                proposed = await extract_triples(mem, llm, cg)
                if dry_run:
                    console.print(f"{mem.id[:8]} -> {len(proposed)} triple(s)")
                else:
                    await store_proposed(proposed, cg)
                total += len(proposed)
            verb = "would propose" if dry_run else "proposed"
            console.print(f"[green]{verb}[/] {total} triple(s) across {len(memories)} memories")
        finally:
            await metadata_store.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Recall Tiers — ``memgentic briefing``
# ---------------------------------------------------------------------------


def _parse_weights_option(raw: str | None) -> dict[str, float]:
    """Parse ``--weights importance=0.4,recency=0.3`` into a dict.

    Silently drops malformed pairs so a typo in the CLI flag doesn't
    kill the whole briefing. Unknown keys pass through; the scorer
    filters them during construction.
    """
    if not raw:
        return {}
    parsed: dict[str, float] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        try:
            parsed[key.strip()] = float(value.strip())
        except ValueError:
            continue
    return parsed


@main.command()
@click.option(
    "--tier",
    type=click.Choice(["T0", "T1", "T2", "T3", "T4", "default"]),
    default="default",
    help="Tier to render. 'default' renders T0 + T1 (the wake-up bundle).",
)
@click.option("--collection", default=None, help="Scope T1/T2 to a collection name.")
@click.option("--topic", default=None, help="Scope T2 to a topic tag.")
@click.option("--query", default=None, help="Query text for T3 Deep Recall.")
@click.option("--entity", default=None, help="Entity to traverse for T4 Atlas.")
@click.option(
    "--model-context",
    type=int,
    default=None,
    help="Override detected model context window (tokens).",
)
@click.option(
    "--max-tokens",
    type=int,
    default=None,
    help="Clamp the tier's token budget below the tier ceiling.",
)
@click.option(
    "--weights",
    default=None,
    help="Scorer weight overrides, e.g. 'importance=0.4,recency=0.3'.",
)
@click.option(
    "--status",
    "show_status",
    is_flag=True,
    help="Print the RecallStack status (budgets + last-run stats) as JSON.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the briefing as JSON (tier text + token counts).",
)
def briefing(
    tier: str,
    collection: str | None,
    topic: str | None,
    query: str | None,
    entity: str | None,
    model_context: int | None,
    max_tokens: int | None,
    weights: str | None,
    show_status: bool,
    as_json: bool,
):
    """Render a Recall Tiers briefing.

    \b
    Examples:
      memgentic briefing                              T0 + T1 (default)
      memgentic briefing --collection myapp           T1 scoped to a collection
      memgentic briefing --model-context 200000       Tune budget to the model
      memgentic briefing --tier T2 --collection x     Orbit tier (filtered)
      memgentic briefing --tier T3 --query "why graphql"
      memgentic briefing --tier T4 --entity Kai       Knowledge-graph traversal
      memgentic briefing --status                     Stack status JSON
      memgentic briefing --weights importance=0.4,recency=0.3
    """
    import json as _json

    from memgentic.briefing import BriefingContext, RecallStack, load_weights
    from memgentic.graph.knowledge import create_knowledge_graph
    from memgentic.processing.embedder import Embedder
    from memgentic.storage.metadata import MetadataStore
    from memgentic.storage.vectors import VectorStore

    async def _run() -> int:
        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        embedder = Embedder(settings)
        graph = create_knowledge_graph(settings.graph_path)

        await metadata_store.initialize()
        await vector_store.initialize()
        try:
            await graph.load()
        except Exception as exc:  # pragma: no cover — graph is optional
            logger.debug("briefing.cli.graph_load_failed", error=str(exc))

        try:
            overrides = _parse_weights_option(weights)
            resolved_weights = load_weights(overrides)

            ctx = BriefingContext(
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedder=embedder,
                graph=graph,
                collection=collection,
                topic=topic,
                query=query,
                entity=entity,
                model_context=model_context,
                max_tokens=max_tokens,
                weights=resolved_weights,
            )

            stack = RecallStack()

            if show_status:
                status = stack.status()
                console.print_json(_json.dumps(status, default=str))
                return 0

            if tier == "default":
                text = await stack.briefing(ctx)
                status = stack.status()
            else:
                out = await stack.tier_recall(tier, ctx)
                text = out.text
                status = stack.status()

            if as_json:
                payload = {
                    "briefing": text,
                    "tokens": status["last_run"].get("tokens", 0),
                    "tier": tier,
                }
                console.print_json(_json.dumps(payload, default=str))
            else:
                console.print(text)
            return 0
        finally:
            await embedder.close()
            await metadata_store.close()
            await vector_store.close()

    exit_code = asyncio.run(_run())
    if exit_code:
        raise SystemExit(exit_code)


# ---------------------------------------------------------------------------
# Retention — self-cleaning (clean) + garbage collection (gc)
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Actually hard-delete. Without this flag the command is a dry run.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt when applying.")
@click.option("--limit", default=10_000, show_default=True, help="Max candidates to scan.")
def gc(apply_changes: bool, yes: bool, limit: int):
    """Garbage-collect expired archived/superseded memories (retention).

    \b
    Dry-run by default — prints what WOULD be permanently deleted. With --apply
    it hard-deletes rows that are ALREADY archived/superseded AND older than
    settings.hard_delete_archived_after_days (and removes their vectors).
    Pinned and mcp_tool memories are NEVER deleted. Active rows are never
    touched. Set hard_delete_archived_after_days=0 to disable GC entirely.
    """
    from memgentic.processing.retention import run_gc
    from memgentic.storage.metadata import MetadataStore
    from memgentic.storage.vectors import VectorStore

    async def _run():
        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)
        try:
            if settings.hard_delete_archived_after_days <= 0:
                console.print(
                    "[yellow]GC is disabled[/] (hard_delete_archived_after_days=0). "
                    "Set it > 0 to enable retention."
                )
                return

            preview = await run_gc(
                metadata_store=metadata_store,
                settings=settings,
                vector_store=vector_store,
                limit=limit,
            )
            noun = "memory" if preview.candidates == 1 else "memories"
            console.print(
                f"[cyan]GC preview[/]: {preview.candidates} archived/superseded {noun} "
                f"older than {preview.grace_days} day(s) eligible for hard deletion."
            )
            for mid in preview.deleted_ids[:20]:
                console.print(f"  [dim]- {mid}[/]")
            if preview.candidates > 20:
                console.print(f"  [dim]... and {preview.candidates - 20} more[/]")

            if not apply_changes:
                console.print("[yellow]Dry run[/] — re-run with --apply to delete.")
                return
            if preview.candidates == 0:
                return
            if not yes and not click.confirm(f"Permanently delete {preview.candidates} {noun}?"):
                return

            report = await run_gc(
                metadata_store=metadata_store,
                settings=settings,
                vector_store=vector_store,
                apply=True,
                limit=limit,
            )
            console.print(
                f"[green]GC done[/]: hard-deleted {report.hard_deleted}, "
                f"vectors removed {report.vectors_deleted}."
            )
            for err in report.errors:
                console.print(f"  [red]{err}[/]")
        finally:
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


@main.command()
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Actually archive. Without this flag the command is a dry run.",
)
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt when applying.")
@click.option("--limit", default=50_000, show_default=True, help="Max active memories to scan.")
def clean(apply_changes: bool, yes: bool, limit: int):
    """One-time bulk cleanup — archive duplicate clusters + stored noise.

    \b
    Keeps the best of each duplicate cluster (pinned > mcp_tool > importance >
    newest) and archives the rest, plus obvious noise the capture-hygiene
    filters now catch (meta-prompts, acknowledgments, tool dumps). Soft-delete
    only (status=archived) so it stays recoverable — hard deletion is left to
    `memgentic gc` after the grace period. NEVER touches pinned or mcp_tool
    memories. Dry-run by default; --apply to archive.
    """
    from memgentic.processing.retention import run_clean
    from memgentic.storage.metadata import MetadataStore
    from memgentic.storage.vectors import VectorStore

    async def _run():
        metadata_store = MetadataStore(settings.sqlite_path)
        vector_store = VectorStore(settings)
        await metadata_store.initialize()
        await vector_store.initialize(metadata_store)
        try:
            preview = await run_clean(metadata_store=metadata_store, limit=limit)

            table = Table(title="Clean preview")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            table.add_row("Duplicate clusters", str(preview.dup_clusters))
            table.add_row("Duplicate rows to archive", str(preview.dup_archived))
            table.add_row("Noise rows to archive", str(preview.noise_archived))
            table.add_row("Total to archive", str(preview.total_archived))
            table.add_row("Preserved (pinned)", str(preview.preserved_pinned))
            table.add_row("Preserved (mcp_tool)", str(preview.preserved_mcp_tool))
            console.print(table)
            if preview.by_content_type:
                breakdown = ", ".join(
                    f"{k}={v}" for k, v in sorted(preview.by_content_type.items())
                )
                console.print(f"[dim]By content type:[/] {breakdown}")

            if not apply_changes:
                console.print("[yellow]Dry run[/] — re-run with --apply to archive.")
                return
            if preview.total_archived == 0:
                return
            noun = "memory" if preview.total_archived == 1 else "memories"
            if not yes and not click.confirm(f"Archive {preview.total_archived} {noun}?"):
                return

            report = await run_clean(
                metadata_store=metadata_store,
                vector_store=vector_store,
                apply=True,
                limit=limit,
            )
            console.print(
                f"[green]Clean done[/]: archived {report.total_archived} "
                f"(dups={report.dup_archived}, noise={report.noise_archived})."
            )
            for err in report.errors:
                console.print(f"  [red]{err}[/]")
        finally:
            await metadata_store.close()
            await vector_store.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Watchers — cross-tool automatic capture
# ---------------------------------------------------------------------------


@main.group(name="watchers")
def watchers_group():
    """Install and manage cross-tool capture watchers.

    \b
    Subcommands:
      install   Install hooks / file watchers for a specific tool
      uninstall Reverse install
      enable    Re-enable a previously-disabled watcher
      disable   Stop capturing without uninstalling
      status    Show per-tool capture status
      logs      Tail recent events for a tool
    """


def _reject_unknown_tool(tool: str) -> None:
    from memgentic.daemon.watchers import ALL_TOOLS

    if tool not in ALL_TOOLS:
        console.print(f"[red]Unknown tool:[/] {tool}. Known: {', '.join(ALL_TOOLS)}")
        raise SystemExit(1)


@watchers_group.command(name="install")
@click.option("--tool", required=True, help="Tool name (e.g. claude_code, codex, gemini_cli)")
def watchers_install(tool: str):
    """Install watcher mechanism for TOOL."""
    from memgentic.daemon.watcher_install import install

    _reject_unknown_tool(tool)
    result = install(tool)
    tag = "[green]OK[/]" if result.changed else "[yellow]noop[/]"
    console.print(f"{tag} {tool}: {result.message}")


@watchers_group.command(name="uninstall")
@click.option("--tool", required=True)
def watchers_uninstall(tool: str):
    """Uninstall watcher for TOOL."""
    from memgentic.daemon.watcher_install import uninstall
    from memgentic.daemon.watcher_state import WatcherStateStore

    _reject_unknown_tool(tool)
    result = uninstall(tool)
    tag = "[green]OK[/]" if result.changed else "[yellow]noop[/]"
    console.print(f"{tag} {tool}: {result.message}")
    # Clear state row so status no longer shows it as installed.
    WatcherStateStore().remove_tool(tool)


@watchers_group.command(name="enable")
@click.option("--tool", required=True)
def watchers_enable(tool: str):
    """Re-enable a previously-disabled watcher."""
    from memgentic.daemon.watcher_state import WatcherStateStore

    _reject_unknown_tool(tool)
    WatcherStateStore().upsert_status(tool, enabled=True)
    console.print(f"[green]OK[/] {tool} enabled")


@watchers_group.command(name="disable")
@click.option("--tool", required=True)
def watchers_disable(tool: str):
    """Stop capturing without uninstalling."""
    from memgentic.daemon.watcher_state import WatcherStateStore

    _reject_unknown_tool(tool)
    WatcherStateStore().upsert_status(tool, enabled=False)
    console.print(f"[yellow]OK[/] {tool} disabled")


@watchers_group.command(name="status")
def watchers_status():
    """Show per-tool watcher status across all known tools."""
    from memgentic.daemon.watcher_state import WatcherStateStore
    from memgentic.daemon.watchers import ALL_TOOLS, classify_tool

    store = WatcherStateStore()
    statuses = {s.tool: s for s in store.list_statuses()}
    table = Table(title="Watchers")
    table.add_column("tool")
    table.add_column("mechanism")
    table.add_column("installed")
    table.add_column("enabled")
    table.add_column("last capture")
    for tool in ALL_TOOLS:
        row = statuses.get(tool)
        table.add_row(
            tool,
            classify_tool(tool),
            "yes" if row and row.installed_at else "no",
            "yes" if row and row.enabled else "no",
            str(getattr(row, "last_captured_at", None) or "—"),
        )
    console.print(table)


@watchers_group.command(name="logs")
@click.option("--tool", required=True)
@click.option("--limit", default=50)
def watchers_logs(tool: str, limit: int):
    """Tail recent events for TOOL."""
    from memgentic.daemon.watcher_state import WatcherStateStore

    _reject_unknown_tool(tool)
    store = WatcherStateStore()
    list_logs = getattr(store, "list_logs", None)
    entries: list[dict] = list_logs(tool, limit=limit) if callable(list_logs) else []  # type: ignore[assignment]
    if not entries:
        console.print("No log entries yet.")
        return
    for entry in entries:
        console.print(
            f"{entry.get('ts', '?')} [{entry.get('level', 'info')}] {entry.get('message', '')}"
        )


if __name__ == "__main__":
    main()
