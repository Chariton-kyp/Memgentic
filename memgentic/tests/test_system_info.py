"""Tests for v0.5.0 #1 — tier recommendation from detected hardware."""

from __future__ import annotations

from memgentic.system_info import (
    GpuInfo,
    RamInfo,
    Tier,
    recommend_tier,
)


def _gpu(vram_gb: float) -> GpuInfo:
    mb = int(vram_gb * 1024)
    return GpuInfo(
        name="fake",
        vram_total_mb=mb,
        vram_used_mb=0,
        vram_free_mb=mb,
        utilization_pct=0,
    )


def _ram(gb: float) -> RamInfo:
    mb = int(gb * 1024)
    return RamInfo(total_mb=mb, available_mb=mb)


class TestRecommendTier:
    def test_workstation_tier(self):
        rec = recommend_tier(_gpu(12), _ram(64), cpu_cores=12)
        assert rec.tier == Tier.WORKSTATION
        assert rec.embedding_model == "qwen3-embedding:0.6b"
        assert rec.embedding_dimensions == 768
        assert rec.local_llm_model == "gemma4:e4b"

    def test_power_tier(self):
        rec = recommend_tier(_gpu(8), _ram(32), cpu_cores=8)
        assert rec.tier == Tier.POWER
        assert rec.local_llm_model == "gemma4:e2b"

    def test_quality_tier_no_gpu(self):
        rec = recommend_tier(None, _ram(16), cpu_cores=6)
        assert rec.tier == Tier.QUALITY
        assert rec.embedding_model == "qwen3-embedding:0.6b"
        assert rec.local_llm_model == "gemma3:1b"
        assert rec.multilingual is True

    def test_balanced_tier_no_gpu(self):
        # 7.5 GB RAM (between MINIMUM's 4 and QUALITY's 15 thresholds)
        rec = recommend_tier(None, _ram(7.5), cpu_cores=4)
        assert rec.tier == Tier.BALANCED
        assert rec.embedding_model == "embeddinggemma:300m"
        assert rec.local_llm_model == "gemma3:1b"
        assert rec.multilingual is True

    def test_minimum_tier_no_gpu_low_ram(self):
        rec = recommend_tier(None, _ram(4), cpu_cores=2, multilingual=False)
        assert rec.tier == Tier.MINIMUM
        assert rec.embedding_model == "granite-embedding:30m"
        assert rec.embedding_dimensions == 384
        assert rec.local_llm_model == "gemma3:270m"
        assert rec.multilingual is False
        # No multilingual note when caller didn't ask for it.
        assert not any("Multilingual" in n for n in rec.notes)

    def test_minimum_tier_multilingual_note(self):
        """Low-RAM + multilingual request → Tier 0 with an explicit note."""
        rec = recommend_tier(None, _ram(4), cpu_cores=2, multilingual=True)
        assert rec.tier == Tier.MINIMUM
        assert any("Multilingual" in n for n in rec.notes)

    def test_ram_autodetect_failure_falls_back_to_balanced(self):
        rec = recommend_tier(None, _ram(0), cpu_cores=4)
        assert rec.tier == Tier.BALANCED
        assert any("auto-detect failed" in n for n in rec.notes)

    def test_weak_gpu_uses_cpu_tier(self):
        """A 2 GB VRAM GPU is too small; tier decided by RAM alone."""
        rec = recommend_tier(_gpu(2), _ram(7.5), cpu_cores=4)
        assert rec.tier == Tier.BALANCED
        assert rec.local_llm_model == "gemma3:1b"

    def test_ordering(self):
        """Tier enum ordering matches intended hardware ladder."""
        assert Tier.MINIMUM < Tier.BALANCED < Tier.QUALITY < Tier.POWER < Tier.WORKSTATION
