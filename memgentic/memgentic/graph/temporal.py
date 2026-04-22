"""Chronograph — bitemporal entity-relationship graph.

Stores subject-predicate-object triples with validity windows
(``valid_from`` / ``valid_to``), user validation status, and provenance
back to source memories. Lives in a standalone SQLite database at
``~/.memgentic/chronograph.sqlite`` so the bitemporal store can be
migrated to PostgreSQL independently of the main metadata database.

The engine is deliberately simple: a thin ``aiosqlite`` wrapper with
CRUD-style methods on two tables (``entities`` and ``triples``) plus a
``schema_version`` sentinel table for idempotent migrations. The
``knowledge.py`` co-occurrence graph is preserved for backwards
compatibility and continues to back existing hybrid search — the two
layers coexist with different purposes (implicit co-occurrence vs.
explicit, user-validated facts).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite
import structlog

logger = structlog.get_logger()


# Reserved migration identifier — kept aligned with the main metadata
# store's version counter (8 was the last one there). The chronograph
# database tracks its own version sentinel in ``schema_version``.
_CHRONOGRAPH_SCHEMA_VERSION = 9

TripleStatus = Literal["proposed", "accepted", "rejected", "edited"]
Direction = Literal["subject", "object", "both"]


_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS entities (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        type          TEXT,
        aliases       TEXT NOT NULL DEFAULT '[]',
        properties    TEXT NOT NULL DEFAULT '{}',
        workspace_id  TEXT,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS triples (
        id              TEXT PRIMARY KEY,
        subject         TEXT NOT NULL,
        predicate       TEXT NOT NULL,
        object          TEXT NOT NULL,
        valid_from      TEXT,
        valid_to        TEXT,
        confidence      REAL NOT NULL DEFAULT 0.7,
        source_memory_id TEXT,
        status          TEXT NOT NULL DEFAULT 'proposed',
        proposer        TEXT,
        accepted_by     TEXT,
        accepted_at     TEXT,
        workspace_id    TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        FOREIGN KEY (subject) REFERENCES entities(id),
        FOREIGN KEY (object) REFERENCES entities(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject, valid_from)",
    "CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object, valid_from)",
    "CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate)",
    "CREATE INDEX IF NOT EXISTS idx_triples_status ON triples(status)",
    "CREATE INDEX IF NOT EXISTS idx_entities_workspace ON entities(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_triples_workspace ON triples(workspace_id)",
]


@dataclass
class Entity:
    """A node in the Chronograph — a person, project, tool, concept."""

    id: str
    name: str
    type: str | None = None
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    workspace_id: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "aliases": list(self.aliases),
            "properties": dict(self.properties),
            "workspace_id": self.workspace_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Triple:
    """A fact — ``(subject, predicate, object)`` with a validity window."""

    id: str
    subject: str
    predicate: str
    object: str
    valid_from: date | None = None
    valid_to: date | None = None
    confidence: float = 0.7
    source_memory_id: str | None = None
    status: TripleStatus = "proposed"
    proposer: str | None = None
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    workspace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "confidence": self.confidence,
            "source_memory_id": self.source_memory_id,
            "status": self.status,
            "proposer": self.proposer,
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _normalize_entity_id(name: str) -> str:
    """Canonicalise an entity name to its lower-case, stripped id form."""
    return name.strip().lower()


def _normalize_predicate_token(raw: str) -> str:
    """Lowercase + snake_case a predicate string (shared with extractor)."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", raw.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "related_to"


def _parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _triple_hash(subject: str, predicate: str, obj: str, valid_from: date | None) -> str:
    """Stable hash used as triple primary key."""
    raw = f"{subject}|{predicate}|{obj}|{valid_from.isoformat() if valid_from else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class Chronograph:
    """Bitemporal entity-relationship graph.

    Triples carry validity windows (``valid_from`` / ``valid_to``) so the
    same subject-predicate pair can hold multiple object values at
    different times. User-facing APIs default to ``status="accepted"``
    so LLM-proposed triples don't leak into query results until a human
    has validated them.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ setup

    async def initialize(self) -> None:
        """Open the database and apply any pending migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()

        cursor = await self._db.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current = int(row[0]) if row and row[0] is not None else 0

        if current < _CHRONOGRAPH_SCHEMA_VERSION:
            for sql in _SCHEMA_STATEMENTS:
                await self._db.execute(sql)
            await self._db.execute(
                "INSERT OR REPLACE INTO schema_version (version, description, applied_at) "
                "VALUES (?, ?, ?)",
                (
                    _CHRONOGRAPH_SCHEMA_VERSION,
                    "chronograph entities and triples",
                    datetime.now(UTC).isoformat(),
                ),
            )
            await self._db.commit()
            logger.info(
                "chronograph.migrated",
                version=_CHRONOGRAPH_SCHEMA_VERSION,
                path=str(self._db_path),
            )
        else:
            logger.debug("chronograph.schema_up_to_date", version=current)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Chronograph.initialize() must be called before use")
        return self._db

    # ---------------------------------------------------------------- entities

    async def add_entity(
        self,
        name: str,
        type: str | None = None,
        aliases: list[str] | None = None,
        properties: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> Entity:
        """Create or update an entity. Entity id = lower-cased stripped name."""
        db = self._require_db()
        entity_id = _normalize_entity_id(name)
        if not entity_id:
            raise ValueError("entity name cannot be empty")

        async with self._lock:
            now = datetime.now(UTC).isoformat()
            existing = await self._get_entity_row(entity_id)
            if existing is None:
                await db.execute(
                    """
                    INSERT INTO entities (id, name, type, aliases, properties,
                                          workspace_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        name.strip() or entity_id,
                        type,
                        json.dumps(aliases or []),
                        json.dumps(properties or {}),
                        workspace_id,
                        now,
                    ),
                )
            else:
                merged_aliases = self._merge_aliases(existing["aliases"], aliases)
                merged_props = self._merge_properties(existing["properties"], properties)
                new_type = type if type else existing["type"]
                await db.execute(
                    """
                    UPDATE entities
                    SET name = ?, type = ?, aliases = ?, properties = ?, workspace_id = ?
                    WHERE id = ?
                    """,
                    (
                        name.strip() or existing["name"],
                        new_type,
                        json.dumps(merged_aliases),
                        json.dumps(merged_props),
                        workspace_id if workspace_id else existing["workspace_id"],
                        entity_id,
                    ),
                )
            await db.commit()

        row = await self._get_entity_row(entity_id)
        assert row is not None  # just wrote it
        return _row_to_entity(row)

    async def get_entity(self, name: str) -> Entity | None:
        entity_id = _normalize_entity_id(name)
        row = await self._get_entity_row(entity_id)
        return _row_to_entity(row) if row else None

    async def list_entities(
        self,
        limit: int = 100,
        offset: int = 0,
        workspace_id: str | None = None,
    ) -> list[Entity]:
        db = self._require_db()
        if workspace_id is not None:
            cursor = await db.execute(
                "SELECT * FROM entities WHERE workspace_id = ? "
                "ORDER BY name LIMIT ? OFFSET ?",
                (workspace_id, limit, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM entities ORDER BY name LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [_row_to_entity(r) for r in rows]

    async def _get_entity_row(self, entity_id: str) -> aiosqlite.Row | None:
        db = self._require_db()
        cursor = await db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        return await cursor.fetchone()

    @staticmethod
    def _merge_aliases(existing_json: str, new: list[str] | None) -> list[str]:
        try:
            current = json.loads(existing_json or "[]")
        except json.JSONDecodeError:
            current = []
        if not new:
            return current
        merged = list(current)
        for alias in new:
            if alias and alias not in merged:
                merged.append(alias)
        return merged

    @staticmethod
    def _merge_properties(existing_json: str, new: dict[str, Any] | None) -> dict[str, Any]:
        try:
            current = json.loads(existing_json or "{}")
        except json.JSONDecodeError:
            current = {}
        if not new:
            return current
        merged = dict(current)
        merged.update(new)
        return merged

    # ----------------------------------------------------------------- triples

    async def add_triple(
        self,
        subject: str,
        predicate: str,
        object: str,  # noqa: A002 — domain term is "object"
        valid_from: date | str | None = None,
        valid_to: date | str | None = None,
        confidence: float = 0.7,
        source_memory_id: str | None = None,
        proposer: str = "llm",
        status: TripleStatus = "proposed",
        workspace_id: str | None = None,
    ) -> Triple:
        """Store a triple, auto-creating entities for subject and object.

        The triple id is deterministic (hash of subject+predicate+object+valid_from)
        so repeated ingestion of the same fact is idempotent — the existing
        row is updated with a higher confidence when the new confidence is
        greater.
        """
        db = self._require_db()
        subject_id = _normalize_entity_id(subject)
        object_id = _normalize_entity_id(object)
        predicate_norm = _normalize_predicate_token(predicate)
        vf = _parse_date(valid_from)
        vt = _parse_date(valid_to)

        if not subject_id or not predicate_norm or not object_id:
            raise ValueError("subject, predicate, and object are required")

        await self.add_entity(subject, workspace_id=workspace_id)
        await self.add_entity(object, workspace_id=workspace_id)

        triple_id = _triple_hash(subject_id, predicate_norm, object_id, vf)
        now = datetime.now(UTC).isoformat()

        async with self._lock:
            cursor = await db.execute("SELECT * FROM triples WHERE id = ?", (triple_id,))
            existing = await cursor.fetchone()
            if existing is None:
                await db.execute(
                    """
                    INSERT INTO triples (
                        id, subject, predicate, object, valid_from, valid_to,
                        confidence, source_memory_id, status, proposer,
                        accepted_by, accepted_at, workspace_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        triple_id,
                        subject_id,
                        predicate_norm,
                        object_id,
                        vf.isoformat() if vf else None,
                        vt.isoformat() if vt else None,
                        float(confidence),
                        source_memory_id,
                        status,
                        proposer,
                        None,
                        None,
                        workspace_id,
                        now,
                        now,
                    ),
                )
            else:
                # Idempotent: keep the higher-confidence version; if the new
                # one is stronger, replace confidence/source; never regress
                # an "accepted" status back to "proposed".
                merged_confidence = max(float(existing["confidence"]), float(confidence))
                merged_source = source_memory_id or existing["source_memory_id"]
                merged_status = existing["status"]
                if merged_status == "proposed" and status == "accepted":
                    merged_status = "accepted"
                await db.execute(
                    """
                    UPDATE triples
                    SET confidence = ?, source_memory_id = ?, status = ?,
                        valid_to = COALESCE(?, valid_to), updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        merged_confidence,
                        merged_source,
                        merged_status,
                        vt.isoformat() if vt else None,
                        now,
                        triple_id,
                    ),
                )
            await db.commit()

        row = await self._get_triple_row(triple_id)
        assert row is not None
        return _row_to_triple(row)

    async def invalidate(
        self,
        subject: str,
        predicate: str,
        object: str,  # noqa: A002
        ended: date | str | None = None,
    ) -> None:
        """Close the validity window for a currently-open triple.

        Matches the open-ended triple (``valid_to IS NULL``) for the given
        subject/predicate/object and sets ``valid_to`` to ``ended`` (today
        when omitted).
        """
        db = self._require_db()
        subject_id = _normalize_entity_id(subject)
        object_id = _normalize_entity_id(object)
        predicate_norm = _normalize_predicate_token(predicate)
        end_date = _parse_date(ended) or datetime.now(UTC).date()
        now = datetime.now(UTC).isoformat()

        async with self._lock:
            await db.execute(
                """
                UPDATE triples
                SET valid_to = ?, updated_at = ?
                WHERE subject = ? AND predicate = ? AND object = ?
                  AND valid_to IS NULL
                """,
                (end_date.isoformat(), now, subject_id, predicate_norm, object_id),
            )
            await db.commit()

    async def query_entity(
        self,
        name: str,
        as_of: date | str | None = None,
        direction: Direction = "both",
        status: TripleStatus | Literal["any"] = "accepted",
    ) -> list[Triple]:
        """Return triples touching ``name`` valid at ``as_of``.

        ``direction`` selects whether to match the entity as subject,
        object, or either side. ``status="any"`` disables filtering so
        the validation queue UI can see proposed rows.
        """
        db = self._require_db()
        entity_id = _normalize_entity_id(name)
        parsed = _parse_date(as_of) if as_of else None
        at: date = parsed if parsed is not None else datetime.now(UTC).date()

        where = []
        params: list[Any] = []
        if direction == "subject":
            where.append("subject = ?")
            params.append(entity_id)
        elif direction == "object":
            where.append("object = ?")
            params.append(entity_id)
        else:
            where.append("(subject = ? OR object = ?)")
            params.extend([entity_id, entity_id])

        if status != "any":
            where.append("status = ?")
            params.append(status)

        # Bitemporal filter: (valid_from IS NULL OR valid_from <= at)
        # AND (valid_to IS NULL OR valid_to >= at)
        where.append("(valid_from IS NULL OR valid_from <= ?)")
        params.append(at.isoformat())
        where.append("(valid_to IS NULL OR valid_to >= ?)")
        params.append(at.isoformat())

        sql = f"SELECT * FROM triples WHERE {' AND '.join(where)} ORDER BY valid_from DESC"
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_triple(r) for r in rows]

    async def timeline(
        self,
        entity: str | None = None,
        status: TripleStatus | Literal["any"] = "accepted",
        limit: int = 500,
    ) -> list[Triple]:
        """Return triples in chronological order (``valid_from`` ascending)."""
        db = self._require_db()
        where = []
        params: list[Any] = []
        if entity:
            entity_id = _normalize_entity_id(entity)
            where.append("(subject = ? OR object = ?)")
            params.extend([entity_id, entity_id])
        if status != "any":
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM triples"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(valid_from, created_at) ASC, created_at ASC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_triple(r) for r in rows]

    async def list_proposed(
        self, limit: int = 50, offset: int = 0, workspace_id: str | None = None
    ) -> list[Triple]:
        db = self._require_db()
        params: list[Any] = ["proposed"]
        sql = "SELECT * FROM triples WHERE status = ?"
        if workspace_id is not None:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_triple(r) for r in rows]

    async def get_triple(self, triple_id: str) -> Triple | None:
        row = await self._get_triple_row(triple_id)
        return _row_to_triple(row) if row else None

    async def _get_triple_row(self, triple_id: str) -> aiosqlite.Row | None:
        db = self._require_db()
        cursor = await db.execute("SELECT * FROM triples WHERE id = ?", (triple_id,))
        return await cursor.fetchone()

    async def accept(self, triple_id: str, user_id: str | None = None) -> Triple:
        db = self._require_db()
        now = datetime.now(UTC).isoformat()
        async with self._lock:
            await db.execute(
                "UPDATE triples SET status = 'accepted', confidence = MAX(confidence, 1.0), "
                "accepted_by = ?, accepted_at = ?, updated_at = ? WHERE id = ?",
                (user_id, now, now, triple_id),
            )
            await db.commit()
        triple = await self.get_triple(triple_id)
        if triple is None:
            raise LookupError(f"triple {triple_id} not found")
        return triple

    async def reject(self, triple_id: str) -> Triple:
        db = self._require_db()
        now = datetime.now(UTC).isoformat()
        async with self._lock:
            await db.execute(
                "UPDATE triples SET status = 'rejected', updated_at = ? WHERE id = ?",
                (now, triple_id),
            )
            await db.commit()
        triple = await self.get_triple(triple_id)
        if triple is None:
            raise LookupError(f"triple {triple_id} not found")
        return triple

    async def edit(self, triple_id: str, **fields: Any) -> Triple:
        """Patch a triple's mutable fields.

        Changing ``subject``, ``predicate``, ``object``, or ``valid_from``
        changes the triple's identity; a new row is inserted (with
        ``status='edited'`` reflecting the provenance) and the old row is
        deleted.
        """
        db = self._require_db()
        existing = await self.get_triple(triple_id)
        if existing is None:
            raise LookupError(f"triple {triple_id} not found")

        identity_changed = any(
            k in fields and fields[k] is not None for k in ("subject", "predicate", "object")
        ) or (
            "valid_from" in fields
            and _parse_date(fields["valid_from"]) != existing.valid_from
        )

        if identity_changed:
            new_subject = fields.get("subject") or existing.subject
            new_predicate = fields.get("predicate") or existing.predicate
            new_object = fields.get("object") or existing.object
            new_valid_from = (
                _parse_date(fields["valid_from"])
                if "valid_from" in fields
                else existing.valid_from
            )
            new_valid_to = (
                _parse_date(fields["valid_to"])
                if "valid_to" in fields
                else existing.valid_to
            )
            new_confidence = float(fields.get("confidence", existing.confidence))
            # Delete old, insert new
            async with self._lock:
                await db.execute("DELETE FROM triples WHERE id = ?", (triple_id,))
                await db.commit()
            triple = await self.add_triple(
                subject=new_subject,
                predicate=new_predicate,
                object=new_object,
                valid_from=new_valid_from,
                valid_to=new_valid_to,
                confidence=new_confidence,
                source_memory_id=existing.source_memory_id,
                proposer="user",
                status="edited",
                workspace_id=existing.workspace_id,
            )
            return triple

        # Non-identity fields only
        updates: list[str] = []
        params: list[Any] = []
        for column in ("valid_to", "confidence", "status", "source_memory_id"):
            if column in fields and fields[column] is not None:
                value = fields[column]
                if column == "valid_to":
                    value = _parse_date(value)
                    value = value.isoformat() if value else None
                updates.append(f"{column} = ?")
                params.append(value)
        if not updates:
            return existing
        now = datetime.now(UTC).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.append(triple_id)
        async with self._lock:
            await db.execute(
                f"UPDATE triples SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            await db.commit()
        updated = await self.get_triple(triple_id)
        assert updated is not None
        return updated

    async def search_triples(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,  # noqa: A002
        status: TripleStatus | Literal["any"] = "any",
        as_of: date | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Triple]:
        """Low-level triple filter used by the REST + CLI layers."""
        db = self._require_db()
        where: list[str] = []
        params: list[Any] = []
        if subject:
            where.append("subject = ?")
            params.append(_normalize_entity_id(subject))
        if predicate:
            where.append("predicate = ?")
            params.append(_normalize_predicate_token(predicate))
        if object:
            where.append("object = ?")
            params.append(_normalize_entity_id(object))
        if status != "any":
            where.append("status = ?")
            params.append(status)
        if as_of is not None:
            at = _parse_date(as_of)
            if at is not None:
                where.append("(valid_from IS NULL OR valid_from <= ?)")
                params.append(at.isoformat())
                where.append("(valid_to IS NULL OR valid_to >= ?)")
                params.append(at.isoformat())
        sql = "SELECT * FROM triples"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_triple(r) for r in rows]

    # ---------------------------------------------------------------- stats

    async def stats(self) -> dict[str, Any]:
        db = self._require_db()
        cursor = await db.execute("SELECT COUNT(*) FROM entities")
        row1 = await cursor.fetchone()
        entity_count = int(row1[0]) if row1 else 0
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM triples GROUP BY status"
        )
        counts: dict[str, int] = {}
        for row in await cursor.fetchall():
            counts[row[0]] = int(row[1])
        cursor = await db.execute("SELECT COUNT(DISTINCT predicate) FROM triples")
        row2 = await cursor.fetchone()
        predicate_count = int(row2[0]) if row2 else 0
        return {
            "entities": entity_count,
            "triples": sum(counts.values()),
            "triples_by_status": counts,
            "predicates": predicate_count,
            "accepted": counts.get("accepted", 0),
            "proposed": counts.get("proposed", 0),
            "rejected": counts.get("rejected", 0),
            "edited": counts.get("edited", 0),
        }


# ---------------------------------------------------------------------- helpers


def _row_to_entity(row: aiosqlite.Row) -> Entity:
    return Entity(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        aliases=json.loads(row["aliases"] or "[]"),
        properties=json.loads(row["properties"] or "{}"),
        workspace_id=row["workspace_id"],
        created_at=_parse_datetime(row["created_at"]),
    )


def _row_to_triple(row: aiosqlite.Row) -> Triple:
    return Triple(
        id=row["id"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        valid_from=_parse_date(row["valid_from"]),
        valid_to=_parse_date(row["valid_to"]),
        confidence=float(row["confidence"]),
        source_memory_id=row["source_memory_id"],
        status=row["status"],
        proposer=row["proposer"],
        accepted_by=row["accepted_by"],
        accepted_at=_parse_datetime(row["accepted_at"]),
        workspace_id=row["workspace_id"],
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------- singletons

_instances: dict[str, Chronograph] = {}


async def get_chronograph(db_path: Path | None = None) -> Chronograph:
    """Return a cached initialised Chronograph for ``db_path``.

    Default path is ``{settings.data_dir}/chronograph.sqlite`` so the
    bitemporal store sits alongside the existing metadata database.
    """
    from memgentic.config import settings

    resolved = Path(db_path) if db_path is not None else settings.data_dir / "chronograph.sqlite"
    key = str(resolved.resolve())
    instance = _instances.get(key)
    if instance is None:
        instance = Chronograph(resolved)
        await instance.initialize()
        _instances[key] = instance
    return instance


def reset_chronograph_cache() -> None:
    """Drop the cached Chronograph instances — used by tests."""
    _instances.clear()
