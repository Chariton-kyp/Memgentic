"""Skill importer — fetch skills from external sources (GitHub, local paths).

Currently supports GitHub repositories via the REST API + raw.githubusercontent.com
for file content. Parses the SKILL.md YAML frontmatter with a tiny line-based
parser so we do not introduce a YAML dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import structlog

from memgentic.models import Skill, SkillFile

logger = structlog.get_logger()

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"
_USER_AGENT = "memgentic-skill-importer/1.0"


class SkillImportError(Exception):
    """Raised when a skill cannot be imported from a remote source."""


@dataclass(frozen=True)
class _GitHubLocation:
    """Parsed GitHub URL components."""

    owner: str
    repo: str
    branch: str | None
    path: str  # may be empty string when the repo root is the skill dir


def _parse_github_url(url: str) -> _GitHubLocation:
    """Parse a GitHub URL into (owner, repo, branch, path).

    Supported forms::

        https://github.com/{owner}/{repo}
        https://github.com/{owner}/{repo}/
        https://github.com/{owner}/{repo}/tree/{branch}
        https://github.com/{owner}/{repo}/tree/{branch}/{path...}
        https://github.com/{owner}/{repo}/blob/{branch}/{path...}
    """
    parsed = urlparse(url.strip())
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise SkillImportError(f"Not a github.com URL: {url}")

    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2:
        raise SkillImportError(f"Malformed GitHub URL (missing owner/repo): {url}")

    owner, repo = segments[0], segments[1]
    # Strip a trailing .git suffix on repo names
    if repo.endswith(".git"):
        repo = repo[:-4]

    branch: str | None = None
    path = ""
    if len(segments) >= 4 and segments[2] in {"tree", "blob"}:
        branch = segments[3]
        path = "/".join(segments[4:])

    return _GitHubLocation(owner=owner, repo=repo, branch=branch, path=path)


def parse_skill_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse a SKILL.md file into (metadata, body).

    Extremely permissive line-based parser for the subset of YAML we use:
    top-level scalars (``name: foo``), flow-style lists (``tags: [a, b, c]``),
    and block-style lists (``tags:\\n  - a\\n  - b``).

    Returns ``(metadata, body)`` — metadata is ``{}`` when there is no
    frontmatter block.
    """
    # Normalize line endings so the regex match is stable across platforms
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not normalized.startswith("---\n") and normalized != "---":
        return {}, text

    # Find the closing --- marker
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", normalized, flags=re.DOTALL)
    if not match:
        return {}, text

    frontmatter_block = match.group(1)
    body = match.group(2)

    metadata: dict[str, object] = {}
    current_list: list[str] | None = None

    for raw_line in frontmatter_block.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue

        # Block-list continuation (e.g. "  - item")
        list_item_match = re.match(r"^\s+-\s+(.*)$", line)
        if current_list is not None and list_item_match:
            current_list.append(_strip_yaml_scalar(list_item_match.group(1)))
            continue

        # Reset list context whenever we see a new key
        current_list = None

        key_value_match = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not key_value_match:
            # Unparseable line — skip rather than crashing
            logger.debug("skill_importer.frontmatter_skip", line=line)
            continue

        key = key_value_match.group(1).strip()
        raw_value = key_value_match.group(2).strip()

        if not raw_value:
            # Start of a block-style list/mapping
            current_list = []
            metadata[key] = current_list
            continue

        # Flow-style list: [a, b, c]
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1].strip()
            items = [_strip_yaml_scalar(part) for part in _split_flow_list(inner) if part.strip()]
            metadata[key] = items
            continue

        metadata[key] = _strip_yaml_scalar(raw_value)

    return metadata, body.lstrip("\n")


def _strip_yaml_scalar(value: str) -> str:
    """Trim whitespace and surrounding quotes from a YAML scalar."""
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        return stripped[1:-1]
    return stripped


def _split_flow_list(inner: str) -> list[str]:
    """Split a flow-style list body (e.g. 'a, "b, c", d') respecting quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _sanitize_name(name: str) -> str:
    """Convert an arbitrary name into a safe kebab-case skill name."""
    lowered = name.strip().lower()
    # Replace any non-alphanumeric runs with single hyphens
    kebab = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return kebab[:200] or "imported-skill"


class SkillImporter:
    """Imports skills from external sources (GitHub, local paths)."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._external_client = http_client
        self._default_headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        }

    async def import_from_github(self, github_url: str) -> Skill:
        """Fetch a skill from a GitHub repo URL.

        Steps:
        1. Parse URL into owner/repo/branch/path.
        2. Resolve the default branch if none was provided.
        3. List files at the skill directory via the GitHub API.
        4. Find SKILL.md, parse its YAML frontmatter for metadata.
        5. Fetch all files under the directory (recursively) using the raw
           content host.
        6. Return a Skill object with SkillFile children.
        """
        location = _parse_github_url(github_url)

        owned_client = self._external_client is None
        client = self._external_client or httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        )
        try:
            branch = location.branch or await self._default_branch(
                client, location.owner, location.repo
            )
            tree_files = await self._list_tree_files(
                client, location.owner, location.repo, branch, location.path
            )
            if not tree_files:
                raise SkillImportError(
                    f"No files found at {location.owner}/{location.repo}/{location.path}"
                )

            # Locate SKILL.md (case-insensitive), prefer one at the base path
            base_prefix = location.path.rstrip("/")
            skill_md_path = _find_skill_md(tree_files, base_prefix)
            if not skill_md_path:
                raise SkillImportError("No SKILL.md found in the referenced GitHub path")

            skill_md_content = await self._fetch_raw(
                client, location.owner, location.repo, branch, skill_md_path
            )
            metadata, body = parse_skill_frontmatter(skill_md_content)

            # The skill directory is the parent of SKILL.md
            skill_dir = skill_md_path.rsplit("/", 1)[0] if "/" in skill_md_path else ""

            # Figure out name/description
            name_raw = metadata.get("name") if isinstance(metadata.get("name"), str) else None
            if not name_raw:
                name_raw = skill_dir.rsplit("/", 1)[-1] if skill_dir else location.repo
            name = _sanitize_name(str(name_raw))

            description = ""
            if isinstance(metadata.get("description"), str):
                description = str(metadata["description"])

            version = "1.0.0"
            if isinstance(metadata.get("version"), str):
                version = str(metadata["version"])

            tags: list[str] = []
            raw_tags = metadata.get("tags")
            if isinstance(raw_tags, list):
                tags = [str(t).strip() for t in raw_tags if str(t).strip()]
            elif isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

            # Collect companion files (everything under skill_dir except SKILL.md)
            companion_paths = [
                p
                for p in tree_files
                if (not skill_dir or p.startswith(skill_dir + "/") or p == skill_dir)
                and p != skill_md_path
                and not p.endswith("/")
            ]

            files: list[SkillFile] = []
            for remote_path in sorted(companion_paths):
                try:
                    content = await self._fetch_raw(
                        client,
                        location.owner,
                        location.repo,
                        branch,
                        remote_path,
                    )
                except SkillImportError as exc:
                    logger.warning(
                        "skill_importer.file_fetch_failed",
                        path=remote_path,
                        error=str(exc),
                    )
                    continue

                if skill_dir and remote_path.startswith(skill_dir + "/"):
                    relative = remote_path[len(skill_dir) + 1 :]
                else:
                    relative = remote_path
                if not relative:
                    continue

                files.append(
                    SkillFile(
                        skill_id="",  # populated by caller once skill.id exists
                        path=relative,
                        content=content,
                    )
                )

            skill = Skill(
                name=name,
                description=description.strip(),
                content=body.strip(),
                source="imported",
                source_url=github_url,
                version=version,
                tags=tags,
            )
            # Point file parents at the skill we just created
            for sf in files:
                sf.skill_id = skill.id
            skill.files = files

            logger.info(
                "skill_importer.github_imported",
                url=github_url,
                name=skill.name,
                files=len(files),
            )
            return skill
        finally:
            if owned_client:
                await client.aclose()

    # ── HTTP helpers ───────────────────────────────────────────────────

    async def _default_branch(self, client: httpx.AsyncClient, owner: str, repo: str) -> str:
        url = f"{_GITHUB_API}/repos/{owner}/{repo}"
        try:
            response = await client.get(url, headers=self._default_headers)
        except httpx.HTTPError as exc:
            raise SkillImportError(f"GitHub API request failed for {owner}/{repo}: {exc}") from exc
        if response.status_code == 404:
            raise SkillImportError(f"Repository not found: {owner}/{repo}")
        if response.status_code >= 400:
            raise SkillImportError(
                f"GitHub API error {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        branch = data.get("default_branch")
        if not isinstance(branch, str) or not branch:
            return "main"
        return branch

    async def _list_tree_files(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        branch: str,
        path: str,
    ) -> list[str]:
        """List every file path under ``path`` using the recursive git tree API.

        Returns paths relative to the repository root.
        """
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        try:
            response = await client.get(url, headers=self._default_headers)
        except httpx.HTTPError as exc:
            raise SkillImportError(
                f"GitHub tree request failed for {owner}/{repo}@{branch}: {exc}"
            ) from exc

        if response.status_code == 404:
            raise SkillImportError(f"Branch not found: {owner}/{repo}@{branch}")
        if response.status_code >= 400:
            raise SkillImportError(
                f"GitHub tree API error {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        entries = payload.get("tree", [])
        prefix = path.rstrip("/")
        results: list[str] = []
        for entry in entries:
            if entry.get("type") != "blob":
                continue
            entry_path = entry.get("path")
            if not isinstance(entry_path, str):
                continue
            if prefix:
                if entry_path == prefix or entry_path.startswith(prefix + "/"):
                    results.append(entry_path)
            else:
                results.append(entry_path)
        return results

    async def _fetch_raw(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        branch: str,
        remote_path: str,
    ) -> str:
        """Download a file's contents from raw.githubusercontent.com."""
        url = f"{_GITHUB_RAW}/{owner}/{repo}/{branch}/{remote_path}"
        try:
            response = await client.get(url, headers={"User-Agent": _USER_AGENT})
        except httpx.HTTPError as exc:
            raise SkillImportError(f"Failed to fetch {remote_path}: {exc}") from exc

        if response.status_code == 404:
            raise SkillImportError(f"File not found: {remote_path}")
        if response.status_code >= 400:
            raise SkillImportError(f"Raw content error {response.status_code} for {remote_path}")
        return response.text


def _find_skill_md(files: list[str], base_prefix: str) -> str | None:
    """Return the best SKILL.md candidate within ``files``.

    Prefers a SKILL.md that sits at the base of ``base_prefix`` (or repo root
    when the base is empty). Falls back to the shallowest match otherwise.
    """
    candidates = [p for p in files if p.rsplit("/", 1)[-1].lower() == "skill.md"]
    if not candidates:
        return None

    preferred_parent = base_prefix.rstrip("/")
    for candidate in candidates:
        parent = candidate.rsplit("/", 1)[0] if "/" in candidate else ""
        if parent == preferred_parent:
            return candidate

    # Fall back to the candidate with the fewest path segments
    candidates.sort(key=lambda p: p.count("/"))
    return candidates[0]
