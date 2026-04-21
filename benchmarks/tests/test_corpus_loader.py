"""Tests for the LongMemEval corpus loader.

We assert the happy-path parse against a tiny fixture plus a handful of
edge cases (missing file, malformed record, string turns). The goal is
regression detection for upstream schema drift, not full coverage of
every LongMemEval release format.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.lib.corpus_loader import CorpusLoaderError, load_longmemeval
from benchmarks.lib.harness import BenchmarkQuery, CorpusSession

FIXTURE = Path(__file__).parent / "fixtures" / "longmemeval_tiny.json"


class TestLoadLongmemevalHappyPath:
    def test_returns_sessions_and_queries(self) -> None:
        sessions, queries = load_longmemeval(FIXTURE)
        assert isinstance(sessions, list)
        assert isinstance(queries, list)

    def test_sessions_are_deduplicated(self) -> None:
        sessions, _ = load_longmemeval(FIXTURE)
        ids = [s.session_id for s in sessions]
        assert len(ids) == len(set(ids)), f"Duplicate sessions: {ids}"

    def test_all_fixture_sessions_loaded(self) -> None:
        sessions, _ = load_longmemeval(FIXTURE)
        ids = {s.session_id for s in sessions}
        # The fixture declares 4 unique session IDs.
        assert ids == {"s-alpha", "s-beta", "s-gamma", "s-delta"}

    def test_sessions_have_non_empty_chunks(self) -> None:
        sessions, _ = load_longmemeval(FIXTURE)
        for session in sessions:
            assert isinstance(session, CorpusSession)
            assert session.chunks, f"Session {session.session_id} has no chunks"

    def test_queries_carry_gold_ids(self) -> None:
        _, queries = load_longmemeval(FIXTURE)
        by_id = {q.id: q for q in queries}
        assert by_id["q-001"].gold == {"s-alpha"}
        assert by_id["q-002"].gold == {"s-delta"}

    def test_queries_expose_category(self) -> None:
        _, queries = load_longmemeval(FIXTURE)
        assert all(q.category == "single-session-user" for q in queries)

    def test_queries_are_benchmarkquery_instances(self) -> None:
        _, queries = load_longmemeval(FIXTURE)
        for query in queries:
            assert isinstance(query, BenchmarkQuery)
            assert query.text
            assert query.gold


class TestLoadLongmemevalEdgeCases:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CorpusLoaderError, match="not found"):
            load_longmemeval(tmp_path / "does_not_exist.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(CorpusLoaderError, match="parse"):
            load_longmemeval(path)

    def test_top_level_dict_records_envelope(self, tmp_path: Path) -> None:
        # Some upstream releases wrap the list in a {"records": [...]} dict.
        payload = json.loads(FIXTURE.read_text())
        wrapped = {"records": payload}
        path = tmp_path / "wrapped.json"
        path.write_text(json.dumps(wrapped))

        _, queries = load_longmemeval(path)
        assert {q.id for q in queries} == {"q-001", "q-002"}

    def test_length_mismatch_raises(self, tmp_path: Path) -> None:
        bad = [
            {
                "question_id": "q-bad",
                "question": "mismatched arrays",
                "haystack_session_ids": ["s-1", "s-2"],
                "haystack_sessions": [[{"role": "user", "content": "only one session"}]],
                "answer_session_ids": ["s-1"],
            }
        ]
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(CorpusLoaderError, match="mismatch"):
            load_longmemeval(path)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        bad = [{"question_id": "q-bad"}]  # no question / haystack fields
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(CorpusLoaderError, match="missing required field"):
            load_longmemeval(path)

    def test_string_turns_are_accepted(self, tmp_path: Path) -> None:
        payload = [
            {
                "question_id": "q-str",
                "question": "Plain string turns",
                "haystack_session_ids": ["s-str"],
                "haystack_sessions": [["user-only string turn"]],
                "answer_session_ids": ["s-str"],
            }
        ]
        path = tmp_path / "strings.json"
        path.write_text(json.dumps(payload))
        sessions, queries = load_longmemeval(path)
        assert len(sessions) == 1
        assert sessions[0].chunks[0].content == "user-only string turn"
        assert queries[0].gold == {"s-str"}
