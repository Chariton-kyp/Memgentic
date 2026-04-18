"""Pluggable vector storage backends for Memgentic.

The :class:`VectorStore` in ``memgentic.storage.vectors`` is a façade that
selects a concrete backend based on ``settings.storage_backend``.

Today's backends:

- Qdrant (``LOCAL`` file mode and ``QDRANT`` server mode) — handled directly
  by the façade to preserve historical behaviour byte-for-byte.
- sqlite-vec (``SQLITE_VEC``) — opt-in, zero-config, multi-process safe.
  Implemented in :mod:`memgentic.storage.backends.sqlite_vec`.
"""

from memgentic.storage.backends.base import VectorBackend

__all__ = ["VectorBackend"]
