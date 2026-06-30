"""Round-trip persistence for the nullable Memory.distilled recall surface."""

from __future__ import annotations

from memgentic.models import ContentType, Memory


async def test_distilled_round_trips(metadata_store, sample_source):
    """A populated distilled column survives store → read, content stays verbatim."""
    m = Memory(
        content="Human: deploy v2 to prod\nAssistant: done, rolled out at 14:00 UTC",
        content_type=ContentType.FACT,
        source=sample_source,
        distilled="Deployed v2 to production at 14:00 UTC.",
    )
    await metadata_store.save_memory(m)

    got = await metadata_store.get_memory(m.id)
    assert got is not None
    assert got.distilled == "Deployed v2 to production at 14:00 UTC."
    # content remains the immutable verbatim source-of-truth
    assert got.content == m.content


async def test_distilled_defaults_none(metadata_store, sample_source):
    """Rows written without a distilled value read back as None (legacy/raw rows)."""
    m = Memory(content="just a verbatim turn, no distillation", source=sample_source)
    await metadata_store.save_memory(m)

    got = await metadata_store.get_memory(m.id)
    assert got is not None
    assert got.distilled is None
