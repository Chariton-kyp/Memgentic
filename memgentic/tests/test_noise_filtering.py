"""Tests for content-value noise filtering."""

from __future__ import annotations

from memgentic.processing.heuristics import is_noise


class TestNoise:
    def test_empty_string_is_noise(self):
        assert is_noise("") is True

    def test_whitespace_is_noise(self):
        assert is_noise("    \n\n  ") is True

    def test_very_short_text_is_noise(self):
        assert is_noise("ok") is True

    def test_pleasantry_is_noise(self):
        assert is_noise("Sure, thanks!") is True

    def test_short_acknowledgment_is_noise(self):
        assert is_noise("Got it, understood.") is True

    def test_let_me_prefix_is_noise(self):
        assert is_noise("Let me check that for you") is True

    def test_looking_at_prefix_is_noise(self):
        assert is_noise("Looking at the file now") is True

    def test_stack_trace_is_noise(self):
        trace = "\n".join(
            [
                "Traceback (most recent call last):",
                '  File "main.py", line 10, in <module>',
                '  File "lib.py", line 22, in helper',
                '  File "lib.py", line 33, in helper2',
                '  File "lib.py", line 44, in helper3',
                '  File "lib.py", line 55, in helper4',
                "ValueError: bad input",
            ]
        )
        assert is_noise(trace) is True

    def test_hex_dump_is_noise(self):
        dump = "00 11 22 33 44 55 66 77 88 99 aa bb cc dd ee ff " * 30
        assert is_noise(dump) is True


class TestNotNoise:
    def test_knowledge_is_not_noise(self):
        assert is_noise("We decided to use PostgreSQL because of JSONB support") is False

    def test_long_decision_is_not_noise(self):
        text = (
            "After reviewing the options we agreed on Qdrant for vector storage "
            "because the file mode lets us avoid running a server."
        )
        assert is_noise(text) is False

    def test_code_block_is_not_noise(self):
        code = "def calculate(items):\n    return sum(item.value for item in items)"
        assert is_noise(code) is False

    def test_factual_statement_not_noise(self):
        assert is_noise("FastAPI is built on Starlette and supports async natively") is False
