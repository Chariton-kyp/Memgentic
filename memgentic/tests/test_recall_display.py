"""Recall display prefers the distilled snippet; expand stays verbatim."""

from __future__ import annotations

from memgentic.config import settings as _settings
from memgentic.mcp.server import _format_memory_md
from memgentic.processing.utils import recall_display_text


def test_recall_display_text_prefers_distilled_when_enabled():
    assert recall_display_text("verbatim", "distilled", enabled=True) == "distilled"


def test_recall_display_text_uses_content_when_disabled():
    assert recall_display_text("verbatim", "distilled", enabled=False) == "verbatim"


def test_recall_display_text_falls_back_when_distilled_missing():
    assert recall_display_text("verbatim", None, enabled=True) == "verbatim"
    assert recall_display_text("verbatim", "", enabled=True) == "verbatim"

DISTILLED = "Deployed v2 to production at 14:00 UTC."
VERBATIM = (
    "Human: ok so there is a lot of noise here, anyway we deployed v2\n"
    "Assistant: done, rolled it out to production at 14:00 UTC"
)


def _payload(distilled: str | None = DISTILLED) -> dict:
    return {
        "id": "m1",
        "content": VERBATIM,
        "distilled": distilled,
        "content_type": "fact",
        "platform": "claude_code",
        "created_at": "2026-06-30T00:00:00",
        "topics": [],
    }


def test_preview_prefers_distilled_when_flag_on(monkeypatch):
    monkeypatch.setattr(_settings, "enable_distilled_recall_surface", True)
    out = _format_memory_md(_payload(), 0.9, detail="preview")
    assert DISTILLED in out
    assert "lot of noise" not in out


def test_index_prefers_distilled_when_flag_on(monkeypatch):
    monkeypatch.setattr(_settings, "enable_distilled_recall_surface", True)
    out = _format_memory_md(_payload(), None, detail="index")
    assert "Deployed v2" in out
    assert "lot of noise" not in out


def test_full_detail_stays_verbatim(monkeypatch):
    monkeypatch.setattr(_settings, "enable_distilled_recall_surface", True)
    out = _format_memory_md(_payload(), 0.9, detail="full")
    # expand / full detail must always return the verbatim source-of-truth
    assert "lot of noise" in out


def test_flag_off_uses_verbatim_content(monkeypatch):
    monkeypatch.setattr(_settings, "enable_distilled_recall_surface", False)
    out = _format_memory_md(_payload(), 0.9, detail="preview")
    assert "lot of noise" in out
    assert DISTILLED not in out


def test_missing_distilled_falls_back_to_content(monkeypatch):
    monkeypatch.setattr(_settings, "enable_distilled_recall_surface", True)
    out = _format_memory_md(_payload(distilled=None), 0.9, detail="preview")
    assert "lot of noise" in out
