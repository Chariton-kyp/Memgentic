"""Tests for C# `using`-directive support in the banned_import check."""

from __future__ import annotations

from memgentic.guard.checks import imports as imports_check
from memgentic.guard.checks.csharp_using import extract_using_namespaces
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule

# ---------------------------------------------------------------------------
# Unit tests for the using-directive extractor
# ---------------------------------------------------------------------------


def test_extract_plain_using():
    assert extract_using_namespaces("using MediatR;") == ["MediatR"]


def test_extract_dotted_namespace():
    assert extract_using_namespaces("using System.Text.Json;") == ["System.Text.Json"]


def test_extract_static_using():
    assert extract_using_namespaces("using static System.Math;") == ["System.Math"]


def test_extract_global_using():
    assert extract_using_namespaces("global using MediatR;") == ["MediatR"]


def test_extract_global_static_using():
    assert extract_using_namespaces("global using static System.Math;") == ["System.Math"]


def test_extract_alias_using_matches_right_side():
    assert extract_using_namespaces("using Json = System.Text.Json;") == ["System.Text.Json"]


def test_extract_leading_whitespace_ok():
    assert extract_using_namespaces("    using MediatR;") == ["MediatR"]


def test_extract_using_var_not_matched():
    assert extract_using_namespaces("using var x = new Foo();") == []


def test_extract_using_statement_paren_not_matched():
    assert extract_using_namespaces("using (var x = new Foo())") == []


def test_extract_using_declaration_not_matched():
    # C#8 using declaration: `using FileStream fs = ...;`
    assert extract_using_namespaces("using FileStream fs = File.Open(p);") == []


def test_extract_commented_line_not_matched():
    assert extract_using_namespaces("// using MediatR;") == []
    assert extract_using_namespaces("/* using MediatR; */") == []
    assert extract_using_namespaces(" * using MediatR;") == []


def test_extract_string_content_not_matched():
    assert extract_using_namespaces('"using MediatR;"') == []


def test_extract_non_using_line():
    assert extract_using_namespaces("public class Foo { }") == []


# ---------------------------------------------------------------------------
# Integration tests through the banned_import check
# ---------------------------------------------------------------------------


def _rule(targets, scope="**", message="banned using", severity="error"):
    return GuardRule(
        id="no-using",
        type="banned_import",
        scope=scope,
        targets=targets,
        message=message,
        severity=severity,
    )


def _blob_factory(blobs):
    def getter(path):
        return blobs.get(path)

    return getter


def test_cs_banned_using_fires():
    rule = _rule(["MediatR"])
    blob = "using MediatR;\npublic class C { }\n"
    df = DiffFile(path="src/Handler.cs", added_lines={1: "using MediatR;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/Handler.cs": blob}))
    assert len(out) == 1
    assert out[0].file == "src/Handler.cs"
    assert out[0].line == 1
    assert out[0].severity == "error"


def test_cs_banned_using_prefix_match():
    """target MediatR catches using MediatR.Extensions.X."""
    rule = _rule(["MediatR"])
    blob = "using MediatR.Extensions.Microsoft.DependencyInjection;\n"
    df = DiffFile(
        path="src/Reg.cs",
        added_lines={1: "using MediatR.Extensions.Microsoft.DependencyInjection;"},
    )
    out = imports_check.check(rule, [df], _blob_factory({"src/Reg.cs": blob}))
    assert len(out) == 1


def test_cs_banned_using_no_false_prefix():
    """target MediatR must NOT match using MediatRFoo;."""
    rule = _rule(["MediatR"])
    blob = "using MediatRFoo;\n"
    df = DiffFile(path="src/X.cs", added_lines={1: "using MediatRFoo;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert out == []


def test_cs_banned_using_case_sensitive():
    """C# namespaces are case-sensitive: target MediatR must NOT match mediatr."""
    rule = _rule(["MediatR"])
    blob = "using mediatr;\n"
    df = DiffFile(path="src/X.cs", added_lines={1: "using mediatr;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert out == []


def test_cs_only_added_lines_count():
    """A banned using already in the blob but not on an added line is ignored."""
    rule = _rule(["MediatR"])
    blob = "using MediatR;\nusing System;\n"
    # only line 2 is added
    df = DiffFile(path="src/X.cs", added_lines={2: "using System;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert out == []


def test_cs_test_file_still_checked():
    """Unlike Python, C# rules apply in test files too (scope controls coverage)."""
    rule = _rule(["MediatR"])
    blob = "using MediatR;\n"
    df = DiffFile(path="tests/HandlerTests.cs", added_lines={1: "using MediatR;"})
    out = imports_check.check(rule, [df], _blob_factory({"tests/HandlerTests.cs": blob}))
    assert len(out) == 1


def test_cs_using_var_no_false_positive():
    rule = _rule(["MediatR"])
    blob = "using var scope = provider.CreateScope();\n"
    df = DiffFile(path="src/X.cs", added_lines={1: "using var scope = provider.CreateScope();"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert out == []


def test_cs_global_using_fires():
    rule = _rule(["MediatR"])
    blob = "global using MediatR;\n"
    df = DiffFile(path="src/GlobalUsings.cs", added_lines={1: "global using MediatR;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/GlobalUsings.cs": blob}))
    assert len(out) == 1


def test_cs_alias_using_fires_on_right_side():
    rule = _rule(["MediatR"])
    blob = "using M = MediatR;\n"
    df = DiffFile(path="src/X.cs", added_lines={1: "using M = MediatR;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert len(out) == 1


def test_cs_base_side_suppression():
    """If the same using already exists on the base side, skip it (pre-existing)."""
    rule = _rule(["MediatR"])
    new_blob = "using System;\nusing MediatR;\n"
    base_blob = "using MediatR;\n"
    # diff added line 2 (a reorder that re-added the MediatR using)
    df = DiffFile(path="src/X.cs", added_lines={2: "using MediatR;"})
    out = imports_check.check(
        rule,
        [df],
        _blob_factory({"src/X.cs": new_blob}),
        base_blob_getter=_blob_factory({"src/X.cs": base_blob}),
    )
    assert out == []


def test_cs_base_side_no_suppression_when_new():
    """A genuinely new using (absent from base) still fires even with base getter."""
    rule = _rule(["MediatR"])
    new_blob = "using System;\nusing MediatR;\n"
    base_blob = "using System;\n"
    df = DiffFile(path="src/X.cs", added_lines={2: "using MediatR;"})
    out = imports_check.check(
        rule,
        [df],
        _blob_factory({"src/X.cs": new_blob}),
        base_blob_getter=_blob_factory({"src/X.cs": base_blob}),
    )
    assert len(out) == 1


def test_cs_commented_using_no_false_positive():
    rule = _rule(["MediatR"])
    blob = "// using MediatR;\n"
    df = DiffFile(path="src/X.cs", added_lines={1: "// using MediatR;"})
    out = imports_check.check(rule, [df], _blob_factory({"src/X.cs": blob}))
    assert out == []


def test_python_still_works_alongside_cs():
    """The .py path must be unaffected by the .cs routing."""
    rule = _rule(["httpx"])
    blob = "import httpx\n"
    df = DiffFile(path="src/x.py", added_lines={1: "import httpx"})
    out = imports_check.check(rule, [df], _blob_factory({"src/x.py": blob}))
    assert len(out) == 1
