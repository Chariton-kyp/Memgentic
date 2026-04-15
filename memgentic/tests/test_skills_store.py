"""Tests for skills metadata store operations (CRUD, files, distributions)."""

from __future__ import annotations

from memgentic.models import Skill, SkillFile
from memgentic.storage.metadata import MetadataStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(name: str = "deploy-runbook", **kwargs) -> Skill:
    return Skill(
        name=name,
        description=kwargs.get("description", "Deploy the app"),
        content=kwargs.get("content", "# Deploy Runbook\n\nRun `make deploy`."),
        tags=kwargs.get("tags", ["ops", "deploy"]),
        distribute_to=kwargs.get("distribute_to", ["claude", "codex"]),
    )


def _make_skill_file(skill_id: str, path: str = "scripts/deploy.sh") -> SkillFile:
    return SkillFile(
        skill_id=skill_id,
        path=path,
        content="#!/usr/bin/env bash\necho deploy\n",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSkillCRUD:
    async def test_create_and_get_skill(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        got = await metadata_store.get_skill(skill.id)
        assert got is not None
        assert got.id == skill.id
        assert got.name == "deploy-runbook"
        assert got.description == "Deploy the app"
        assert got.tags == ["ops", "deploy"]
        assert got.distribute_to == ["claude", "codex"]
        assert got.files == []

    async def test_get_skill_by_name(self, metadata_store: MetadataStore):
        skill = _make_skill(name="code-review-checklist")
        await metadata_store.create_skill(skill)

        got = await metadata_store.get_skill_by_name("code-review-checklist")
        assert got is not None
        assert got.id == skill.id

        # Unknown name returns None
        missing = await metadata_store.get_skill_by_name("nonexistent")
        assert missing is None

    async def test_list_skills(self, metadata_store: MetadataStore):
        for name in ["alpha", "beta", "gamma"]:
            await metadata_store.create_skill(_make_skill(name=name))

        skills = await metadata_store.get_skills()
        assert len(skills) == 3
        assert {s.name for s in skills} == {"alpha", "beta", "gamma"}

    async def test_update_skill(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        await metadata_store.update_skill(
            skill.id,
            description="Updated description",
            content="# New content",
            tags=["updated"],
            distribute_to=["claude", "cursor", "opencode"],
        )

        got = await metadata_store.get_skill(skill.id)
        assert got is not None
        assert got.description == "Updated description"
        assert got.content == "# New content"
        assert got.tags == ["updated"]
        assert got.distribute_to == ["claude", "cursor", "opencode"]

    async def test_update_skill_ignores_unknown_fields(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        # Unknown fields are silently dropped
        await metadata_store.update_skill(skill.id, not_a_field="ignored")

        got = await metadata_store.get_skill(skill.id)
        assert got is not None
        assert got.name == skill.name


class TestSkillFiles:
    async def test_add_file_to_skill(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        sf = _make_skill_file(skill.id, path="scripts/deploy.sh")
        await metadata_store.create_skill_file(sf)

        got = await metadata_store.get_skill(skill.id)
        assert got is not None
        assert len(got.files) == 1
        assert got.files[0].path == "scripts/deploy.sh"
        assert "deploy" in got.files[0].content

    async def test_multiple_files_ordered_by_path(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        for path in ["z.md", "a.md", "m.md"]:
            await metadata_store.create_skill_file(_make_skill_file(skill.id, path=path))

        files = await metadata_store.get_skill_files(skill.id)
        assert [f.path for f in files] == ["a.md", "m.md", "z.md"]

    async def test_update_skill_file(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        sf = _make_skill_file(skill.id)
        await metadata_store.create_skill_file(sf)

        await metadata_store.update_skill_file(
            sf.id, path="scripts/deploy-v2.sh", content="new content"
        )

        files = await metadata_store.get_skill_files(skill.id)
        assert len(files) == 1
        assert files[0].path == "scripts/deploy-v2.sh"
        assert files[0].content == "new content"

    async def test_delete_skill_file(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        sf = _make_skill_file(skill.id)
        await metadata_store.create_skill_file(sf)

        await metadata_store.delete_skill_file(sf.id)

        files = await metadata_store.get_skill_files(skill.id)
        assert files == []


class TestSkillCascade:
    async def test_delete_skill_cascades_to_files(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        for path in ["a.md", "b.md"]:
            await metadata_store.create_skill_file(_make_skill_file(skill.id, path=path))

        await metadata_store.delete_skill(skill.id)

        # Skill gone
        assert await metadata_store.get_skill(skill.id) is None
        # Files gone via FK cascade
        assert await metadata_store.get_skill_files(skill.id) == []


class TestSkillDistributionsLog:
    async def test_log_and_list_distributions(self, metadata_store: MetadataStore):
        skill = _make_skill()
        await metadata_store.create_skill(skill)

        await metadata_store.log_skill_distribution(
            skill.id, "claude", "/home/user/.claude/skills/deploy-runbook"
        )
        await metadata_store.log_skill_distribution(
            skill.id, "codex", "/home/user/.codex/skills/deploy-runbook"
        )

        distributions = await metadata_store.get_skill_distributions(skill.id)
        assert len(distributions) == 2
        tools = {d["tool"] for d in distributions}
        assert tools == {"claude", "codex"}
