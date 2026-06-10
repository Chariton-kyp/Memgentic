"""Tests for the guard git-diff parser."""

from memgentic.guard.diff import parse_diff

SAMPLE = """diff --git a/memgentic/x.py b/memgentic/x.py
index 111..222 100644
--- a/memgentic/x.py
+++ b/memgentic/x.py
@@ -1,2 +1,3 @@
 import os
+import memgentic_api
 import sys
diff --git a/data.bin b/data.bin
index 333..444 100644
Binary files a/data.bin and b/data.bin differ
"""


def test_parse_added_line_numbers_and_routing():
    files = {f.path: f for f in parse_diff(SAMPLE)}
    x = files["memgentic/x.py"]
    # 'import memgentic_api' is the 2nd new-side line
    assert x.added_lines == {2: "import memgentic_api"}
    assert files["data.bin"].is_binary is True


def test_crlf_stripped():
    diff = "diff --git a/p.py b/p.py\n--- a/p.py\n+++ b/p.py\n@@ -0,0 +1 @@\n+import x\r\n"
    f = parse_diff(diff)[0]
    assert f.added_lines == {1: "import x"}  # trailing \r removed


def test_dev_null_marks_deleted():
    diff = (
        "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-import x\n"
    )
    f = parse_diff(diff)[0]
    assert f.path == "gone.py" and f.is_deleted is True


def test_rename_path_is_new_side():
    diff = (
        "diff --git a/old.py b/new.py\nrename from old.py\nrename to new.py\n"
        "--- a/old.py\n+++ b/new.py\n@@ -1,0 +1 @@\n+import y\n"
    )
    f = parse_diff(diff)[0]
    assert f.path == "new.py" and f.added_lines == {1: "import y"}


def test_multi_hunk_resets_new_lineno():
    diff = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -1 +1 @@\n+import a\n@@ -10 +20 @@\n+import b\n"
    )
    f = parse_diff(diff)[0]
    assert f.added_lines == {1: "import a", 20: "import b"}


def test_deleted_lines_do_not_advance_new_counter():
    diff = (
        "diff --git a/d.py b/d.py\n--- a/d.py\n+++ b/d.py\n"
        "@@ -1,3 +1,1 @@\n-import a\n-import b\n+import c\n"
    )
    f = parse_diff(diff)[0]
    assert f.added_lines == {1: "import c"}


def test_new_file_not_marked_deleted():
    diff = "diff --git a/n.py b/n.py\n--- /dev/null\n+++ b/n.py\n@@ -0,0 +1 @@\n+import z\n"
    f = parse_diff(diff)[0]
    assert f.path == "n.py" and f.is_deleted is False and f.added_lines == {1: "import z"}


# ---------------------------------------------------------------------------
# ITEM 2 — BOM stripped from added lines
# ---------------------------------------------------------------------------


def test_bom_stripped_from_added_lines():
    diff = "diff --git a/p.py b/p.py\n--- a/p.py\n+++ b/p.py\n@@ -0,0 +1 @@\n+﻿import x\n"
    f = parse_diff(diff)[0]
    assert f.added_lines == {1: "import x"}
