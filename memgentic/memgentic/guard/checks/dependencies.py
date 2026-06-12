from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections.abc import Callable

from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule, Violation

BlobGetter = Callable[[str], str | None]
_MANIFESTS = ("pyproject.toml", "package.json", "requirements.txt")


def _is_csharp_manifest(path: str) -> bool:
    """True for .NET dependency manifests (.csproj and Directory.Packages.props)."""
    return path.endswith(".csproj") or path.endswith("Directory.Packages.props")


def _is_manifest(path: str) -> bool:
    return path.endswith(_MANIFESTS) or _is_csharp_manifest(path)


def _in_scope(path: str, scope: str) -> bool:
    if scope in ("**", "*", ""):
        return True
    return fnmatch.fnmatch(path, scope)


def _strip_comment(line: str, path: str) -> str:
    if not path.endswith(("pyproject.toml", "requirements.txt")):
        return line  # json has no line comments
    if line.lstrip().startswith("#"):
        return ""  # full-line comment
    return re.split(r"\s#", line, maxsplit=1)[0]  # inline comment needs leading whitespace


def _canon(s: str) -> str:
    """PEP 503 canonical package name: lowercase, collapse [-_.] to '-'."""
    return re.sub(r"[-_.]+", "-", s.strip().strip('"').strip("'").lower())


def _norm_pkg(req: str) -> str:
    raw = re.split(r"[<>=!~;\[\s]", req.strip().strip('"').strip("'"))[0]
    return _canon(raw)


def _core_dep_names(blob_getter: BlobGetter, path: str) -> set[str] | None:
    """Return normalized names of *shipped/core* deps for section-aware filtering.

    For pyproject.toml: packages in [project.dependencies].
    For package.json: packages in "dependencies" only (not devDependencies etc.).
    Returns None for requirements.txt or if blob is missing/unparseable
    (→ fall back to firing on any matched line).
    """
    if path.endswith("pyproject.toml"):
        blob = blob_getter(path)
        if not blob:
            return None
        try:
            data = tomllib.loads(blob)
        except Exception:
            return None
        deps = data.get("project", {}).get("dependencies", [])
        if not deps:
            # no [project.dependencies] section (Poetry/Hatch-style) → fire on any match
            return None
        return {_norm_pkg(d) for d in deps if isinstance(d, str)}

    if path.endswith("package.json"):
        blob = blob_getter(path)
        if not blob:
            return None
        try:
            data = json.loads(blob)
        except Exception:
            return None
        deps = data.get("dependencies") or {}
        if not deps:
            return None  # no "dependencies" section → fire on any match
        return {_canon(k) for k in deps}

    return None


def _base_dep_names(base_blob_getter: BlobGetter, path: str) -> set[str] | None:
    """Return ALL normalized dep names from the base-side manifest for suppression.

    For pyproject.toml: includes both [project.dependencies] AND every list
    under [project.optional-dependencies] so that any pre-existing package
    (core or extra) suppresses a re-fire on a version bump.

    For requirements.txt: all non-comment, non-blank lines; VCS lines with
    #egg=<name> use the egg name; other VCS/URL lines without an egg fragment
    are skipped.

    For package.json: union of keys across "dependencies", "devDependencies",
    "peerDependencies", and "optionalDependencies" (all canonicalized).
    An empty union is returned as an empty set (meaning nothing pre-existing).

    Returns None if the blob is missing/unparseable — in those cases the caller
    must NOT suppress (safe default).
    """
    if path.endswith("pyproject.toml"):
        blob = base_blob_getter(path)
        if not blob:
            return None
        try:
            data = tomllib.loads(blob)
        except Exception:
            return None
        names: set[str] = set()
        for d in data.get("project", {}).get("dependencies", []):
            if isinstance(d, str):
                names.add(_norm_pkg(d))
        for extras_list in data.get("project", {}).get("optional-dependencies", {}).values():
            for d in extras_list:
                if isinstance(d, str):
                    names.add(_norm_pkg(d))
        return names if names else None

    if path.endswith("requirements.txt"):
        blob = base_blob_getter(path)
        if not blob:
            return None
        names = set()
        for raw_line in blob.splitlines():
            line = _strip_comment(raw_line, path).strip()
            if not line:
                continue
            # VCS / URL lines: try to extract egg fragment
            if line.startswith(("git+", "hg+", "svn+", "bzr+", "-e ", "http://", "https://")):
                egg_match = re.search(r"#egg=([A-Za-z0-9_.-]+)", line)
                if egg_match:
                    names.add(_canon(egg_match.group(1)))
                # else: skip unparseable VCS line
                continue
            # Options flags (e.g. -r, --index-url, --constraint)
            if line.startswith("-"):
                continue
            names.add(_norm_pkg(line))
        return names  # may be empty set — callers treat empty set as "nothing pre-existing"

    if path.endswith("package.json"):
        blob = base_blob_getter(path)
        if not blob:
            return None
        try:
            data = json.loads(blob)
        except Exception:
            return None
        names = set()
        _sections = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
        for section in _sections:
            for k in data.get(section) or {}:
                names.add(_canon(k))
        return names  # may be empty set

    return None


def _build_target_pattern(target: str) -> re.Pattern[str]:
    """Build a case-insensitive, separator-tolerant regex for a package name.

    Splits on the canonical separator '-' and joins with [-_.]+ so that
    'langchain-core', 'langchain_core', 'Langchain.Core', etc. all match,
    but 'langchain-core-extras' does NOT (the trailing separator trips the
    negative lookahead).
    """
    canon = _canon(target)
    parts = [re.escape(p) for p in canon.split("-")]
    pattern = r"[-_.]+".join(parts)
    return re.compile(rf"(?<![\w.-]){pattern}(?![\w.-])", re.IGNORECASE)


# Match <PackageReference Include="X" .../> and Update="X"; also
# <PackageVersion Include="X" .../> used by central package management. The
# package ID is whatever sits inside the Include/Update attribute quotes.
_PKG_REF = re.compile(
    r"<Package(?:Reference|Version)\b[^>]*?\b(?:Include|Update)\s*=\s*"
    r'"([^"]+)"',
    re.IGNORECASE,
)


# Strip complete single-line XML comments (<!-- ... -->) so a commented-out
# PackageReference does not fire. Multi-line comment spans are out of scope
# (we only ever see added lines, never the surrounding span); a fully
# single-line comment is by far the common case.
_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_xml_comments(text: str) -> str:
    return _XML_COMMENT.sub("", text)


def _csproj_pkg_ids(blob: str | None) -> set[str]:
    """Return the lowercased set of NuGet package IDs referenced in a manifest blob."""
    if not blob:
        return set()
    return {m.group(1).strip().lower() for m in _PKG_REF.finditer(_strip_xml_comments(blob))}


def _check_csharp(
    rule: GuardRule,
    df: DiffFile,
    base_blob_getter: BlobGetter | None,
) -> list[Violation]:
    # NuGet IDs are case-insensitive; match must be EXACT (no prefix/substring).
    targets_lower = {t.strip().lower() for t in rule.targets}

    # Base-side suppression: any package ID already in the base manifest (at any
    # version) suppresses a re-fire — version bumps stay silent.
    base_ids: set[str] = set()
    if base_blob_getter is not None:
        base_ids = _csproj_pkg_ids(base_blob_getter(df.path))

    out: list[Violation] = []
    for lineno, text in sorted(df.added_lines.items()):
        for m in _PKG_REF.finditer(_strip_xml_comments(text)):
            pkg_id = m.group(1).strip().lower()
            if pkg_id not in targets_lower:
                continue
            if pkg_id in base_ids:
                continue
            out.append(
                Violation(
                    rule_id=rule.id,
                    message=rule.message,
                    file=df.path,
                    line=lineno,
                    snippet=text.strip(),
                    severity=rule.severity,
                )
            )
            break  # one violation per line
    return out


def check(
    rule: GuardRule,
    diff_files: list[DiffFile],
    blob_getter: BlobGetter,
    *,
    base_blob_getter: BlobGetter | None = None,
) -> list[Violation]:
    out: list[Violation] = []
    # word-boundary that treats '-' as part of the token, so 'langchain-core'
    # does NOT match inside 'langchain-core-extras'
    targets = [(t, _build_target_pattern(t)) for t in rule.targets]
    for df in diff_files:
        if df.is_binary or not _is_manifest(df.path) or not _in_scope(df.path, rule.scope):
            continue
        if _is_csharp_manifest(df.path):
            out.extend(_check_csharp(rule, df, base_blob_getter))
            continue
        # For pyproject.toml, restrict to packages actually in [project.dependencies]
        # so a banned package living in an optional extra does not fire. None means
        # "no section info" (non-pyproject, or unparseable) → fire on any match.
        core = _core_dep_names(blob_getter, df.path)

        # Build the set of dep names already in the base manifest so that a
        # version bump of a pre-existing banned dep doesn't re-fire.
        base_names: set[str] | None = None
        if base_blob_getter is not None:
            base_names = _base_dep_names(base_blob_getter, df.path)

        for lineno, text in df.added_lines.items():
            code = _strip_comment(text, df.path)
            for target, pattern in targets:
                if not pattern.search(code):
                    continue
                if core is not None and _norm_pkg(target) not in core:
                    continue  # banned package is in an extra, not [project.dependencies]
                # Skip if this target was already present in the base manifest
                if base_names is not None and _norm_pkg(target) in base_names:
                    continue
                out.append(
                    Violation(
                        rule_id=rule.id,
                        message=rule.message,
                        file=df.path,
                        line=lineno,
                        snippet=text.strip(),
                        severity=rule.severity,
                    )
                )
                break  # one violation per line
    return out
