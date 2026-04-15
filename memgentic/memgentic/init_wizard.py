"""Memgentic init wizard -- one-command setup for all AI tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog
from rich.console import Console
from rich.panel import Panel

from memgentic.config import settings

console = Console()
logger = structlog.get_logger()

MEMGENTIC_START_MARKER = "<!-- memgentic:start -->"
MEMGENTIC_END_MARKER = "<!-- memgentic:end -->"


@dataclass
class DetectedTool:
    """Represents a detected AI CLI tool."""

    name: str
    command: str | None
    data_dir: Path | None
    context_file: Path
    mcp_method: str  # "claude_cli" | "gemini_json" | "codex_cli"
    detected: bool = False
    command_found: bool = False
    data_found: bool = False


def detect_tools() -> list[DetectedTool]:
    """Detect installed AI CLI tools."""
    tools = [
        DetectedTool(
            name="Claude Code",
            command="claude",
            data_dir=Path.home() / ".claude",
            context_file=Path.home() / ".claude" / "CLAUDE.md",
            mcp_method="claude_cli",
        ),
        DetectedTool(
            name="Gemini CLI",
            command="gemini",
            data_dir=Path.home() / ".gemini",
            context_file=Path.home() / ".gemini" / "GEMINI.md",
            mcp_method="gemini_json",
        ),
        DetectedTool(
            name="Codex CLI",
            command="codex",
            data_dir=Path.home() / ".codex",
            context_file=Path.home() / ".codex" / "AGENTS.md",
            mcp_method="codex_cli",
        ),
    ]

    for tool in tools:
        if tool.command:
            tool.command_found = shutil.which(tool.command) is not None
        if tool.data_dir:
            tool.data_found = tool.data_dir.is_dir()
        tool.detected = tool.command_found or tool.data_found

    return tools


def configure_mcp(tool: DetectedTool, dry_run: bool = False) -> bool:
    """Configure MCP for a detected tool."""
    if tool.mcp_method == "claude_cli":
        return _configure_mcp_claude(dry_run)
    elif tool.mcp_method == "gemini_json":
        return _configure_mcp_gemini(dry_run)
    elif tool.mcp_method == "codex_cli":
        return _configure_mcp_codex(dry_run)
    return False


def _configure_mcp_claude(dry_run: bool) -> bool:
    """Add Memgentic MCP server to Claude Code via CLI."""
    if not shutil.which("claude"):
        return False
    if dry_run:
        console.print("  [dim]Would run: claude mcp add mneme[/]")
        return True
    try:
        result = subprocess.run(
            [
                "claude",
                "mcp",
                "add",
                "--transport",
                "stdio",
                "--scope",
                "user",
                "memgentic",
                "--",
                "uvx",
                "memgentic",
                "serve",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("init.claude_mcp_failed", error=str(e))
        return False


def _configure_mcp_gemini(dry_run: bool) -> bool:
    """Add Memgentic MCP server to Gemini CLI via settings.json."""
    settings_path = Path.home() / ".gemini" / "settings.json"

    if dry_run:
        console.print(f"  [dim]Would write to: {settings_path}[/]")
        return True

    try:
        existing: dict = {}
        if settings_path.exists():
            existing = json.loads(settings_path.read_text())

        mcp_servers = existing.get("mcpServers", {})
        if "memgentic" in mcp_servers:
            return True  # Already configured

        mcp_servers["memgentic"] = {
            "command": "uvx",
            "args": ["memgentic", "serve"],
        }
        existing["mcpServers"] = mcp_servers

        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(existing, indent=2))
        return True
    except Exception as e:
        logger.warning("init.gemini_mcp_failed", error=str(e))
        return False


def _configure_mcp_codex(dry_run: bool) -> bool:
    """Add Memgentic MCP server to Codex CLI."""
    if not shutil.which("codex"):
        return False
    if dry_run:
        console.print("  [dim]Would run: codex mcp add mneme[/]")
        return True
    try:
        result = subprocess.run(
            ["codex", "mcp", "add", "memgentic", "--", "uvx", "memgentic", "serve"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("init.codex_mcp_failed", error=str(e))
        return False


def _load_template() -> str:
    """Load memory instructions template from package resources."""
    from importlib.resources import files

    return files("memgentic.templates").joinpath("memory_instructions.md").read_text()


def inject_memory_instructions(context_file: Path, dry_run: bool = False) -> bool:
    """Inject or update memory instructions in a context file."""
    template = _load_template()

    if dry_run:
        console.print(f"  [dim]Would inject into: {context_file}[/]")
        return True

    try:
        existing = ""
        if context_file.exists():
            existing = context_file.read_text(encoding="utf-8")

        if MEMGENTIC_START_MARKER in existing:
            # Replace existing section
            start = existing.index(MEMGENTIC_START_MARKER)
            end = existing.index(MEMGENTIC_END_MARKER) + len(MEMGENTIC_END_MARKER)
            updated = existing[:start] + template.strip() + existing[end:]
        else:
            # Append
            separator = (
                "\n\n"
                if existing and not existing.endswith("\n\n")
                else "\n"
                if existing and not existing.endswith("\n")
                else ""
            )
            updated = existing + separator + template.strip() + "\n"

        context_file.parent.mkdir(parents=True, exist_ok=True)
        context_file.write_text(updated, encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("init.inject_failed", file=str(context_file), error=str(e))
        return False


async def _check_ollama(model_name: str) -> tuple[bool, bool]:
    """Check if Ollama is running and model is available."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            has_model = any(model_name in n for n in models)
            return True, has_model
    except Exception:
        return False, False


async def run_init(dry_run: bool = False, skip_import: bool = False) -> None:
    """Main init wizard orchestrator."""
    console.print(
        Panel.fit(
            "[bold cyan]Memgentic -- Universal AI Memory Layer[/]\n"
            "[dim]One-command setup for cross-tool AI memory[/]",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print("[yellow]DRY RUN -- no changes will be made[/]\n")

    # Step 1: Detect tools
    console.print("[bold]Detecting AI tools...[/]")
    tools = detect_tools()

    detected_count = 0
    for tool in tools:
        if tool.detected:
            detected_count += 1
            parts = []
            if tool.command_found:
                parts.append("CLI found")
            if tool.data_found:
                parts.append("data dir found")
            console.print(f"  [green]OK[/] {tool.name} ({', '.join(parts)})")
        else:
            console.print(f"  [dim]X {tool.name} (not found)[/]")

    if detected_count == 0:
        console.print(
            "\n[yellow]No AI tools detected. "
            "Install Claude Code, Gemini CLI, or Codex CLI first.[/]"
        )
        return

    console.print()

    # Step 2: Configure MCP + inject instructions
    console.print("[bold]Configuring MCP servers...[/]")
    for tool in tools:
        if not tool.detected:
            continue
        if not tool.command_found:
            console.print(
                f"  [yellow]![/] {tool.name}: CLI not found, "
                "skipping MCP config (data dir exists for import)"
            )
            continue
        ok = configure_mcp(tool, dry_run)
        status = "[green]OK[/]" if ok else "[red]X[/]"
        console.print(f"  {status} {tool.name}: MCP server {'configured' if ok else 'FAILED'}")

    console.print()
    console.print("[bold]Adding memory instructions...[/]")
    for tool in tools:
        if not tool.detected:
            continue
        ok = inject_memory_instructions(tool.context_file, dry_run)
        status = "[green]OK[/]" if ok else "[red]X[/]"
        console.print(f"  {status} {tool.context_file.name}")

    console.print()

    # Step 3: Check Ollama + model
    console.print("[bold]Checking embedding model...[/]")
    ollama_ok, model_ok = await _check_ollama(settings.embedding_model)

    if ollama_ok and model_ok:
        console.print(f"  [green]OK[/] Ollama running, model {settings.embedding_model} ready")
    elif ollama_ok and not model_ok:
        console.print(
            f"  [yellow]![/] Ollama running but model {settings.embedding_model} not found"
        )
        if not dry_run:
            console.print(f"  [cyan]Pull with: ollama pull {settings.embedding_model}[/]")
    else:
        console.print(f"  [yellow]![/] Ollama not running at {settings.ollama_url}")
        console.print("  [cyan]Install: https://ollama.com/download[/]")

    # Step 4: Ensure data directory
    if not dry_run:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"\n  [green]OK[/] Data directory: {settings.data_dir}")

    # Step 5: Import (optional)
    if not skip_import and not dry_run and ollama_ok and model_ok:
        import click as click_mod

        if click_mod.confirm("\nImport existing conversations now?", default=True):
            console.print("\n[cyan]Importing existing conversations...[/]")
            # Reuse existing import logic
            from memgentic.adapters import get_import_adapters
            from memgentic.graph.knowledge import create_knowledge_graph
            from memgentic.processing.embedder import Embedder
            from memgentic.processing.llm import LLMClient
            from memgentic.processing.pipeline import IngestionPipeline
            from memgentic.storage.metadata import MetadataStore
            from memgentic.storage.vectors import VectorStore

            metadata_store = MetadataStore(settings.sqlite_path)
            vector_store = VectorStore(settings)
            embedder = Embedder(settings)
            llm_client = LLMClient(settings)
            graph = create_knowledge_graph(settings.graph_path)
            await graph.load()
            pipeline = IngestionPipeline(
                settings,
                metadata_store,
                vector_store,
                embedder,
                llm_client=llm_client,
                graph=graph,
            )

            await metadata_store.initialize()
            await vector_store.initialize()

            try:
                adapters = get_import_adapters()
                total_imported = 0
                for adapter in adapters:
                    files = adapter.discover_files()
                    if not files:
                        continue
                    console.print(f"  [cyan]{adapter.platform.value}:[/] {len(files)} files")
                    for f in files:
                        try:
                            session_id = await adapter.get_session_id(f)
                            chunks = await adapter.parse_file(f)
                            if chunks:
                                memories = await pipeline.ingest_conversation(
                                    chunks=chunks,
                                    platform=adapter.platform,
                                    session_id=session_id,
                                    file_path=str(f),
                                )
                                total_imported += len(memories)
                        except Exception:
                            pass
                console.print(f"  [green]OK[/] {total_imported} memories imported")
            finally:
                await graph.save()
                await embedder.close()
                await metadata_store.close()
                await vector_store.close()
    elif skip_import:
        console.print("\n[dim]Skipping import (--skip-import)[/]")

    # Step 6: Summary
    console.print()
    console.print(
        Panel.fit(
            "[bold green]Memgentic is ready![/]\n\n"
            f"[cyan]{detected_count}[/] AI tool"
            f"{'s' if detected_count != 1 else ''} configured with shared memory.\n"
            "Every conversation will be captured. Every tool has context.\n\n"
            "[dim]Next steps:[/]\n"
            "  - Start a new session in any configured tool\n"
            "  - The AI will automatically load memory context\n"
            "  - Run [bold]memgentic daemon[/] for real-time capture\n"
            '  - Run [bold]memgentic search "query"[/] to search your memories',
            border_style="green",
        )
    )
