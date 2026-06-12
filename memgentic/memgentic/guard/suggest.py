"""LLM-assisted rule DISCOVERY for guard — ``memgentic guard suggest``.

This module reads a repo's prose rule files (AGENTS.md, CLAUDE.md, cursor
rules, ADRs, …) and PROPOSES machine-checkable guard rules for human review.
It is an **advisory drafting tool**: it never enforces, never writes any file
in the target repo, and renders its output as ready-to-paste YAML on STDOUT.

Enforcement stays 100% deterministic — the `guard` engine only ever runs
rules a human has saved into `decisions.yaml`. This command just drafts them.

Design constraints (mirrors ``processing/dream.py``):

* All LLM imports are **lazy** and behind the ``[intelligence]`` extra. On a
  base install (or with no configured provider) we raise ``SuggestUnavailableError``
  with an actionable message instead of a stack trace.
* The LLM call reuses ``processing.llm.LLMClient`` and the same model-name
  routing as dream (``_build_phase_llm``) — we do not reinvent providers.
* Post-validation is **deterministic**: every proposed rule is validated
  against the real ``GuardRule`` pydantic model, low-confidence and duplicate
  rules are dropped, and invalid ones are collected as warnings.

``FORBIDDEN_PATH`` note: a parallel PR is adding a ``forbidden_path`` guard
rule type. We let the model emit it (it's a real, deterministic rule shape),
but because ``GuardRuleType`` may not yet contain it in this checkout, the
validator treats it specially — it is rendered into the YAML with a header
caveat ("requires guard >= the next release") and skips pydantic validation
for that single type. The code handles both worlds: if/when the enum gains
``FORBIDDEN_PATH``, it validates normally with no other change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from memgentic.config import MemgenticSettings
from memgentic.models import GuardRule, GuardRuleType

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Caps (bytes) — bound how much prose we feed the model
# ---------------------------------------------------------------------------

_PER_FILE_CAP = 30_000  # ~30 KB per source file
_TOTAL_CAP = 120_000  # ~120 KB total budget across all sources

# The guard rule types the model is allowed to propose. ``forbidden_path`` is
# included even though ``GuardRuleType`` may not yet define it (parallel PR);
# the validator handles the gap. The other three are the live, enforceable
# types in this checkout.
_PROPOSABLE_TYPES = (
    "import_direction",
    "banned_import",
    "banned_dependency",
    "forbidden_path",
)

# Types not (yet) backed by a ``GuardRuleType`` enum member. We still emit
# them in the YAML but skip pydantic validation for them and annotate the
# output header so the user knows they need a newer guard.
_FUTURE_TYPES = frozenset(t for t in _PROPOSABLE_TYPES if t not in {m.value for m in GuardRuleType})


class SuggestUnavailableError(RuntimeError):
    """Raised when guard suggest can't run: missing extras or no LLM provider.

    The CLI maps this to exit code 2 and prints ``str(exc)`` verbatim, so the
    message must be clean and actionable.
    """


# ---------------------------------------------------------------------------
# Source files we scan for prose rules
# ---------------------------------------------------------------------------
#
# Two kinds of entries:
#   * plain relative paths — checked for existence directly
#   * glob patterns (contain ``*``) — expanded against the repo root, files only
#
# Order matters only for stable output; dedupe is by resolved path.

_SOURCE_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)

_SOURCE_GLOBS = (
    ".cursor/rules/*",
    ".agents/rules/*.md",
    ".agents/guidelines/*.md",
    "docs/adr/*.md",
)


@dataclass
class CollectedSource:
    """One prose rule file gathered from the target repo."""

    path: str  # repo-relative POSIX path, for display + provenance
    text: str  # file contents (already per-file capped)


@dataclass
class SuggestResult:
    """Outcome of a suggest run, ready for rendering."""

    rules: list[GuardRule] = field(default_factory=list)
    # Future-typed rules kept as raw dicts (e.g. forbidden_path) — validated
    # only for shape, not against the pydantic model.
    future_rules: list[dict] = field(default_factory=list)
    sources_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_used: str = ""

    @property
    def total_proposed(self) -> int:
        return len(self.rules) + len(self.future_rules)


# ---------------------------------------------------------------------------
# 1. Source collection (deterministic, no LLM)
# ---------------------------------------------------------------------------


def collect_sources(
    repo: Path,
    *,
    per_file_cap: int = _PER_FILE_CAP,
    total_cap: int = _TOTAL_CAP,
) -> list[CollectedSource]:
    """Gather existing prose rule files from ``repo``.

    Each file is read text-only, truncated to ``per_file_cap`` bytes, and the
    running total is bounded by ``total_cap``. Missing files are skipped
    silently. Returns sources in a stable order (fixed file list first, then
    sorted glob matches). Unreadable files are skipped.
    """
    repo = Path(repo)
    out: list[CollectedSource] = []
    seen: set[Path] = set()
    budget = total_cap

    def _add(p: Path) -> bool:
        """Append a capped source. Returns False when the total budget is spent."""
        nonlocal budget
        try:
            resolved = p.resolve()
        except OSError:
            return True
        if resolved in seen:
            return True
        seen.add(resolved)
        if budget <= 0:
            return False
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            return True
        text = raw[:per_file_cap]
        text = text[:budget]
        if not text.strip():
            return True
        budget -= len(text)
        rel = p.relative_to(repo).as_posix() if _is_relative(p, repo) else p.name
        out.append(CollectedSource(path=rel, text=text))
        return True

    for name in _SOURCE_FILES:
        candidate = repo / name
        if candidate.is_file() and not _add(candidate):
            return out

    for pattern in _SOURCE_GLOBS:
        for match in sorted(repo.glob(pattern)):
            if match.is_file() and not _add(match):
                return out

    return out


def _is_relative(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# 2. LLM structured-output schema + prompt contract
# ---------------------------------------------------------------------------


def _build_schema() -> type[BaseModel]:
    """Build the structured-output schema lazily (pydantic is always present,
    but we keep the model construction local so the module imports cleanly on
    a base install and the schema stays close to the prompt contract)."""
    from pydantic import BaseModel, Field

    proposable = " | ".join(_PROPOSABLE_TYPES)

    class ProposedRule(BaseModel):
        id: str = Field(description="kebab-case unique rule id, e.g. 'no-mediatr'")
        type: str = Field(description=f"one of: {proposable}")
        scope: str = Field(
            default="**",
            description="glob of files the rule applies to, e.g. 'src/**' or '**'",
        )
        targets: list[str] = Field(
            description=(
                "CONCRETE strings the rule checks: module/package/namespace "
                "names or path globs. NEVER vague descriptions."
            ),
        )
        message: str = Field(description="human-readable explanation shown on violation")
        source: str = Field(description="the source file this rule came from")
        snippet: str = Field(description="the exact quoted prose snippet that justifies the rule")
        confidence: float = Field(
            description="0.0-1.0 — how confident this is a deterministic rule"
        )

    class ProposedRuleSet(BaseModel):
        rules: list[ProposedRule] = Field(default_factory=list)

    return ProposedRuleSet


_SYSTEM_PROMPT = """\
You are a precise software-architecture rule extractor for a deterministic guard tool.

Your job: read prose engineering-rule documents and extract ONLY the rules that
can be checked MECHANICALLY by matching imports, dependency manifests, or file
paths. You output JSON matching the given schema. Nothing is enforced from your
output — a human reviews every rule before it is saved.

The guard tool supports exactly these rule types:

- import_direction: forbid a layer/package from importing another layer.
  targets = the package/module names that the scoped files must NOT import.
  Example: scope "core/**", targets ["api", "web"], "core must not import api".

- banned_import: forbid importing specific modules/packages anywhere in scope.
  targets = concrete import names (e.g. ["requests", "MediatR", "StackExchange.Redis"]).

- banned_dependency: forbid a package from appearing in a dependency manifest
  (pyproject.toml / package.json / requirements.txt). targets = package names.

- forbidden_path: forbid changes to / creation of files matching path globs.
  targets = concrete path globs (e.g. ["**/.env", "**/appsettings.Production.json"]).

STRICT RULES:
1. ONLY emit rules expressible as one of the four types above.
2. targets MUST be CONCRETE: real module names, package names, or path globs.
   NEVER emit vague targets like "bad code", "anti-patterns", "legacy stuff".
3. NO aspirational, stylistic, or semantic rules ("write clean code", "prefer
   composition", "add tests"). Those are not mechanically checkable — OMIT them.
4. When in doubt, OMIT the rule. Precision over recall. A wrong rule costs the
   reviewer more than a missing one.
5. Every rule MUST cite its `source` file and quote the exact `snippet` of prose
   that justifies it.
6. Set `confidence` honestly: 0.9+ only for explicit, unambiguous bans;
   0.5-0.8 for clear-but-implicit rules; below 0.5 means you should have omitted it.
7. Use kebab-case ids that describe the rule (e.g. "ban-mediatr", "no-secrets-in-git").
"""

_USER_TEMPLATE = """\
Extract machine-checkable guard rules from the following prose rule documents.

Target repo: {repo_name}

=== SOURCE DOCUMENTS ===
{sources_block}
=== END SOURCE DOCUMENTS ===

Return JSON with a `rules` array. Each rule: id, type, scope, targets, message,
source, snippet, confidence. Emit ONLY mechanically-checkable rules. When in
doubt, omit. Concrete targets only.
"""


_PLAIN_JSON_SUFFIX = """

Respond with ONLY a JSON object using EXACTLY these field names (do not invent
fields like description/severity/check_type/source_file):

{"rules": [
  {"id": "ban-mediatr", "type": "banned_import", "scope": "**",
   "targets": ["MediatR"], "message": "MediatR is banned; use direct handlers",
   "source": "CLAUDE.md", "snippet": "Do not use MediatR", "confidence": 0.9}
]}

Allowed `type` values ONLY: import_direction, banned_import, banned_dependency,
forbidden_path. `targets` MUST be concrete module/package names or path globs —
never descriptions. Set `confidence` between 0 and 1. Omit any rule you can't
express this way. No prose, no markdown fences — just the JSON object. If there
are no machine-checkable rules, respond with {"rules": []}.
"""


def _format_sources(sources: list[CollectedSource]) -> str:
    blocks: list[str] = []
    for s in sources:
        blocks.append(f"--- FILE: {s.path} ---\n{s.text}")
    return "\n\n".join(blocks)


def build_prompt(repo_name: str, sources: list[CollectedSource]) -> str:
    """Assemble the full system+user prompt for the suggest LLM call."""
    user = _USER_TEMPLATE.format(
        repo_name=repo_name,
        sources_block=_format_sources(sources),
    )
    return _SYSTEM_PROMPT + "\n\n" + user


# ---------------------------------------------------------------------------
# 3. Post-validation (deterministic)
# ---------------------------------------------------------------------------


_MIN_CONFIDENCE = 0.5


def validate_proposals(
    raw_rules: list[dict],
) -> tuple[list[GuardRule], list[dict], list[str]]:
    """Validate LLM-proposed rules deterministically.

    Returns ``(valid_rules, future_rules, warnings)`` where:

    * ``valid_rules`` — proposals that pass ``GuardRule`` pydantic validation,
      have confidence >= 0.5, and survive (type, targets) dedupe.
    * ``future_rules`` — proposals whose type isn't (yet) a ``GuardRuleType``
      member (e.g. ``forbidden_path``). Kept as shape-checked dicts so they
      still render into the YAML draft.
    * ``warnings`` — human-readable notes about every dropped/skipped proposal.

    Dedupe key is ``(type, sorted(targets))`` so the same ban from two source
    files collapses to one rule. Confidence is preserved as a private attribute
    on the returned ``GuardRule`` objects (``_suggest_confidence``) and on the
    ``future_rules`` dicts for rendering.
    """
    valid: list[GuardRule] = []
    future: list[dict] = []
    warnings: list[str] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    for i, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            warnings.append(f"rule #{i}: not an object — dropped")
            continue

        rid = str(raw.get("id") or f"rule-{i}")
        rtype = str(raw.get("type") or "").strip()
        confidence = _coerce_confidence(raw.get("confidence"))
        targets = [str(t).strip() for t in (raw.get("targets") or []) if str(t).strip()]

        if confidence < _MIN_CONFIDENCE:
            warnings.append(f"'{rid}': dropped — confidence {confidence:.2f} < {_MIN_CONFIDENCE}")
            continue

        if rtype not in _PROPOSABLE_TYPES:
            warnings.append(f"'{rid}': dropped — unknown/unsupported type '{rtype}'")
            continue

        if not targets:
            warnings.append(f"'{rid}': dropped — no concrete targets")
            continue

        dedupe_key = (rtype, tuple(sorted(targets)))
        if dedupe_key in seen:
            warnings.append(f"'{rid}': dropped — duplicate of an earlier {rtype} rule")
            continue

        # Future type (not in this checkout's enum) — keep as a shape-checked
        # dict, skip pydantic validation, annotate.
        if rtype in _FUTURE_TYPES:
            seen.add(dedupe_key)
            future.append(
                {
                    "id": rid,
                    "type": rtype,
                    "scope": str(raw.get("scope") or "**"),
                    "targets": targets,
                    "message": str(raw.get("message") or rid),
                    "source": str(raw.get("source") or "(unknown)"),
                    "snippet": str(raw.get("snippet") or ""),
                    "confidence": confidence,
                }
            )
            continue

        # Live type — validate against the real pydantic model.
        try:
            rule = GuardRule(
                id=rid,
                type=GuardRuleType(rtype),
                scope=str(raw.get("scope") or "**"),
                targets=targets,
                message=str(raw.get("message") or rid),
                source=str(raw.get("source") or "decisions.yaml"),
            )
        except Exception as exc:  # noqa: BLE001 — collect, don't crash
            warnings.append(f"'{rid}': dropped — failed validation: {exc}")
            continue

        seen.add(dedupe_key)
        # Stash confidence + snippet for rendering without polluting the model.
        object.__setattr__(rule, "_suggest_confidence", confidence)
        object.__setattr__(rule, "_suggest_snippet", str(raw.get("snippet") or ""))
        valid.append(rule)

    return valid, future, warnings


def _coerce_confidence(value: object) -> float:
    try:
        c = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


# ---------------------------------------------------------------------------
# 4. YAML rendering (advisory output)
# ---------------------------------------------------------------------------

_HEADER = (
    "# PROPOSED by guard suggest — REVIEW BEFORE ENFORCING. Nothing is enforced "
    "until you save this as decisions.yaml yourself."
)


def render_yaml(result: SuggestResult) -> str:
    """Render a ``SuggestResult`` to ready-to-paste decisions.yaml text.

    Includes the prominent advisory header, a per-source manifest, and per-rule
    ``# source:`` / ``# confidence:`` comments. Future-typed rules (e.g.
    forbidden_path) get an extra caveat comment. This function NEVER writes a
    file.
    """
    import yaml

    lines: list[str] = [_HEADER, "#"]

    if result.model_used:
        lines.append(f"# model: {result.model_used}")
    if result.sources_found:
        lines.append(f"# sources scanned: {', '.join(result.sources_found)}")
    else:
        lines.append("# sources scanned: (none found)")
    if result.future_rules:
        future_types = sorted({r["type"] for r in result.future_rules})
        lines.append(
            f"# NOTE: rule type(s) {', '.join(future_types)} require guard >= the "
            "next release (not yet enforceable in your installed guard)."
        )
    if result.warnings:
        lines.append(f"# {len(result.warnings)} proposal(s) dropped during validation:")
        for w in result.warnings:
            lines.append(f"#   - {w}")
    lines.append("")

    if result.total_proposed == 0:
        lines.append("rules: []  # no machine-checkable rules discovered")
        return "\n".join(lines) + "\n"

    lines.append("rules:")

    for rule in result.rules:
        conf = getattr(rule, "_suggest_confidence", None)
        snippet = getattr(rule, "_suggest_snippet", "")
        lines.extend(
            _render_rule_block(
                rid=rule.id,
                rtype=rule.type.value,
                scope=rule.scope,
                targets=list(rule.targets),
                message=rule.message,
                source=rule.source,
                snippet=snippet,
                confidence=conf,
                future=False,
                yaml_mod=yaml,
            )
        )

    for raw in result.future_rules:
        lines.extend(
            _render_rule_block(
                rid=raw["id"],
                rtype=raw["type"],
                scope=raw["scope"],
                targets=list(raw["targets"]),
                message=raw["message"],
                source=raw["source"],
                snippet=raw.get("snippet", ""),
                confidence=raw.get("confidence"),
                future=True,
                yaml_mod=yaml,
            )
        )

    return "\n".join(lines) + "\n"


def _render_rule_block(
    *,
    rid: str,
    rtype: str,
    scope: str,
    targets: list[str],
    message: str,
    source: str,
    snippet: str,
    confidence: float | None,
    future: bool,
    yaml_mod,
) -> list[str]:
    """Render a single rule as YAML list-item lines with provenance comments."""
    lines: list[str] = []
    if confidence is not None:
        lines.append(f"  # confidence: {confidence:.2f}")
    lines.append(f"  # source: {source}")
    if snippet:
        # Keep the snippet on one comment line; collapse newlines.
        flat = " ".join(snippet.split())
        if len(flat) > 200:
            flat = flat[:197] + "..."
        lines.append(f"  # justification: {flat}")
    if future:
        lines.append(f"  # NOTE: '{rtype}' requires guard >= the next release.")

    # Build the mapping and dump it as a YAML block, then indent under the
    # list item. ``yaml.safe_dump`` quotes only where needed.
    body = {
        "id": rid,
        "type": rtype,
        "scope": scope,
        "targets": targets,
        "message": message,
        "source": source,
    }
    dumped = yaml_mod.safe_dump(
        body, sort_keys=False, default_flow_style=False, allow_unicode=True
    ).rstrip("\n")
    block = dumped.splitlines()
    # First key becomes the "- key:" list item; rest indented to align.
    lines.append(f"  - {block[0]}")
    for extra in block[1:]:
        lines.append(f"    {extra}")
    return lines


# ---------------------------------------------------------------------------
# 5. Orchestration — the public entry point
# ---------------------------------------------------------------------------


def _make_llm_client(settings: MemgenticSettings, model: str | None) -> object:
    """Build an LLMClient (or dream-style routed client) for suggest.

    Lazy: all LLM imports happen here. Raises ``SuggestUnavailableError`` with an
    actionable message when the ``[intelligence]`` extra is missing or no
    provider is configured.

    ``model`` follows the same routing convention as dream's ``--model``
    overrides (claude-*, gemini-*, gpt-*/openai/*, else an Ollama tag). When
    None/empty, the default ``LLMClient`` provider chain is used.
    """
    try:
        from memgentic.processing.llm import LLMClient
    except ImportError as exc:  # langchain provider extras missing
        raise SuggestUnavailableError(
            "guard suggest needs the [intelligence] extra and a configured LLM "
            "provider — Ollama works out of the box when running. "
            "Install with: pip install 'memgentic[intelligence]'"
        ) from exc

    client: object | None = None
    if model:
        # Reuse dream's provider routing so --model accepts the same names.
        try:
            from memgentic.processing.dream import _build_phase_llm

            client = _build_phase_llm(settings, model, "suggest")
        except ImportError as exc:
            raise SuggestUnavailableError(
                "guard suggest needs the [intelligence] extra and a configured LLM "
                "provider — Ollama works out of the box when running. "
                "Install with: pip install 'memgentic[intelligence]'"
            ) from exc

    if client is None:
        client = LLMClient(settings)

    if not getattr(client, "available", False):
        raise SuggestUnavailableError(
            "guard suggest could not reach an LLM provider. Ollama works out of "
            "the box when running (`ollama serve`); or configure a cloud provider "
            "(GOOGLE_API_KEY / ANTHROPIC_API_KEY / MEMGENTIC_OPENAI_COMPAT_BASE_URL). "
            "Ensure the [intelligence] extra is installed: pip install 'memgentic[intelligence]'"
        )
    return client


async def suggest_rules(
    repo: Path,
    *,
    settings: MemgenticSettings | None = None,
    model: str | None = None,
    llm_client: object | None = None,
) -> SuggestResult:
    """Discover proposed guard rules from a repo's prose rule files.

    Steps: collect sources → LLM structured extraction → deterministic
    post-validation. Returns a ``SuggestResult`` (caller renders it). Never
    writes any file in ``repo``.

    ``llm_client`` is an injection seam for tests — when provided it must
    expose ``available: bool`` and ``async generate_structured(prompt, schema)``
    (the ``LLMClient`` interface). When omitted, a client is built from
    ``settings`` (and ``model``), raising ``SuggestUnavailableError`` if none is
    reachable.
    """
    repo = Path(repo)
    if settings is None:
        settings = MemgenticSettings()

    sources = collect_sources(repo)
    sources_found = [s.path for s in sources]

    client = llm_client if llm_client is not None else _make_llm_client(settings, model)
    model_used = _describe_model(client, settings, model)

    if not sources:
        logger.info("guard.suggest.no_sources", repo=str(repo))
        return SuggestResult(
            rules=[],
            future_rules=[],
            sources_found=[],
            warnings=["no prose rule files found in the target repo"],
            model_used=model_used,
        )

    schema = _build_schema()
    prompt = build_prompt(repo.name or str(repo), sources)

    extra_warnings: list[str] = []
    raw_rules: list[dict] = []

    parsed = await client.generate_structured(prompt, schema)  # type: ignore[attr-defined]
    if parsed is not None:
        raw_rules = _extract_raw_rules(parsed)

    # Fallback: small local models (gemma4:e2b/e4b, qwen <7B) frequently ignore
    # the json_schema wrapper and emit a bare top-level array, which langchain's
    # structured path rejects. Recover by asking for plain JSON and parsing it
    # tolerantly. Post-validation is unchanged — determinism is preserved.
    if not raw_rules and hasattr(client, "generate"):
        logger.info("guard.suggest.fallback_plain_json", repo=str(repo))
        text = await client.generate(prompt + _PLAIN_JSON_SUFFIX)  # type: ignore[attr-defined]
        raw_rules = _parse_loose_json_rules(text)
        if not raw_rules:
            extra_warnings.append(
                "the LLM returned no usable rules (empty or unparseable response)"
            )

    if not raw_rules:
        logger.warning("guard.suggest.llm_empty", repo=str(repo))
        return SuggestResult(
            rules=[],
            future_rules=[],
            sources_found=sources_found,
            warnings=extra_warnings
            or ["the LLM returned no usable rules (empty or unparseable response)"],
            model_used=model_used,
        )

    valid, future, warnings = validate_proposals(raw_rules)
    warnings = extra_warnings + warnings

    logger.info(
        "guard.suggest",
        repo=str(repo),
        sources=len(sources_found),
        proposed=len(raw_rules),
        valid=len(valid),
        future=len(future),
        dropped=len(warnings),
    )

    return SuggestResult(
        rules=valid,
        future_rules=future,
        sources_found=sources_found,
        warnings=warnings,
        model_used=model_used,
    )


def _extract_raw_rules(parsed: object) -> list[dict]:
    """Normalize a parsed structured-output object into a list of rule dicts."""
    rules_attr = getattr(parsed, "rules", None)
    if rules_attr is None and isinstance(parsed, dict):
        rules_attr = parsed.get("rules")
    if not rules_attr:
        return []
    out: list[dict] = []
    for item in rules_attr:
        if isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "model_dump"):
            out.append(item.model_dump())
    return out


def _parse_loose_json_rules(text: str) -> list[dict]:
    """Tolerantly extract a list of rule dicts from a free-text LLM response.

    Handles the common small-model failure modes the structured path rejects:

    * markdown code fences (```json ... ```)
    * a bare top-level array ``[ {...}, {...} ]`` instead of ``{"rules": [...]}``
    * leading/trailing prose around the JSON

    Returns ``[]`` on anything unparseable. Never raises.
    """
    import json
    import re

    if not text or not text.strip():
        return []

    # Strip markdown fences if present.
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text.strip()

    # Try the whole candidate first, then the largest {...} or [...] slice.
    slices = [candidate]
    obj_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if obj_match:
        slices.append(obj_match.group(0))
    arr_match = re.search(r"\[.*\]", candidate, re.DOTALL)
    if arr_match:
        slices.append(arr_match.group(0))

    for chunk in slices:
        try:
            data = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            rules = data.get("rules")
            if isinstance(rules, list):
                return [r for r in rules if isinstance(r, dict)]
            # A single rule object dict, no wrapper.
            if "type" in data and "targets" in data:
                return [data]
        elif isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]

    return []


def _describe_model(client: object, settings: MemgenticSettings, model: str | None) -> str:
    """Best-effort human label for which model produced the proposals."""
    if model:
        return model
    kind = getattr(client, "_provider_kind", None)
    if kind == "ollama":
        return settings.local_llm_model
    if kind == "google":
        return settings.summarization_model
    if kind == "anthropic":
        return "anthropic"
    if kind == "openai_compat":
        return settings.openai_compat_model
    return kind or "(unknown)"
