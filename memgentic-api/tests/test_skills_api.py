"""Tests for skill CRUD, files, distribution, extraction, and import endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Fixture: isolate skill distribution to a temp directory so tests never
# touch the real ~/.claude/skills/ or ~/.codex/skills/ paths on the host.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_skill_paths(tmp_path: Path, monkeypatch):
    """Redirect TOOL_SKILL_PATHS to a tmp directory for every skill test."""
    from memgentic.skills import distributor

    sandbox = tmp_path / "tool_skills"
    monkeypatch.setattr(
        distributor,
        "TOOL_SKILL_PATHS",
        {
            "claude": sandbox / "claude" / "skills",
            "codex": sandbox / "codex" / "skills",
            "cursor": sandbox / "cursor" / "rules",
            "opencode": sandbox / "opencode" / "skills",
        },
    )
    # The skills route also imports TOOL_SKILL_PATHS at module level; patch both.
    from memgentic_api.routes import skills as skills_route

    monkeypatch.setattr(
        skills_route,
        "TOOL_SKILL_PATHS",
        distributor.TOOL_SKILL_PATHS,
    )
    yield


def _skill_payload(name: str = "test-skill", **overrides) -> dict:
    """Build a default CreateSkillRequest payload."""
    payload = {
        "name": name,
        "description": "A skill for testing",
        "content": "# Skill body\n\nUse this skill to test things.",
        "tags": ["testing"],
        "distribute_to": ["claude"],
        "auto_distribute": False,
    }
    payload.update(overrides)
    return payload


# --- CRUD ---


async def test_create_skill(client: AsyncClient):
    """POST /api/v1/skills creates and returns a skill."""
    resp = await client.post("/api/v1/skills", json=_skill_payload("my-skill"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-skill"
    assert data["description"] == "A skill for testing"
    assert data["tags"] == ["testing"]
    assert data["auto_distribute"] is False
    assert data["files"] == []


async def test_create_skill_with_files(client: AsyncClient):
    """POST /api/v1/skills with a files array persists the files."""
    payload = _skill_payload(
        "skill-with-files",
        files=[
            {"path": "scripts/run.sh", "content": "#!/bin/bash\necho hi"},
            {"path": "README.md", "content": "# Readme"},
        ],
    )
    resp = await client.post("/api/v1/skills", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["files"]) == 2
    paths = {f["path"] for f in data["files"]}
    assert paths == {"scripts/run.sh", "README.md"}


async def test_create_skill_duplicate_name(client: AsyncClient):
    """POST /api/v1/skills with a duplicate name returns 409."""
    await client.post("/api/v1/skills", json=_skill_payload("dup-skill"))
    resp = await client.post("/api/v1/skills", json=_skill_payload("dup-skill"))
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


async def test_list_skills(client: AsyncClient):
    """GET /api/v1/skills returns all created skills."""
    for name in ("skill-a", "skill-b", "skill-c"):
        await client.post("/api/v1/skills", json=_skill_payload(name))

    resp = await client.get("/api/v1/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    names = {s["name"] for s in data["skills"]}
    assert names == {"skill-a", "skill-b", "skill-c"}


async def test_get_skill(client: AsyncClient):
    """GET /api/v1/skills/{id} returns the skill with files attached."""
    create = await client.post(
        "/api/v1/skills",
        json=_skill_payload(
            "fetchable-skill",
            files=[{"path": "notes.md", "content": "# Notes"}],
        ),
    )
    skill_id = create.json()["id"]

    resp = await client.get(f"/api/v1/skills/{skill_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == skill_id
    assert data["name"] == "fetchable-skill"
    assert len(data["files"]) == 1


async def test_get_skill_not_found(client: AsyncClient):
    """GET /api/v1/skills/{id} returns 404 for unknown ID."""
    resp = await client.get("/api/v1/skills/does-not-exist")
    assert resp.status_code == 404


async def test_update_skill(client: AsyncClient):
    """PUT /api/v1/skills/{id} updates name and content."""
    create = await client.post("/api/v1/skills", json=_skill_payload("to-update"))
    skill_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/skills/{skill_id}",
        json={"name": "updated-name", "content": "# New body"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "updated-name"
    assert data["content"] == "# New body"


async def test_delete_skill(client: AsyncClient):
    """DELETE /api/v1/skills/{id} returns 204 and subsequent GET returns 404."""
    create = await client.post("/api/v1/skills", json=_skill_payload("to-delete"))
    skill_id = create.json()["id"]

    del_resp = await client.delete(f"/api/v1/skills/{skill_id}")
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 404


# --- Skill files ---


async def test_add_skill_file(client: AsyncClient):
    """POST /api/v1/skills/{id}/files adds a new file."""
    create = await client.post("/api/v1/skills", json=_skill_payload("file-host"))
    skill_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/skills/{skill_id}/files",
        json={"path": "helpers/util.py", "content": "print('hi')"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["path"] == "helpers/util.py"
    assert data["content"] == "print('hi')"


async def test_delete_skill_file(client: AsyncClient):
    """DELETE /api/v1/skills/{id}/files/{fid} removes a file."""
    create = await client.post("/api/v1/skills", json=_skill_payload("file-rm"))
    skill_id = create.json()["id"]

    file_resp = await client.post(
        f"/api/v1/skills/{skill_id}/files",
        json={"path": "doomed.txt", "content": "delete me"},
    )
    file_id = file_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/skills/{skill_id}/files/{file_id}")
    assert del_resp.status_code == 204

    # Verify the file is gone from the skill
    get_resp = await client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200
    assert all(f["id"] != file_id for f in get_resp.json()["files"])


# --- Distribution ---


async def test_distribute_skill(client: AsyncClient, tmp_path: Path):
    """POST /api/v1/skills/{id}/distribute writes SKILL.md to target tool paths."""
    create = await client.post(
        "/api/v1/skills",
        json=_skill_payload(
            "distributable",
            files=[{"path": "assets/notes.md", "content": "# Inner file"}],
        ),
    )
    skill_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/skills/{skill_id}/distribute",
        json={"tools": ["claude"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["distributed_to"] == ["claude"]
    assert len(data["paths"]) == 1

    # Confirm the SKILL.md file was actually written inside the isolated tmp path
    written_dir = Path(data["paths"][0])
    assert written_dir.exists()
    assert (written_dir / "SKILL.md").exists()
    assert (written_dir / "assets" / "notes.md").exists()


# --- Extract ---


async def test_skill_extract_no_memories(client: AsyncClient):
    """POST /api/v1/skills/extract with invalid memory IDs returns 404."""
    resp = await client.post(
        "/api/v1/skills/extract",
        json={"memory_ids": ["nonexistent-1", "nonexistent-2"]},
    )
    assert resp.status_code == 404


async def test_skill_extract_from_memories(client: AsyncClient):
    """POST /api/v1/skills/extract builds a skill from real memories."""
    # Seed a memory first
    mem_resp = await client.post(
        "/api/v1/memories",
        json={
            "content": "Always run tests before committing Python code",
            "topics": ["python", "testing", "workflow"],
            "source": "claude_code",
        },
    )
    memory_id = mem_resp.json()["id"]

    resp = await client.post(
        "/api/v1/skills/extract",
        json={"memory_ids": [memory_id]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["auto_extracted"] is True
    assert memory_id in data["source_memory_ids"]


# --- Import from GitHub ---


async def test_skill_import_invalid_url(client: AsyncClient):
    """POST /api/v1/skills/import with a non-GitHub URL returns 400."""
    from memgentic.skills.importer import SkillImportError

    async def _fake_import(url: str):
        raise SkillImportError("Only GitHub URLs are supported")

    with patch(
        "memgentic.skills.importer.SkillImporter.import_from_github",
        new=AsyncMock(side_effect=_fake_import),
    ):
        resp = await client.post(
            "/api/v1/skills/import",
            json={"github_url": "https://example.com/not-github"},
        )
    assert resp.status_code == 400
    assert "GitHub" in resp.json()["detail"]
