"""Watcher state store — per-tool/per-file offsets and status tracking.

Uses a dedicated SQLite database at ``~/.memgentic/watcher_state.sqlite`` so
the Watchers subsystem stays isolated from the main metadata DB. This makes
it safe to reset Watcher state (e.g. re-scan from scratch) without touching
the memory store.

Tables
------
``watcher_state``
    Tracks the byte offset last consumed from each conversation file for
    each (tool, session) pair so file watchers can incrementally read deltas
    instead of re-parsing whole files.

``watcher_status``
    Tracks per-tool install status, enabled flag, and last error for the
    CLI and dashboard to report from.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watcher_state (
    tool TEXT NOT NULL,
    session_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    last_offset INTEGER NOT NULL DEFAULT 0,
    last_captured_at TEXT,
    captured_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tool, session_id, file_path)
);

CREATE TABLE IF NOT EXISTS watcher_status (
    tool TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    installed_at TEXT,
    last_error TEXT,
    last_error_at TEXT
);

CREATE TABLE IF NOT EXISTS watcher_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watcher_logs_tool_created
    ON watcher_logs(tool, created_at DESC);
"""


def _default_db_path() -> Path:
    return Path.home() / ".memgentic" / "watcher_state.sqlite"


@dataclass
class WatcherState:
    tool: str
    session_id: str
    file_path: str
    last_offset: int = 0
    last_captured_at: str | None = None
    captured_count: int = 0


@dataclass
class WatcherStatus:
    tool: str
    enabled: bool = True
    installed_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None


@dataclass
class WatcherLogEntry:
    id: int
    tool: str
    level: str
    message: str
    created_at: str


class WatcherStateStore:
    """Thin synchronous wrapper around the watcher_state.sqlite database.

    The store is safe to instantiate repeatedly — it reopens the connection
    on each call. All writes happen inside short transactions so multiple
    processes (daemon, CLI) can read/write concurrently via SQLite's default
    locking.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # -- connection helpers ------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- offsets / state ---------------------------------------------------

    def get_offset(self, tool: str, session_id: str, file_path: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_offset FROM watcher_state "
                "WHERE tool=? AND session_id=? AND file_path=?",
                (tool, session_id, file_path),
            ).fetchone()
            return int(row["last_offset"]) if row else 0

    def update_state(
        self,
        *,
        tool: str,
        session_id: str,
        file_path: str,
        new_offset: int,
        captured_increment: int = 0,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watcher_state
                    (tool, session_id, file_path, last_offset, last_captured_at, captured_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tool, session_id, file_path) DO UPDATE SET
                    last_offset = excluded.last_offset,
                    last_captured_at = excluded.last_captured_at,
                    captured_count = captured_count + ?
                """,
                (
                    tool,
                    session_id,
                    file_path,
                    new_offset,
                    now,
                    captured_increment,
                    captured_increment,
                ),
            )

    def reset_file(self, tool: str, session_id: str, file_path: str) -> None:
        """Reset offset for a specific file (e.g. after rotation)."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM watcher_state WHERE tool=? AND session_id=? AND file_path=?",
                (tool, session_id, file_path),
            )

    def list_states(self, tool: str | None = None) -> list[WatcherState]:
        sql = "SELECT * FROM watcher_state"
        params: tuple = ()
        if tool:
            sql += " WHERE tool=?"
            params = (tool,)
        sql += " ORDER BY last_captured_at DESC NULLS LAST"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            WatcherState(
                tool=row["tool"],
                session_id=row["session_id"],
                file_path=row["file_path"],
                last_offset=row["last_offset"] or 0,
                last_captured_at=row["last_captured_at"],
                captured_count=row["captured_count"] or 0,
            )
            for row in rows
        ]

    def total_captured(self, tool: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(captured_count), 0) AS total FROM watcher_state WHERE tool=?",
                (tool,),
            ).fetchone()
            return int(row["total"]) if row else 0

    def last_captured_at(self, tool: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(last_captured_at) AS ts FROM watcher_state WHERE tool=?",
                (tool,),
            ).fetchone()
            return row["ts"] if row else None

    def captured_count_today(self, tool: str) -> int:
        """Sum ``ingested N`` events from ``watcher_logs`` for ``tool`` since UTC midnight.

        Parses the ``ingested <N> memory/memories …`` messages that both the
        hook dispatcher and the file-watcher base emit on every successful
        capture. Returns 0 when no rows match — including when ``level`` isn't
        ``info`` or the message format doesn't parse.
        """
        import re

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pattern = re.compile(r"^ingested\s+(\d+)\s+memor", re.IGNORECASE)
        total = 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message FROM watcher_logs
                WHERE tool = ?
                  AND level = 'info'
                  AND created_at >= ?
                  AND message LIKE 'ingested %'
                """,
                (tool, f"{today}T00:00:00+00:00"),
            ).fetchall()
        for row in rows:
            match = pattern.match(row["message"] or "")
            if match:
                total += int(match.group(1))
        return total

    # -- status ------------------------------------------------------------

    def get_status(self, tool: str) -> WatcherStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM watcher_status WHERE tool=?",
                (tool,),
            ).fetchone()
        if not row:
            return None
        return WatcherStatus(
            tool=row["tool"],
            enabled=bool(row["enabled"]),
            installed_at=row["installed_at"],
            last_error=row["last_error"],
            last_error_at=row["last_error_at"],
        )

    def upsert_status(
        self,
        tool: str,
        *,
        enabled: bool | None = None,
        installed_at: str | None = None,
        clear_error: bool = False,
    ) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT enabled, installed_at FROM watcher_status WHERE tool=?",
                (tool,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO watcher_status (tool, enabled, installed_at) VALUES (?, ?, ?)",
                    (
                        tool,
                        int(enabled if enabled is not None else True),
                        installed_at or datetime.now(UTC).isoformat(),
                    ),
                )
                return
            new_enabled = enabled if enabled is not None else bool(existing["enabled"])
            new_installed = installed_at or existing["installed_at"]
            if clear_error:
                conn.execute(
                    """
                    UPDATE watcher_status
                    SET enabled=?, installed_at=?, last_error=NULL, last_error_at=NULL
                    WHERE tool=?
                    """,
                    (int(new_enabled), new_installed, tool),
                )
            else:
                conn.execute(
                    "UPDATE watcher_status SET enabled=?, installed_at=? WHERE tool=?",
                    (int(new_enabled), new_installed, tool),
                )

    def set_enabled(self, tool: str, enabled: bool) -> None:
        self.upsert_status(tool, enabled=enabled)

    def record_error(self, tool: str, message: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watcher_status (tool, enabled, last_error, last_error_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(tool) DO UPDATE SET
                    last_error = excluded.last_error,
                    last_error_at = excluded.last_error_at
                """,
                (tool, message, now),
            )

    def remove_tool(self, tool: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM watcher_status WHERE tool=?", (tool,))
            conn.execute("DELETE FROM watcher_state WHERE tool=?", (tool,))
            conn.execute("DELETE FROM watcher_logs WHERE tool=?", (tool,))

    def list_statuses(self) -> list[WatcherStatus]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM watcher_status ORDER BY tool").fetchall()
        return [
            WatcherStatus(
                tool=row["tool"],
                enabled=bool(row["enabled"]),
                installed_at=row["installed_at"],
                last_error=row["last_error"],
                last_error_at=row["last_error_at"],
            )
            for row in rows
        ]

    # -- logs --------------------------------------------------------------

    def append_log(self, tool: str, message: str, level: str = "info") -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO watcher_logs (tool, level, message, created_at) VALUES (?, ?, ?, ?)",
                (tool, level, message, now),
            )
            # Trim: keep last ~500 per tool to bound the table.
            conn.execute(
                """
                DELETE FROM watcher_logs
                WHERE tool = ? AND id NOT IN (
                    SELECT id FROM watcher_logs
                    WHERE tool = ?
                    ORDER BY created_at DESC
                    LIMIT 500
                )
                """,
                (tool, tool),
            )

    def tail_logs(self, tool: str, limit: int = 50) -> list[WatcherLogEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM watcher_logs WHERE tool=? ORDER BY created_at DESC LIMIT ?",
                (tool, max(1, min(limit, 1000))),
            ).fetchall()
        return [
            WatcherLogEntry(
                id=row["id"],
                tool=row["tool"],
                level=row["level"],
                message=row["message"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


__all__ = [
    "WatcherState",
    "WatcherStateStore",
    "WatcherStatus",
    "WatcherLogEntry",
]
