"""Tests for the SkillDistributor — writes SKILL.md to tool-native paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from memgentic.models import Skill, SkillFile
from memgentic.skills import distributor as distributor_module
from memgentic.skills.distributor import TOOL_SKILL_PATHS, SkillDistributor
from memgentic.storage.metadata import MetadataStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(
    name: str = "deploy-runbook",
    *,
    description: str = "Deploy the app",
    content: str = "# Deploy Runbook\n\nRun `make deploy`.",
    tags: list[str] | None = None,
    version: str = "1.0.0",
) -> Skill:
    return Skill(
        name=name,
        description=description,
        content=content,
        tags=tags or [],
        version=version,
    )


def _make_skill_file(skill_id: str, path: str, content: str = "hello") -> SkillFile:
    return SkillFile(skill_id=skill_id, path=path, content=content)


@pytest.fixture()
def tmp_tool_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect TOOL_SKILL_PATHS entries to subdirectories under tmp_path."""
    replacements = {
        "claude": tmp_path / ".claude" / "skills",
        "codex": tmp_path / ".codex" / "skills",
        "opencode": tmp_path / ".config" / "opencode" / "skills",
        "cursor": tmp_path / ".cursor" / "rules",
    }
    for tool, new_path in replacements.items():
        monkeypatch.setitem(distributor_module.TOOL_SKILL_PATHS, tool, new_path)
    return replacements


# ---------------------------------------------------------------------------
# Tests: render_skill_md
# ---------------------------------------------------------------------------


class TestRenderSkillMd:
    def test_basic_frontmatter(self):
        skill = _make_skill(name="hello-world", description="Greets the world")
        md = SkillDistributor._render_skill_md(skill)

        assert md.startswith("---\n")
        assert "name: hello-world" in md
        assert "description: Greets the world" in md
        assert "# Deploy Runbook" in md  # body included

    def test_tags_are_rendered(self):
        skill = _make_skill(tags=["ops", "deploy"])
        md = SkillDistributor._render_skill_md(skill)
        assert "tags: [ops, deploy]" in md

    def test_version_only_rendered_when_non_default(self):
        default_skill = _make_skill(version="1.0.0")
        custom_skill = _make_skill(version="2.3.1")

        assert "version:" not in SkillDistributor._render_skill_md(default_skill)
        assert "version: 2.3.1" in SkillDistributor._render_skill_md(custom_skill)

    def test_body_follows_frontmatter(self):
        skill = _make_skill(content="# Custom body\n\nBody text here.")
        md = SkillDistributor._render_skill_md(skill)
        # Frontmatter terminates before body
        closing = md.index("---", 3)
        body = md[closing + len("---") :].strip()
        assert body.startswith("# Custom body")


# ---------------------------------------------------------------------------
# Tests: TOOL_SKILL_PATHS mapping
# ---------------------------------------------------------------------------


class TestToolSkillPaths:
    def test_all_expected_tools_present(self):
        assert set(TOOL_SKILL_PATHS.keys()) == {"claude", "codex", "opencode", "cursor"}

    def test_claude_path_shape(self):
        # Under real home, the path should end with .claude/skills
        assert TOOL_SKILL_PATHS["claude"].parts[-2:] == (".claude", "skills")

    def test_cursor_uses_rules_directory(self):
        assert TOOL_SKILL_PATHS["cursor"].parts[-2:] == (".cursor", "rules")


# ---------------------------------------------------------------------------
# Tests: distribute_skill
# ---------------------------------------------------------------------------


class TestDistributeSkill:
    async def test_writes_skill_md_to_correct_path(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="deploy-runbook")
        await metadata_store.create_skill(skill)

        written = await distributor.distribute_skill(skill, [], ["claude"])

        target = tmp_tool_paths["claude"] / "deploy-runbook"
        assert str(target) in written
        skill_md = target / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "name: deploy-runbook" in content
        assert "# Deploy Runbook" in content

    async def test_writes_supporting_files(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="deploy-runbook")
        await metadata_store.create_skill(skill)

        files = [
            _make_skill_file(skill.id, "scripts/deploy.sh", "#!/bin/bash\necho go"),
            _make_skill_file(skill.id, "config/app.yml", "port: 8080"),
        ]

        await distributor.distribute_skill(skill, files, ["claude"])

        skill_dir = tmp_tool_paths["claude"] / "deploy-runbook"
        assert (skill_dir / "scripts" / "deploy.sh").read_text() == "#!/bin/bash\necho go"
        assert (skill_dir / "config" / "app.yml").read_text() == "port: 8080"

    async def test_distribute_to_multiple_tools(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="shared-skill")
        await metadata_store.create_skill(skill)

        written = await distributor.distribute_skill(skill, [], ["claude", "codex", "cursor"])

        assert len(written) == 3
        for tool in ("claude", "codex", "cursor"):
            skill_dir = tmp_tool_paths[tool] / "shared-skill"
            assert (skill_dir / "SKILL.md").exists()

    async def test_unknown_tool_is_skipped(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="test")
        await metadata_store.create_skill(skill)

        written = await distributor.distribute_skill(skill, [], ["claude", "nonexistent-tool"])

        # Only the valid tool is in the written list
        assert len(written) == 1
        assert "claude" in written[0]

    async def test_distribution_is_logged(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="logged-skill")
        await metadata_store.create_skill(skill)

        await distributor.distribute_skill(skill, [], ["claude", "codex"])

        distributions = await metadata_store.get_skill_distributions(skill.id)
        assert len(distributions) == 2
        tools = {d["tool"] for d in distributions}
        assert tools == {"claude", "codex"}


class TestRemoveSkill:
    async def test_remove_skill_deletes_directory(
        self,
        metadata_store: MetadataStore,
        tmp_tool_paths: dict[str, Path],
    ):
        distributor = SkillDistributor(metadata_store)
        skill = _make_skill(name="temp-skill")
        await metadata_store.create_skill(skill)

        await distributor.distribute_skill(skill, [], ["claude"])
        skill_dir = tmp_tool_paths["claude"] / "temp-skill"
        assert skill_dir.exists()

        await distributor.remove_skill(skill.name, ["claude"])
        assert not skill_dir.exists()
