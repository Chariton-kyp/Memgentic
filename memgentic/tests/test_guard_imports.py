"""Tests for the banned-import guard check."""
from memgentic.guard.checks.imports import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(id="ban-httpx", type="banned_import", targets=["httpx"], message="no httpx")


def _g(blobs):
    return lambda p: blobs.get(p)


def test_fires_on_real_import():
    df = DiffFile(path="a.py", added_lines={1: "import httpx"})
    assert len(check(RULE, [df], _g({"a.py": "import httpx\n"}))) == 1


def test_indented_function_body_import_fires():
    src = "def f():\n    import httpx\n    return 1\n"
    df = DiffFile(path="a.py", added_lines={2: "    import httpx"})
    assert len(check(RULE, [df], _g({"a.py": src}))) == 1


def test_no_fp_in_comment_string_or_test_file():
    src = "# import httpx\nx = 'import httpx'\n"
    df = DiffFile(path="a.py", added_lines={1: "# import httpx", 2: "x = 'import httpx'"})
    assert check(RULE, [df], _g({"a.py": src})) == []
    dft = DiffFile(path="tests/test_a.py", added_lines={1: "import httpx"})
    assert check(RULE, [dft], _g({"tests/test_a.py": "import httpx\n"})) == []


def test_no_fp_in_optional_import_guard():
    src = "try:\n    import httpx\nexcept ImportError:\n    httpx = None\n"
    df = DiffFile(path="a.py", added_lines={2: "    import httpx"})
    assert check(RULE, [df], _g({"a.py": src})) == []


def test_no_fp_in_tuple_import_error_guard():
    src = "try:\n    import httpx\nexcept (ImportError, OSError):\n    httpx = None\n"
    df = DiffFile(path="a.py", added_lines={2: "    import httpx"})
    assert check(RULE, [df], _g({"a.py": src})) == []


def test_syntactically_invalid_blob_degrades():
    df = DiffFile(path="a.py", added_lines={1: "import httpx"})
    assert check(RULE, [df], _g({"a.py": "def (:\n"})) == []


def test_respects_scope():
    rule = GuardRule(id="ban", type="banned_import", scope="pkg/**", targets=["httpx"], message="x")
    assert len(check(rule, [DiffFile(path="pkg/a.py", added_lines={1: "import httpx"})],
                     _g({"pkg/a.py": "import httpx\n"}))) == 1
    assert check(rule, [DiffFile(path="other/b.py", added_lines={1: "import httpx"})],
                 _g({"other/b.py": "import httpx\n"})) == []


# ---------------------------------------------------------------------------
# BUG A: base-side check — pre-existing banned imports must not re-fire
# ---------------------------------------------------------------------------

def test_no_fire_when_banned_import_already_in_base():
    """A banned import that was already in base (just reordered) must NOT fire."""
    df = DiffFile(path="a.py", added_lines={1: "import httpx"})
    new = _g({"a.py": "import httpx\nimport os\n"})
    base = _g({"a.py": "import os\nimport httpx\n"})
    assert check(RULE, [df], new, base_blob_getter=base) == []


def test_fires_when_banned_import_is_new_vs_base():
    """A banned import that did NOT exist in base must fire."""
    df = DiffFile(path="a.py", added_lines={2: "import httpx"})
    new = _g({"a.py": "import os\nimport httpx\n"})
    base = _g({"a.py": "import os\n"})
    assert len(check(RULE, [df], new, base_blob_getter=base)) == 1
