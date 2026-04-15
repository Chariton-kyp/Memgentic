"""Tests for the best-effort CursorAdapter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from memgentic.adapters.cursor import CursorAdapter
from memgentic.models import Platform


def _make_cursor_db(path: Path, rows: list[tuple[str, str]]) -> None:
    """Create a minimal Cursor-style state.vscdb."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        conn.executemany(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class TestCursorAdapter:
    def test_platform(self):
        assert CursorAdapter().platform == Platform.CURSOR

    def test_file_patterns(self):
        assert "state.vscdb" in CursorAdapter().file_patterns

    async def test_parse_extracts_chat_text(self, tmp_path: Path):
        db_path = tmp_path / "state.vscdb"
        payload = json.dumps(
            {
                "tabs": [
                    {
                        "messages": [
                            {
                                "text": (
                                    "We decided to use FastAPI for the backend "
                                    "because it supports async natively and has "
                                    "great Pydantic integration."
                                )
                            },
                            {"text": "short"},  # below min length — skipped
                        ]
                    }
                ]
            }
        )
        _make_cursor_db(
            db_path,
            rows=[
                ("workbench.panel.aichat.state", payload),
                ("unrelated.key", "noise"),
            ],
        )

        adapter = CursorAdapter()
        chunks = await adapter.parse_file(db_path)

        assert len(chunks) >= 1
        assert any("FastAPI" in c.content for c in chunks)

    async def test_parse_missing_itemtable(self, tmp_path: Path):
        """Adapter returns [] when the DB has no ItemTable."""
        db_path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()

        chunks = await CursorAdapter().parse_file(db_path)
        assert chunks == []

    async def test_parse_corrupt_file(self, tmp_path: Path):
        """Adapter fails gracefully on non-sqlite input."""
        bad = tmp_path / "state.vscdb"
        bad.write_bytes(b"not a sqlite database")
        chunks = await CursorAdapter().parse_file(bad)
        assert chunks == []

    async def test_session_id_from_parent_dir(self, tmp_path: Path):
        workspace = tmp_path / "abc123hash"
        workspace.mkdir()
        db = workspace / "state.vscdb"
        db.touch()
        sid = await CursorAdapter().get_session_id(db)
        assert sid == "abc123hash"


@pytest.mark.parametrize(
    "value,expected_contains",
    [
        (b'{"content": "This is a long enough content string for extraction"}', "long enough"),
        ("not json but long enough to pass the length filter so it goes through", "long enough"),
    ],
)
def test_extract_texts(value, expected_contains):
    adapter = CursorAdapter()
    texts = adapter._extract_texts(value)
    assert any(expected_contains in t for t in texts)
