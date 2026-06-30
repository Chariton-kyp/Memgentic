"""Grounding gate — distilled text must be lexically anchored in its source.

Guards against promoting a hallucinated distillation to the recall surface.
"""

from __future__ import annotations

from memgentic.processing._grounding import is_grounded


def test_grounded_facts_pass():
    source = "Human: We deployed v2 to production at 14:00 UTC after testing."
    distilled = "Deployed v2 to production at 14:00 UTC."
    assert is_grounded(distilled, source) is True


def test_hallucinated_facts_fail():
    source = "Human: We deployed v2 to production today."
    distilled = "The capital of France is Paris and the secret API key is XYZ."
    assert is_grounded(distilled, source) is False


def test_empty_distilled_is_not_grounded():
    source = "anything at all here"
    assert is_grounded("", source) is False
    assert is_grounded("   ", source) is False


def test_overlap_below_threshold_fails():
    source = "alpha only"
    distilled = "alpha beta gamma delta epsilon"  # 1/5 overlap < 0.5
    assert is_grounded(distilled, source) is False


def test_stopwords_do_not_inflate_overlap():
    # Only stopwords overlap; no content token is anchored → not grounded.
    source = "the and to of is in on at"
    distilled = "Kubernetes autoscaling and the retry budget"
    assert is_grounded(distilled, source) is False
