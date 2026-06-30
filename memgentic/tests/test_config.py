"""Config flag defaults — recall-surface settings."""

from __future__ import annotations

from memgentic.config import MemgenticSettings


def test_distilled_recall_surface_defaults_off(tmp_path):
    """The distilled recall surface must be OFF until the eval harness confirms it."""
    s = MemgenticSettings(data_dir=tmp_path / "d")
    assert s.enable_distilled_recall_surface is False
