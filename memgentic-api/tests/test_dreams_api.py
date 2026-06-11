"""REST API tests for /api/v1/dreams — list, detail, create, apply, reject."""

from __future__ import annotations

from httpx import AsyncClient
from memgentic.models import (
    CaptureMethod,
    ContentType,
    DreamPatch,
    DreamPatchAction,
    DreamRun,
    DreamStatus,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)


def _make_memory(mid: str, content: str = "test") -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
    )


async def _seed_dream(client: AsyncClient, *, project: str = "test") -> tuple[str, list[str]]:
    """Insert a DreamRun + 2 patches via the underlying store. Returns
    (dream_id, [patch_ids]).
    """
    store = client._transport.app.state.metadata_store  # type: ignore[union-attr]
    run = DreamRun(project=project, status=DreamStatus.COMPLETED, model="claude-sonnet-4-6")
    await store.create_dream_run(run)
    patches = [
        DreamPatch(
            dream_id=run.id,
            action=DreamPatchAction.MERGE,
            target_memory_ids=["a", "b"],
            evidence="dup",
        ),
        DreamPatch(
            dream_id=run.id,
            action=DreamPatchAction.INSERT_INSIGHT,
            new_content="recurring pattern",
            evidence="seen 3x",
        ),
    ]
    await store.create_dream_patches(patches)
    return run.id, [p.id for p in patches]


class TestListDreams:
    async def test_empty_list(self, client: AsyncClient):
        resp = await client.get("/api/v1/dreams")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"dreams": [], "total": 0}

    async def test_list_returns_seeded_run_with_patch_count(self, client: AsyncClient):
        dream_id, _ = await _seed_dream(client)
        resp = await client.get("/api/v1/dreams")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["dreams"][0]["id"] == dream_id
        assert body["dreams"][0]["status"] == "completed"
        assert body["dreams"][0]["patches_count"] == 2

    async def test_filter_by_project(self, client: AsyncClient):
        dream_a, _ = await _seed_dream(client, project="alpha")
        dream_b, _ = await _seed_dream(client, project="beta")

        resp = await client.get("/api/v1/dreams", params={"project": "alpha"})
        assert resp.status_code == 200
        ids = [d["id"] for d in resp.json()["dreams"]]
        assert dream_a in ids
        assert dream_b not in ids

    async def test_filter_by_status(self, client: AsyncClient):
        await _seed_dream(client)
        resp = await client.get("/api/v1/dreams", params={"status": "failed"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetDream:
    async def test_returns_run_and_patches(self, client: AsyncClient):
        dream_id, patch_ids = await _seed_dream(client)

        resp = await client.get(f"/api/v1/dreams/{dream_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run"]["id"] == dream_id
        assert body["run"]["model"] == "claude-sonnet-4-6"
        assert len(body["patches"]) == 2
        actions = sorted(p["action"] for p in body["patches"])
        assert actions == ["insert_insight", "merge"]
        # Every patch is initially proposed
        assert all(p["status"] == "proposed" for p in body["patches"])

    async def test_404_for_unknown_dream(self, client: AsyncClient):
        resp = await client.get("/api/v1/dreams/does-not-exist")
        assert resp.status_code == 404


class TestApplyDream:
    async def test_apply_non_destructive_only_skips_merge(self, client: AsyncClient):
        # Memories must exist for the MERGE patch's targets
        store = client._transport.app.state.metadata_store  # type: ignore[union-attr]
        await store.save_memory(_make_memory("a"))
        await store.save_memory(_make_memory("b"))

        dream_id, _ = await _seed_dream(client)

        resp = await client.post(
            f"/api/v1/dreams/{dream_id}/apply",
            json={"only_non_destructive": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dream_id"] == dream_id
        # INSERT_INSIGHT applied, MERGE skipped as destructive
        assert body["applied"] == 1
        assert body["skipped_destructive"] == 1
        assert len(body["inserted_memories"]) == 1
        assert body["superseded_memories"] == []

        # The MERGE remains proposed for explicit follow-up apply
        detail = await client.get(f"/api/v1/dreams/{dream_id}")
        proposed_actions = {
            p["action"] for p in detail.json()["patches"] if p["status"] == "proposed"
        }
        assert proposed_actions == {"merge"}

    async def test_apply_full_runs_destructive(self, client: AsyncClient):
        store = client._transport.app.state.metadata_store  # type: ignore[union-attr]
        await store.save_memory(_make_memory("a"))
        await store.save_memory(_make_memory("b"))

        dream_id, _ = await _seed_dream(client)

        resp = await client.post(
            f"/api/v1/dreams/{dream_id}/apply",
            json={"only_non_destructive": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] == 2
        assert body["skipped_destructive"] == 0
        assert len(body["superseded_memories"]) == 1  # one of {a, b} kept canonical

        # The merged memory is superseded
        b_after = await store.get_memory("b")
        assert b_after is not None
        assert b_after.status == MemoryStatus.SUPERSEDED

    async def test_apply_404_for_unknown_dream(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/dreams/does-not-exist/apply",
            json={"only_non_destructive": True},
        )
        assert resp.status_code == 404


class TestRejectDream:
    async def test_reject_marks_proposed_as_rejected(self, client: AsyncClient):
        dream_id, _ = await _seed_dream(client)

        resp = await client.post(f"/api/v1/dreams/{dream_id}/reject")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dream_id"] == dream_id
        assert body["rejected"] == 2

        # Subsequent reject is a no-op (idempotent)
        resp2 = await client.post(f"/api/v1/dreams/{dream_id}/reject")
        assert resp2.status_code == 200
        assert resp2.json()["rejected"] == 0

    async def test_reject_404_for_unknown_dream(self, client: AsyncClient):
        resp = await client.post("/api/v1/dreams/does-not-exist/reject")
        assert resp.status_code == 404


class TestCreateDream:
    """The POST /dreams endpoint runs the pipeline. We mock-out the LLM to
    avoid network and to keep tests deterministic."""

    async def test_create_returns_completed_run(self, client: AsyncClient, monkeypatch):
        from memgentic.processing import dream as dream_module
        from memgentic.processing.dream import DreamRun, DreamStatus

        async def _fake_run_dream(*, project, metadata_store, embedder, settings, **kwargs):
            run = DreamRun(project=project, status=DreamStatus.COMPLETED, model="mocked")
            await metadata_store.create_dream_run(run)
            return run

        monkeypatch.setattr(dream_module, "run_dream", _fake_run_dream)

        resp = await client.post(
            "/api/v1/dreams",
            json={"project": "test", "instructions": "", "limit_sessions": 5},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "completed"
        assert body["project"] == "test"
        assert body["patches_count"] == 0

    async def test_create_rejects_oversized_instructions(self, client: AsyncClient):
        # Schema-level guard on the request body — caught before reaching the
        # pipeline. Length cap is 4096.
        resp = await client.post(
            "/api/v1/dreams",
            json={"project": "test", "instructions": "x" * 5000},
        )
        assert resp.status_code == 422  # Pydantic validation error
