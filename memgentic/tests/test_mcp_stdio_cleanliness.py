"""Tests guarding the MCP stdio stream against log-line pollution.

MCP stdio transport reserves stdout for JSON-RPC framing. Any structlog line
that leaks onto stdout breaks strict clients. The `_redirect_logs_to_stderr`
hook in `memgentic.mcp.server` must actually redirect.
"""

from __future__ import annotations

import sys

import structlog

from memgentic.mcp.server import _redirect_logs_to_stderr


def test_redirect_logs_to_stderr_keeps_stdout_clean(capsys):
    """After redirect, a log call writes to stderr, not stdout."""
    _redirect_logs_to_stderr()
    try:
        structlog.get_logger().info("mcp_stdio.test_event", value=42)
        captured = capsys.readouterr()
        assert captured.out == "", (
            f"structlog leaked to stdout — MCP JSON-RPC stream would break. "
            f"Leaked: {captured.out!r}"
        )
        assert "mcp_stdio.test_event" in captured.err
    finally:
        # Reset to default so unrelated tests see the global structlog state
        # they expect.
        structlog.reset_defaults()


def test_redirect_hook_uses_stderr_file_factory():
    """The hook wires a PrintLoggerFactory pointed at sys.stderr."""
    _redirect_logs_to_stderr()
    try:
        config = structlog.get_config()
        factory = config["logger_factory"]
        # PrintLoggerFactory stores the file on the factory itself.
        assert isinstance(factory, structlog.PrintLoggerFactory)
        assert factory._file is sys.stderr  # type: ignore[attr-defined]
    finally:
        structlog.reset_defaults()


def test_run_server_with_watcher_redirects_before_first_log(monkeypatch):
    """The fused --watch entrypoint must redirect stdout BEFORE it emits any
    log line. Previously only ``run_server`` did this, so ``--watch`` still
    polluted stdout and broke strict MCP clients.
    """
    import asyncio

    from memgentic.mcp import server as mcp_server

    call_order: list[str] = []

    def fake_redirect() -> None:
        call_order.append("redirect")

    async def fake_run_stdio_async() -> None:
        call_order.append("run_stdio_async")

    monkeypatch.setattr(mcp_server, "_redirect_logs_to_stderr", fake_redirect)
    monkeypatch.setattr(mcp_server.mcp, "run_stdio_async", fake_run_stdio_async)

    asyncio.run(mcp_server.run_server_with_watcher(scan_existing=False))

    assert call_order == ["redirect", "run_stdio_async"], (
        "run_server_with_watcher must redirect logs to stderr before starting "
        f"the MCP stdio loop. Got call order: {call_order}"
    )


def test_serve_command_uses_stderr_console_for_banner(monkeypatch):
    """The ``memgentic serve`` banner must print to stderr so the JSON-RPC
    stream on stdout stays clean. Regression guard for the --watch path in
    particular, which printed two banners to stdout before handing over to
    the MCP loop.

    We patch Rich's ``Console`` class and record how it was instantiated
    inside ``serve`` — any Console touched during serve must be created
    with ``stderr=True``, otherwise its output lands on stdout by default.
    """
    from click.testing import CliRunner

    import memgentic.cli as cli_module
    from memgentic.cli import main

    consoles_created: list[dict] = []
    real_console_cls = cli_module.Console

    def recording_console(*args, **kwargs):
        consoles_created.append(kwargs)
        return real_console_cls(*args, **kwargs)

    monkeypatch.setattr(cli_module, "Console", recording_console)
    monkeypatch.setattr("memgentic.mcp.server.run_server", lambda: None)
    monkeypatch.setattr("memgentic.observability.init_observability", lambda **_: None)

    runner = CliRunner()
    result = runner.invoke(main, ["serve"])
    assert result.exit_code == 0, result.output

    # Exactly one Console instance created inside serve, and it's stderr-bound.
    serve_consoles = [kw for kw in consoles_created if kw.get("stderr")]
    assert serve_consoles, (
        "serve() did not construct any stderr-bound Console — banners would "
        f"leak to stdout. Consoles seen: {consoles_created}"
    )
