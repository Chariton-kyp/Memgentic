"""The distill prompt carries mem0-style detail-preservation rules.

These are cheap string assertions on the built prompt; the LLM's actual output
is exercised by integration tests, not here.
"""

from __future__ import annotations

from memgentic.processing.intelligence import _build_distill_prompt


def test_prompt_demands_identifier_and_number_preservation():
    low = _build_distill_prompt("We bumped pyo3 to 0.27 in Cargo.toml.", "fact").lower()
    assert "identifier" in low
    assert "number" in low
    assert "code" in low


def test_prompt_demands_coreference_resolution():
    low = _build_distill_prompt("It crashed because of the KV cache.", "bug_fix").lower()
    assert "pronoun" in low or "coreference" in low
    assert "entit" in low  # "entity" / "entities"


def test_prompt_keeps_decision_with_rationale():
    low = _build_distill_prompt("We chose Qdrant because of local mode.", "decision").lower()
    assert "rationale" in low or "reason" in low
    assert "decision" in low


def test_prompt_grounds_relative_time():
    low = _build_distill_prompt("We shipped it yesterday.", "fact").lower()
    assert "relative time" in low or "absolute" in low


def test_prompt_includes_content_and_type_and_keeps_json_contract():
    content = "Deployed v2 to production at 14:00 UTC."
    p = _build_distill_prompt(content, "fact")
    assert "Content type: fact" in p
    assert content in p
    # Output contract must stay identical (facts / is_valuable / value_score).
    assert '"facts"' in p
    assert "is_valuable" in p
    assert "value_score" in p


def test_prompt_truncation_cap_raised_above_2000():
    content = "x" * 3000  # over the old 2000-char cap, under the new one
    p = _build_distill_prompt(content, "fact")
    assert ("x" * 2500) in p  # more than 2000 chars of content survived truncation
