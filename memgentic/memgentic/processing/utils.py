"""Shared processing utilities."""

# Try to use the Rust-native implementation (10-20x faster).
try:
    from memgentic_native.textproc import text_overlap as _native_text_overlap

    _USE_NATIVE = True
except ImportError:
    _USE_NATIVE = False


def text_overlap(text_a: str, text_b: str) -> float:
    """Compute word-level Jaccard similarity between two texts.

    Used by contradiction detection and consolidation to compare text content.

    Returns:
        Jaccard index (0.0 to 1.0). Returns 0.0 if either text is empty.

    Uses Rust native implementation when available (10-20x faster).
    """
    if _USE_NATIVE:
        return _native_text_overlap(text_a, text_b)
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
