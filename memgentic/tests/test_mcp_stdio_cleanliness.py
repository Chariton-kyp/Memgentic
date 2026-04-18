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
