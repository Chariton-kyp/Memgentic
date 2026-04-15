"""Skill distributor — writes skills to each AI tool's native discovery path.

Supports the Agent Skills open standard: each skill is a directory with a
SKILL.md file (YAML frontmatter + markdown body) and optional supporting files.

Supported tool paths:
- Claude Code: ~/.claude/skills/<name>/SKILL.md
- Codex CLI:   ~/.codex/skills/<name>/SKILL.md
- OpenCode:    ~/.config/opencode/skills/<name>/SKILL.md
- Cursor:      ~/.cursor/rules/<name>/SKILL.md
"""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog

from memgentic.models import Skill, SkillFile
from memgentic.storage.metadata import MetadataStore

logger = structlog.get_logger()

# Global (user-level) skill paths per tool
TOOL_SKILL_PATHS: dict[str, Path] = {
    "claude": Path.home() / ".claude" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "cursor": Path.home() / ".cursor" / "rules",
}


class SkillDistributor:
    """Writes skills from the database to each tool's native discovery path."""

    def __init__(self, metadata_store: MetadataStore) -> None:
        self._metadata = metadata_store

    async def distribute_skill(
        self,
        skill: Skill,
        skill_files: list[SkillFile],
        tools: list[str],
    ) -> list[str]:
        """Write a skill to the specified tools' native paths.

        Returns a list of target directories where the skill was written.
        """
        written: list[str] = []
        for tool in tools:
            target = TOOL_SKILL_PATHS.get(tool)
            if not target:
                logger.warning(
                    "skill_distributor.unknown_tool",
                    tool=tool,
                    skill=skill.name,
                )
                continue

            skill_dir = target / skill.name
            try:
                skill_dir.mkdir(parents=True, exist_ok=True)

                # Write SKILL.md (Agent Skills standard format)
                skill_md = self._render_skill_md(skill)
                (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

                # Write supporting files
                for sf in skill_files:
                    file_path = skill_dir / sf.path
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(sf.content, encoding="utf-8")

                # Log distribution in database
                await self._metadata.log_skill_distribution(skill.id, tool, str(skill_dir))
                written.append(str(skill_dir))

                logger.info(
                    "skill_distributor.distributed",
                    skill=skill.name,
                    tool=tool,
                    path=str(skill_dir),
                )
            except OSError as exc:
                logger.error(
                    "skill_distributor.write_failed",
                    skill=skill.name,
                    tool=tool,
                    error=str(exc),
                )

        return written

    async def remove_skill(self, skill_name: str, tools: list[str]) -> None:
        """Remove a skill from the specified tools' native paths."""
        for tool in tools:
            await self.remove_skill_from_tool(skill_name, tool)

    async def remove_skill_from_tool(self, skill_name: str, tool: str) -> None:
        """Remove a skill's files from a single tool's native path.

        Idempotent: silently returns when the target directory does not exist
        or when the tool is unknown. Raises nothing on non-OSError conditions.
        """
        target = TOOL_SKILL_PATHS.get(tool)
        if not target:
            logger.warning(
                "skill_distributor.unknown_tool",
                tool=tool,
                skill=skill_name,
            )
            return

        skill_dir = target / skill_name
        if not skill_dir.exists():
            logger.debug(
                "skill_distributor.remove_noop",
                skill=skill_name,
                tool=tool,
                path=str(skill_dir),
            )
            return

        try:
            shutil.rmtree(skill_dir)
            logger.info(
                "skill_distributor.removed",
                skill=skill_name,
                tool=tool,
                path=str(skill_dir),
            )
        except OSError as exc:
            logger.error(
                "skill_distributor.remove_failed",
                skill=skill_name,
                tool=tool,
                error=str(exc),
            )

    async def sync_all(self, skills: list[Skill]) -> None:
        """Full sync — ensure all auto-distribute skills are distributed."""
        for skill in skills:
            if not skill.auto_distribute:
                continue
            tools = skill.distribute_to
            files = skill.files or await self._metadata.get_skill_files(skill.id)
            await self.distribute_skill(skill, files, tools)

    @staticmethod
    def _render_skill_md(skill: Skill) -> str:
        """Render SKILL.md in Agent Skills standard format with YAML frontmatter."""
        lines = ["---"]
        lines.append(f"name: {skill.name}")
        if skill.description:
            lines.append(f"description: {skill.description}")
        if skill.version and skill.version != "1.0.0":
            lines.append(f"version: {skill.version}")
        if skill.tags:
            tags_str = ", ".join(skill.tags)
            lines.append(f"tags: [{tags_str}]")
        lines.append("---")
        lines.append("")
        lines.append(skill.content)
        return "\n".join(lines)
