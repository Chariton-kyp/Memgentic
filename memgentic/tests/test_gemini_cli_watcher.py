"""Tests for the Gemini CLI delta-aware file watcher.

Exercises ``parse_delta`` directly (without watchdog) so we can focus on
the delta/offset logic and partial-write behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memgentic.daemon.dedup import SemanticDeduper
from memgentic.daemon.file_watchers.base import WatcherContext
from memgentic.daemon.file_watchers.gemini_cli import GeminiCliFileWatcher
from memgentic.daemon.watcher_state import WatcherStateStore
from memgentic.models import Platform


class _NoopPipeline:
    async def ingest_conversation(self, **kwargs):  # noqa: D401
        return []


class _NoopEmbedder:
    async def embed(self, text: str):
        return [0.0]


class _NoopVectorStore:
    async def search(self, **kwargs):
        return []


def _write_json(path: Path, messages: list[dict]) -> None:
    path.write_text(json.dumps({"messages": messages}), encoding="utf-8")


@pytest.fixture()
def ctx(tmp_path: Path) -> WatcherContext:
    return WatcherContext(
        settings=None,  # type: ignore[arg-type]
        pipeline=_NoopPipeline(),  # type: ignore[arg-type]
        deduper=SemanticDeduper(_NoopEmbedder(), _NoopVectorStore()),  # type: ignore[arg-type]
        state_store=WatcherStateStore(tmp_path / "state.db"),
    )


@pytest.mark.asyncio
async def test_parse_delta_returns_all_on_fresh_file(ctx: WatcherContext, tmp_path: Path) -> None:
    watcher = GeminiCliFileWatcher(ctx)
    file_path = tmp_path / "sess.json"
    messages = [
        {"role": "user", "parts": [{"text": "hello this is a longer first turn"}]},
        {"role": "model", "parts": [{"text": "sure, responding to the first turn"}]},
    ]
    _write_json(file_path, messages)

    delta = await watcher.parse_delta(file_path, last_offset=0)
    assert delta is not None
    assert delta.new_offset == len(messages)
    assert len(delta.chunks) == 1  # one exchange


@pytest.mark.asyncio
async def test_parse_delta_skips_unchanged(ctx: WatcherContext, tmp_path: Path) -> None:
    watcher = GeminiCliFileWatcher(ctx)
    file_path = tmp_path / "sess.json"
    _write_json(
        file_path,
        [
            {"role": "user", "parts": [{"text": "hello longer than fifty chars please"}]},
            {"role": "model", "parts": [{"text": "hi back with enough length to matter"}]},
        ],
    )

    delta = await watcher.parse_delta(file_path, last_offset=2)
    assert delta is not None
    assert delta.chunks == []
    assert delta.new_offset == 2


@pytest.mark.asyncio
async def test_parse_delta_incremental(ctx: WatcherContext, tmp_path: Path) -> None:
    watcher = GeminiCliFileWatcher(ctx)
    file_path = tmp_path / "sess.json"
    messages = [
        {"role": "user", "parts": [{"text": "first request with enough length please"}]},
        {"role": "model", "parts": [{"text": "first response matching the requested topic"}]},
    ]
    _write_json(file_path, messages)
    delta = await watcher.parse_delta(file_path, last_offset=0)
    assert delta is not None
    first_offset = delta.new_offset

    # Append a second exchange
    messages.extend(
        [
            {"role": "user", "parts": [{"text": "follow-up question with lots of words here"}]},
            {"role": "model", "parts": [{"text": "follow-up answer with enough length"}]},
        ]
    )
    _write_json(file_path, messages)

    delta2 = await watcher.parse_delta(file_path, last_offset=first_offset)
    assert delta2 is not None
    assert len(delta2.chunks) == 1  # one new exchange
    assert delta2.new_offset == 4


@pytest.mark.asyncio
async def test_parse_delta_returns_none_for_partial_json(
    ctx: WatcherContext, tmp_path: Path
) -> None:
    watcher = GeminiCliFileWatcher(ctx)
    file_path = tmp_path / "sess.json"
    file_path.write_text('{"messages": [{"role": "user", "pa', encoding="utf-8")

    delta = await watcher.parse_delta(file_path, last_offset=0)
    assert delta is None  # retry later


@pytest.mark.asyncio
async def test_process_file_updates_state(ctx: WatcherContext, tmp_path: Path) -> None:
    # Enable the watcher in the store so process_file will actually dispatch.
    ctx.state_store.upsert_status("gemini_cli", enabled=True)
    watcher = GeminiCliFileWatcher(ctx)

    file_path = tmp_path / "sess-2.json"
    _write_json(
        file_path,
        [
            {"role": "user", "parts": [{"text": "a " * 40}]},
            {"role": "model", "parts": [{"text": "b " * 40}]},
        ],
    )

    await watcher.process_file(file_path)
    offset = ctx.state_store.get_offset("gemini_cli", file_path.stem, str(file_path.resolve()))
    assert offset == 2


def test_watcher_declares_platform() -> None:
    assert GeminiCliFileWatcher.tool == "gemini_cli"
    assert GeminiCliFileWatcher.platform == Platform.GEMINI_CLI
