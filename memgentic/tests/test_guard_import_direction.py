"""Tests for the import-direction guard check."""
from memgentic.guard.checks.import_direction import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

RULE = GuardRule(
    id="core-import-direction", type="import_direction", scope="memgentic/**",
    targets=["memgentic_api", "dashboard"], message="core must not import api/dashboard",
)


def _getter(blobs):
    return lambda path: blobs.get(path)


def test_fires_on_forbidden_import_in_scope():
    df = DiffFile(path="memgentic/x.py", added_lines={2: "import memgentic_api"})
    blobs = {"memgentic/x.py": "import os\nimport memgentic_api\n"}
    out = check(RULE, [df], _getter(blobs))
    assert len(out) == 1
    assert out[0].file == "memgentic/x.py" and out[0].line == 2


def test_silent_when_out_of_scope():
    df = DiffFile(path="tests/x.py", added_lines={1: "import memgentic_api"})
    blobs = {"tests/x.py": "import memgentic_api\n"}
    assert check(RULE, [df], _getter(blobs)) == []


def test_silent_when_import_not_in_added_lines():
    df = DiffFile(path="memgentic/x.py", added_lines={3: "x = 1"})
    blobs = {"memgentic/x.py": "import memgentic_api\n\nx = 1\n"}
    assert check(RULE, [df], _getter(blobs)) == []


def test_submodule_and_from_import_match():
    df = DiffFile(path="memgentic/y.py", added_lines={1: "from memgentic_api.routes import r"})
    blobs = {"memgentic/y.py": "from memgentic_api.routes import r\n"}
    assert len(check(RULE, [df], _getter(blobs))) == 1


def test_multi_name_import_fires():
    df = DiffFile(path="memgentic/x.py", added_lines={1: "import os, memgentic_api"})
    assert len(check(RULE, [df], _getter({"memgentic/x.py": "import os, memgentic_api\n"}))) == 1


def test_prefix_boundary_not_matched():
    df = DiffFile(path="memgenticextensions/x.py", added_lines={1: "import memgentic_api"})
    assert check(RULE, [df], _getter({"memgenticextensions/x.py": "import memgentic_api\n"})) == []


def test_silent_on_type_checking_import():
    src = ("from __future__ import annotations\nfrom typing import TYPE_CHECKING\n"
           "if TYPE_CHECKING:\n    import memgentic_api\n")
    df = DiffFile(path="memgentic/z.py", added_lines={4: "    import memgentic_api"})
    assert check(RULE, [df], _getter({"memgentic/z.py": src})) == []


def test_silent_on_typing_type_checking_attribute():
    src = "import typing\nif typing.TYPE_CHECKING:\n    import memgentic_api\n"
    df = DiffFile(path="memgentic/z.py", added_lines={3: "    import memgentic_api"})
    assert check(RULE, [df], _getter({"memgentic/z.py": src})) == []


def test_multiline_from_import_added_names_only():
    src = "from memgentic_api import (\n    a,\n    b,\n)\n"
    df = DiffFile(path="memgentic/x.py", added_lines={2: "    a,"})
    out = check(RULE, [df], _getter({"memgentic/x.py": src}))
    assert len(out) == 1
    assert out[0].line == 2


def test_fires_on_import_error_guarded_import():
    src = "try:\n    import memgentic_api\nexcept ImportError:\n    memgentic_api = None\n"
    df = DiffFile(path="memgentic/x.py", added_lines={2: "    import memgentic_api"})
    assert len(check(RULE, [df], _getter({"memgentic/x.py": src}))) == 1


def test_silent_in_test_file_even_in_scope():
    df = DiffFile(path="memgentic/tests/test_x.py", added_lines={1: "import memgentic_api"})
    assert check(RULE, [df], _getter({"memgentic/tests/test_x.py": "import memgentic_api\n"})) == []


def test_bom_blob_still_parsed():
    src = "﻿import memgentic_api\n"
    df = DiffFile(path="memgentic/memgentic/x.py", added_lines={1: "import memgentic_api"})
    assert len(check(RULE, [df], _getter({"memgentic/memgentic/x.py": src}))) == 1


def test_else_branch_of_type_checking_not_suppressed():
    src = ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import os\n"
           "else:\n    import memgentic_api\n")
    df = DiffFile(path="memgentic/memgentic/x.py", added_lines={5: "    import memgentic_api"})
    assert len(check(RULE, [df], _getter({"memgentic/memgentic/x.py": src}))) == 1


# ---------------------------------------------------------------------------
# BUG A: base-side check — pre-existing forbidden imports must not re-fire
# ---------------------------------------------------------------------------

def test_no_fire_when_forbidden_import_already_in_base():
    """An import that was already in base (just reordered) must NOT fire."""
    df = DiffFile(path="memgentic/memgentic/x.py", added_lines={1: "import memgentic_api"})
    new = _getter({"memgentic/memgentic/x.py": "import memgentic_api\nimport os\n"})
    base = _getter({"memgentic/memgentic/x.py": "import os\nimport memgentic_api\n"})
    assert check(RULE, [df], new, base_blob_getter=base) == []


def test_fires_when_forbidden_import_is_new_vs_base():
    """An import that did NOT exist in base must fire."""
    df = DiffFile(path="memgentic/memgentic/x.py", added_lines={2: "import memgentic_api"})
    new = _getter({"memgentic/memgentic/x.py": "import os\nimport memgentic_api\n"})
    base = _getter({"memgentic/memgentic/x.py": "import os\n"})
    assert len(check(RULE, [df], new, base_blob_getter=base)) == 1
