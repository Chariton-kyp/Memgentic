"""Unit tests for the adaptive token-budget resolver."""

from __future__ import annotations

import pytest

from memgentic.briefing.token_budget import (
    DEFAULT_MODEL_CONTEXT,
    MAX_HORIZON_MEMORIES,
    MODEL_CONTEXT_ENV_VAR,
    detect_model_context,
    estimate_tokens,
    resolve_budget,
)


class TestDetectModelContext:
    def test_default_when_no_override(self, monkeypatch):
        monkeypatch.delenv(MODEL_CONTEXT_ENV_VAR, raising=False)
        assert detect_model_context() == DEFAULT_MODEL_CONTEXT

    def test_explicit_override_wins(self, monkeypatch):
        monkeypatch.setenv(MODEL_CONTEXT_ENV_VAR, "50000")
        assert detect_model_context(override=200_000) == 200_000

    def test_env_var_applied(self, monkeypatch):
        monkeypatch.setenv(MODEL_CONTEXT_ENV_VAR, "16000")
        assert detect_model_context() == 16_000

    def test_invalid_env_var_falls_back(self, monkeypatch):
        monkeypatch.setenv(MODEL_CONTEXT_ENV_VAR, "not-a-number")
        assert detect_model_context() == DEFAULT_MODEL_CONTEXT

    def test_zero_env_var_falls_back(self, monkeypatch):
        monkeypatch.setenv(MODEL_CONTEXT_ENV_VAR, "0")
        assert detect_model_context() == DEFAULT_MODEL_CONTEXT

    def test_zero_override_falls_through(self, monkeypatch):
        monkeypatch.setenv(MODEL_CONTEXT_ENV_VAR, "50000")
        assert detect_model_context(override=0) == 50_000


class TestResolveBudget:
    def test_small_context_tight_horizon(self, monkeypatch):
        monkeypatch.delenv(MODEL_CONTEXT_ENV_VAR, raising=False)
        b = resolve_budget("T1", model_context=16_000)
        assert b.tokens == 400
        assert b.max_memories == 8

    def test_medium_context_standard_horizon(self, monkeypatch):
        monkeypatch.delenv(MODEL_CONTEXT_ENV_VAR, raising=False)
        b = resolve_budget("T1", model_context=128_000)
        assert b.tokens == 800
        assert b.max_memories == 15

    def test_large_context_generous_horizon(self, monkeypatch):
        monkeypatch.delenv(MODEL_CONTEXT_ENV_VAR, raising=False)
        b = resolve_budget("T1", model_context=1_000_000)
        assert b.tokens == 1500
        assert b.max_memories == MAX_HORIZON_MEMORIES

    def test_max_tokens_override_clamps_down(self):
        b = resolve_budget("T1", model_context=128_000, max_tokens=300)
        assert b.tokens == 300

    def test_max_tokens_override_cannot_exceed_ceiling(self):
        b = resolve_budget("T1", model_context=16_000, max_tokens=9999)
        assert b.tokens == 400  # tier ceiling wins over caller request

    def test_zero_max_tokens_ignored(self):
        b = resolve_budget("T1", model_context=128_000, max_tokens=0)
        assert b.tokens == 800

    def test_persona_budget_constant(self):
        small = resolve_budget("T0", model_context=16_000)
        large = resolve_budget("T0", model_context=1_000_000)
        assert small.tokens == large.tokens  # T0 is identity-sized

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError):
            resolve_budget("T9")  # type: ignore[arg-type]

    @pytest.mark.parametrize("tier", ["T0", "T1", "T2", "T3", "T4"])
    def test_each_tier_has_non_zero_budget(self, tier):
        b = resolve_budget(tier)  # type: ignore[arg-type]
        assert b.tokens > 0


class TestEstimateTokens:
    def test_empty_string_is_zero(self):
        assert estimate_tokens("") == 0

    def test_short_string_rounds_up(self):
        # 10 chars → (10+3)//4 = 3 tokens (conservative)
        assert estimate_tokens("helloworld") == 3

    def test_roughly_matches_word_count_for_long_text(self):
        text = " ".join(["token"] * 100)
        # 100 words x 6 chars ≈ 600 chars → ~150 tokens
        tokens = estimate_tokens(text)
        assert 100 <= tokens <= 200

    def test_never_zero_for_non_empty(self):
        assert estimate_tokens("a") == 1
