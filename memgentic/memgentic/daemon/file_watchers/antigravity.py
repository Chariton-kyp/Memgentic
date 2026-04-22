"""Antigravity file watcher.

Antigravity writes conversations to
``~/.gemini/antigravity/conversations/*.pb`` — Protocol Buffer blobs. We
delegate parsing to :class:`memgentic.adapters.antigravity.AntigravityAdapter`
which already uses the Rust-native protobuf extractor with a pure-Python
fallback.

Protobuf schema churn is handled defensively: if parsing fails we warn,
record the error on :class:`WatcherStatus`, and skip.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from memgentic.adapters.antigravity import ANTIGRAVITY_BASE, AntigravityAdapter
from memgentic.adapters.base import BaseAdapter
from memgentic.daemon.file_watchers.base import BaseFileWatcher, DeltaPayload
from memgentic.models import Platform

logger = structlog.get_logger()


class AntigravityFileWatcher(BaseFileWatcher):
    tool = "antigravity"
    platform = Platform.ANTIGRAVITY

    def watch_dirs(self) -> list[Path]:
        return [ANTIGRAVITY_BASE]

    def patterns(self) -> list[str]:
        return ["*.pb"]

    def adapter(self) -> BaseAdapter:
        return AntigravityAdapter()

    async def parse_delta(
        self,
        file_path: Path,
        last_offset: int,
    ) -> DeltaPayload | None:
        # Protobuf blobs are opaque — a partial write is indistinguishable
        # from a valid one, so we only parse once the file's size has not
        # grown since the last event. We approximate "stable" by requiring
        # the file to contain more bytes than ``last_offset``.
        try:
            current_size = file_path.stat().st_size
        except OSError:
            return None
        if current_size <= last_offset:
            return DeltaPayload(chunks=[], new_offset=current_size, session_id=file_path.stem)

        try:
            adapter = self._adapter
            chunks = await adapter.parse_file(file_path)
        except Exception as exc:
            logger.warning(
                "antigravity_watcher.parse_failed",
                file=str(file_path),
                error=str(exc),
            )
            self._ctx.state_store.record_error(self.tool, f"protobuf decode: {exc}")
            # Advance offset anyway so we don't loop on an undecodable file.
            return DeltaPayload(chunks=[], new_offset=current_size, session_id=file_path.stem)

        return DeltaPayload(
            chunks=chunks,
            new_offset=current_size,
            session_id=file_path.stem,
            session_title=None,
        )


__all__ = ["AntigravityFileWatcher"]
