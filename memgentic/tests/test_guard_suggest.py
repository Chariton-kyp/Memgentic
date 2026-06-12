"""Tests for ``memgentic guard suggest`` — LLM-assisted rule discovery.

No network: the LLM is always a fake/monkeypatched client. These tests cover
source collection (incl. caps), deterministic post-validation, YAML rendering
+ round-trip through ``engine.load_rules``, the end-to-end ``suggest_rules``
orchestration with a fake client, and the CLI's clean exit-2 path when no LLM
provider is available.
"""

from __future__ import annotations

import asyncio

import pytest
import yaml
from click.testing import CliRunner

from memgentic.guard import engine, suggest
from memgentic.guard.suggest import (
    CollectedSource,
    SuggestResult,
    SuggestUnavailableError,
    collect_sources,
    render_yaml,
    suggest_rules,
    validate_proposals,
)
from memgentic.models import GuardRule, GuardRuleType

# ---------------------------------------------------------------------------
# Source collection
# ---------------------------------------------------------------------------


def test_collect_sources_finds_known_files(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("core must not import api", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("ban requests", encoding="utf-8")
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "arch.md").write_text("no MediatR", encoding="utf-8")
    (tmp_path / ".agents" / "rules").mkdir(parents=True)
    (tmp_path / ".agents" / "rules" / "db.md").write_text("no in-memory db", encoding="utf-8")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001.md").write_text("ADR: ban rabbitmq", encoding="utf-8")

    sources = collect_sources(tmp_path)
    found = {s.path for s in sources}

    assert "CLAUDE.md" in found
    assert "AGENTS.md" in found
    assert ".cursor/rules/arch.md" in found
    assert ".agents/rules/db.md" in found
    assert "docs/adr/0001.md" in found


def test_collect_sources_skips_missing_and_empty(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("real content", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("   \n\n  ", encoding="utf-8")  # whitespace only

    sources = collect_sources(tmp_path)
    paths = {s.path for s in sources}

    assert "CLAUDE.md" in paths
    assert "AGENTS.md" not in paths  # empty/whitespace dropped
    assert "GEMINI.md" not in paths  # never existed


def test_collect_sources_respects_per_file_cap(tmp_path):
    big = "x" * 50_000
    (tmp_path / "CLAUDE.md").write_text(big, encoding="utf-8")

    sources = collect_sources(tmp_path, per_file_cap=1000, total_cap=10_000)

    assert len(sources) == 1
    assert len(sources[0].text) == 1000  # truncated to per-file cap


def test_collect_sources_respects_total_cap(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("a" * 8000, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("b" * 8000, encoding="utf-8")
    (tmp_path / "GEMINI.md").write_text("c" * 8000, encoding="utf-8")

    sources = collect_sources(tmp_path, per_file_cap=8000, total_cap=10_000)

    total = sum(len(s.text) for s in sources)
    assert total <= 10_000  # total budget enforced across files


# ---------------------------------------------------------------------------
# Post-validation
# ---------------------------------------------------------------------------


def test_validate_drops_invalid_type_with_warning():
    raw = [
        {
            "id": "bogus",
            "type": "write_clean_code",
            "targets": ["whatever"],
            "message": "m",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        }
    ]
    valid, future, warnings = validate_proposals(raw)
    assert valid == []
    assert future == []
    assert any("unknown/unsupported type" in w for w in warnings)


def test_validate_drops_low_confidence():
    raw = [
        {
            "id": "weak",
            "type": "banned_import",
            "targets": ["requests"],
            "message": "m",
            "source": "CLAUDE.md",
            "confidence": 0.3,
        }
    ]
    valid, _future, warnings = validate_proposals(raw)
    assert valid == []
    assert any("confidence" in w for w in warnings)


def test_validate_drops_empty_targets():
    raw = [
        {
            "id": "notargets",
            "type": "banned_import",
            "targets": [],
            "message": "m",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        }
    ]
    valid, _future, warnings = validate_proposals(raw)
    assert valid == []
    assert any("no concrete targets" in w for w in warnings)


def test_validate_dedupes_by_type_and_targets():
    raw = [
        {
            "id": "ban-requests-1",
            "type": "banned_import",
            "targets": ["requests"],
            "message": "from CLAUDE.md",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        },
        {
            "id": "ban-requests-2",
            "type": "banned_import",
            "targets": ["requests"],
            "message": "from AGENTS.md",
            "source": "AGENTS.md",
            "confidence": 0.8,
        },
    ]
    valid, _future, warnings = validate_proposals(raw)
    assert len(valid) == 1
    assert any("duplicate" in w for w in warnings)


def test_validate_keeps_valid_rule():
    raw = [
        {
            "id": "core-no-api",
            "type": "import_direction",
            "scope": "memgentic/**",
            "targets": ["memgentic_api", "dashboard"],
            "message": "core must not import api/dashboard",
            "source": "CLAUDE.md",
            "snippet": "Core must NEVER import from api",
            "confidence": 0.95,
        }
    ]
    valid, future, warnings = validate_proposals(raw)
    assert future == []
    assert warnings == []
    assert len(valid) == 1
    assert isinstance(valid[0], GuardRule)
    assert valid[0].type == GuardRuleType.IMPORT_DIRECTION
    assert valid[0]._suggest_confidence == pytest.approx(0.95)


def test_validate_handles_forbidden_path_both_worlds():
    """forbidden_path must be retained — either validated (if the enum has it)
    or kept as a future_rule (if it doesn't yet exist in this checkout)."""
    raw = [
        {
            "id": "no-secrets",
            "type": "forbidden_path",
            "targets": ["**/.env", "**/appsettings.Production.json"],
            "message": "never commit secrets",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        }
    ]
    valid, future, warnings = validate_proposals(raw)

    has_enum_member = "forbidden_path" in {m.value for m in GuardRuleType}
    if has_enum_member:
        assert len(valid) == 1
        assert valid[0].type.value == "forbidden_path"
    else:
        assert len(future) == 1
        assert future[0]["type"] == "forbidden_path"
        # not a "dropped" warning — forbidden_path is retained, not rejected
        assert not any("no-secrets" in w and "dropped" in w for w in warnings)


# ---------------------------------------------------------------------------
# YAML rendering + round-trip through engine.load_rules
# ---------------------------------------------------------------------------


def test_render_yaml_has_advisory_header():
    result = SuggestResult(model_used="gemma4:e4b")
    text = render_yaml(result)
    assert "PROPOSED by guard suggest" in text
    assert "REVIEW BEFORE ENFORCING" in text


def test_rendered_yaml_round_trips_through_load_rules(tmp_path):
    """Valid (live-type) rules must render to YAML that loads back cleanly.

    forbidden_path entries are excluded here when the type isn't in this
    checkout's enum (they go to future_rules and are commented as needing a
    newer guard) — engine.load_rules would reject them otherwise."""
    raw = [
        {
            "id": "core-no-api",
            "type": "import_direction",
            "scope": "memgentic/**",
            "targets": ["memgentic_api", "dashboard"],
            "message": "core must not import api/dashboard",
            "source": "CLAUDE.md",
            "snippet": "Core must NEVER import from api/dashboard",
            "confidence": 0.95,
        },
        {
            "id": "ban-llm-deps",
            "type": "banned_dependency",
            "scope": "memgentic/pyproject.toml",
            "targets": ["langchain-core", "langgraph"],
            "message": "LLM stack belongs in the intelligence extra",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        },
    ]
    valid, future, _warnings = validate_proposals(raw)
    result = SuggestResult(rules=valid, future_rules=future, model_used="test")
    text = render_yaml(result)

    # Round-trip: write to a tmp file and load through the real engine.
    out = tmp_path / "decisions.yaml"
    out.write_text(text, encoding="utf-8")
    loaded = engine.load_rules(out)

    # All live rules survive the round-trip with identical core fields.
    loaded_by_id = {r.id: r for r in loaded}
    assert "core-no-api" in loaded_by_id
    assert "ban-llm-deps" in loaded_by_id
    assert loaded_by_id["core-no-api"].targets == ["memgentic_api", "dashboard"]
    assert loaded_by_id["core-no-api"].type == GuardRuleType.IMPORT_DIRECTION

    # Per-rule provenance comments present.
    assert "# source: CLAUDE.md" in text
    assert "# confidence: 0.95" in text


def test_rendered_yaml_is_valid_yaml_even_when_empty():
    result = SuggestResult(model_used="test")
    text = render_yaml(result)
    data = yaml.safe_load(text)
    assert data == {"rules": []}


def test_future_type_rendered_with_caveat(tmp_path):
    raw = [
        {
            "id": "no-secrets",
            "type": "forbidden_path",
            "targets": ["**/.env"],
            "message": "never commit secrets",
            "source": "CLAUDE.md",
            "confidence": 0.9,
        }
    ]
    valid, future, _warnings = validate_proposals(raw)
    result = SuggestResult(rules=valid, future_rules=future, model_used="test")
    text = render_yaml(result)

    if future:  # forbidden_path not yet in this checkout's enum
        assert "requires guard >= the next release" in text


# ---------------------------------------------------------------------------
# End-to-end suggest_rules with a fake LLM client (no network)
# ---------------------------------------------------------------------------


class _FakeClient:
    """Mimics the LLMClient interface used by suggest_rules."""

    def __init__(self, payload, *, available=True, provider="ollama"):
        self._payload = payload
        self.available = available
        self._provider_kind = provider

    async def generate_structured(self, prompt, schema):
        if self._payload is None:
            return None
        return schema(**self._payload)


def test_suggest_rules_end_to_end_with_fake_client(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "Core must never import memgentic_api. Ban the requests library.",
        encoding="utf-8",
    )
    payload = {
        "rules": [
            {
                "id": "core-no-api",
                "type": "import_direction",
                "scope": "memgentic/**",
                "targets": ["memgentic_api"],
                "message": "core must not import api",
                "source": "CLAUDE.md",
                "snippet": "Core must never import memgentic_api",
                "confidence": 0.95,
            },
            {
                "id": "ban-requests",
                "type": "banned_import",
                "scope": "**",
                "targets": ["requests"],
                "message": "ban requests",
                "source": "CLAUDE.md",
                "snippet": "Ban the requests library",
                "confidence": 0.85,
            },
            {
                "id": "be-nice",
                "type": "write_clean_code",  # invalid → dropped
                "scope": "**",
                "targets": ["everything"],
                "message": "be nice",
                "source": "CLAUDE.md",
                "snippet": "",
                "confidence": 0.99,
            },
        ]
    }
    fake = _FakeClient(payload)
    result = asyncio.run(suggest_rules(tmp_path, llm_client=fake))

    assert result.total_proposed == 2  # the bogus type was dropped
    ids = {r.id for r in result.rules}
    assert ids == {"core-no-api", "ban-requests"}
    assert "CLAUDE.md" in result.sources_found
    assert any("write_clean_code" in w or "be-nice" in w for w in result.warnings)


def test_suggest_rules_no_sources_returns_empty(tmp_path):
    fake = _FakeClient({"rules": []})
    result = asyncio.run(suggest_rules(tmp_path, llm_client=fake))
    assert result.total_proposed == 0
    assert result.sources_found == []
    assert any("no prose rule files" in w for w in result.warnings)


def test_suggest_rules_llm_returns_none(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("ban requests", encoding="utf-8")
    fake = _FakeClient(None)  # simulates unparseable/empty LLM response
    result = asyncio.run(suggest_rules(tmp_path, llm_client=fake))
    assert result.total_proposed == 0
    assert any("no usable rules" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# CLI — clean exit 2 when no LLM provider is available
# ---------------------------------------------------------------------------


def test_cli_suggest_exit_2_when_no_provider(tmp_path, monkeypatch):
    """When the LLM client factory can't reach a provider, the CLI must exit 2
    with the clean, actionable message (no stack trace)."""
    from memgentic.cli import main

    (tmp_path / "CLAUDE.md").write_text("ban requests", encoding="utf-8")

    def _boom(settings, model):
        raise SuggestUnavailableError(
            "guard suggest needs the [intelligence] extra and a configured LLM provider"
        )

    monkeypatch.setattr(suggest, "_make_llm_client", _boom)

    res = CliRunner().invoke(main, ["guard", "suggest", "--repo", str(tmp_path)])
    assert res.exit_code == 2
    assert "[intelligence] extra" in res.stderr
    # stdout must NOT contain a YAML draft on the error path
    assert "PROPOSED by guard suggest" not in res.stdout


def test_cli_suggest_success_renders_yaml(tmp_path, monkeypatch):
    """Happy path: CLI prints the advisory YAML on stdout and exits 0."""
    from memgentic.cli import main

    (tmp_path / "CLAUDE.md").write_text("Core must never import memgentic_api", encoding="utf-8")

    async def _fake_suggest(repo, *, settings=None, model=None):
        valid, future, _w = validate_proposals(
            [
                {
                    "id": "core-no-api",
                    "type": "import_direction",
                    "scope": "memgentic/**",
                    "targets": ["memgentic_api"],
                    "message": "core must not import api",
                    "source": "CLAUDE.md",
                    "confidence": 0.95,
                }
            ]
        )
        return SuggestResult(
            rules=valid,
            future_rules=future,
            sources_found=["CLAUDE.md"],
            warnings=[],
            model_used="fake",
        )

    monkeypatch.setattr(suggest, "suggest_rules", _fake_suggest)

    res = CliRunner().invoke(main, ["guard", "suggest", "--repo", str(tmp_path)])
    assert res.exit_code == 0
    assert "PROPOSED by guard suggest" in res.output
    assert "core-no-api" in res.output


def test_collected_source_dataclass_roundtrip():
    s = CollectedSource(path="CLAUDE.md", text="hello")
    assert s.path == "CLAUDE.md"
    assert s.text == "hello"


# ---------------------------------------------------------------------------
# Loose JSON fallback parser (small-model robustness)
# ---------------------------------------------------------------------------


def test_parse_loose_json_wrapped_object():
    text = '{"rules": [{"id": "a", "type": "banned_import", "targets": ["x"]}]}'
    rules = suggest._parse_loose_json_rules(text)
    assert len(rules) == 1
    assert rules[0]["id"] == "a"


def test_parse_loose_json_bare_array():
    # Gemma's observed failure mode: a bare top-level array.
    text = (
        '[{"id": "a", "type": "banned_import", "targets": ["x"]}, '
        '{"id": "b", "type": "banned_dependency", "targets": ["y"]}]'
    )
    rules = suggest._parse_loose_json_rules(text)
    assert len(rules) == 2


def test_parse_loose_json_with_code_fence_and_prose():
    text = (
        "Here are the rules I found:\n"
        "```json\n"
        '{"rules": [{"id": "a", "type": "banned_import", "targets": ["x"]}]}\n'
        "```\n"
        "Hope this helps!"
    )
    rules = suggest._parse_loose_json_rules(text)
    assert len(rules) == 1


def test_parse_loose_json_garbage_returns_empty():
    assert suggest._parse_loose_json_rules("not json at all") == []
    assert suggest._parse_loose_json_rules("") == []


class _FallbackClient:
    """Fake client whose structured call fails but plain generate() works —
    mimics gemma4 returning a bare array the json_schema path rejects."""

    available = True
    _provider_kind = "ollama"

    def __init__(self, plain_text):
        self._plain = plain_text

    async def generate_structured(self, prompt, schema):
        return None  # structured path "fails"

    async def generate(self, prompt):
        return self._plain


def test_suggest_rules_uses_plain_json_fallback(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Ban the requests library", encoding="utf-8")
    bare_array = (
        '[{"id": "ban-requests", "type": "banned_import", "scope": "**", '
        '"targets": ["requests"], "message": "ban requests", '
        '"source": "CLAUDE.md", "snippet": "Ban the requests library", '
        '"confidence": 0.9}]'
    )
    client = _FallbackClient(bare_array)
    result = asyncio.run(suggest_rules(tmp_path, llm_client=client))

    assert result.total_proposed == 1
    assert result.rules[0].id == "ban-requests"
