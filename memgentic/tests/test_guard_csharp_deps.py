"""Tests for .csproj / Directory.Packages.props support in banned_dependency."""

from __future__ import annotations

from memgentic.guard.checks.dependencies import check
from memgentic.guard.diff import DiffFile
from memgentic.models import GuardRule


def _rule(targets, scope="**", message="banned package", severity="error"):
    return GuardRule(
        id="no-redis",
        type="banned_dependency",
        scope=scope,
        targets=targets,
        message=message,
        severity=severity,
    )


def _blob(blobs):
    def getter(path):
        return blobs.get(path)

    return getter


def test_csproj_packagereference_fires():
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageReference Include="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert len(out) == 1
    assert out[0].file == "src/Api.csproj"
    assert out[0].line == 10
    assert out[0].severity == "error"


def test_csproj_case_insensitive_id():
    """NuGet IDs are case-insensitive."""
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageReference Include="stackexchange.redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert len(out) == 1


def test_csproj_signalr_redis_no_false_positive():
    """REGRESSION: target StackExchange.Redis must NOT match the SignalR package
    whose ID is Microsoft.AspNetCore.SignalR.StackExchangeRedis."""
    rule = _rule(["StackExchange.Redis"])
    line = (
        "    <PackageReference "
        'Include="Microsoft.AspNetCore.SignalR.StackExchangeRedis" Version="8.0.0" />'
    )
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert out == []


def test_csproj_update_attribute_matches():
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageReference Update="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert len(out) == 1


def test_directory_packages_props_packageversion_fires():
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageVersion Include="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="Directory.Packages.props", added_lines={5: line})
    out = check(rule, [df], lambda p: None)
    assert len(out) == 1


def test_directory_packages_props_packagereference_fires():
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageReference Include="StackExchange.Redis" />'
    df = DiffFile(path="Directory.Packages.props", added_lines={5: line})
    out = check(rule, [df], lambda p: None)
    assert len(out) == 1


def test_csproj_unrelated_package_no_fire():
    rule = _rule(["StackExchange.Redis"])
    line = '    <PackageReference Include="Serilog" Version="3.1.1" />'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert out == []


def test_csproj_base_side_suppression_version_bump():
    """A version bump of a pre-existing banned package stays silent."""
    rule = _rule(["StackExchange.Redis"])
    base = (
        "<Project>\n  <ItemGroup>\n"
        '    <PackageReference Include="StackExchange.Redis" Version="2.6.0" />\n'
        "  </ItemGroup>\n</Project>\n"
    )
    new_line = '    <PackageReference Include="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={3: new_line})
    out = check(
        rule,
        [df],
        lambda p: None,
        base_blob_getter=_blob({"src/Api.csproj": base}),
    )
    assert out == []


def test_csproj_base_side_no_suppression_when_new():
    """A genuinely new banned package fires even with base getter present."""
    rule = _rule(["StackExchange.Redis"])
    base = "<Project>\n  <ItemGroup>\n  </ItemGroup>\n</Project>\n"
    new_line = '    <PackageReference Include="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={3: new_line})
    out = check(
        rule,
        [df],
        lambda p: None,
        base_blob_getter=_blob({"src/Api.csproj": base}),
    )
    assert len(out) == 1


def test_csproj_severity_copied():
    rule = _rule(["StackExchange.Redis"], severity="warn")
    line = '    <PackageReference Include="StackExchange.Redis" Version="2.7.4" />'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    assert out[0].severity == "warn"


def test_csproj_comment_no_false_positive():
    rule = _rule(["StackExchange.Redis"])
    line = '    <!-- <PackageReference Include="StackExchange.Redis" /> -->'
    df = DiffFile(path="src/Api.csproj", added_lines={10: line})
    out = check(rule, [df], lambda p: None)
    # Inside an XML comment — should not fire.
    assert out == []


def test_pyproject_still_works():
    """Python pyproject path must be unaffected by csproj routing."""
    rule = GuardRule(
        id="no-lc",
        type="banned_dependency",
        scope="**",
        targets=["langchain-core"],
        message="m",
    )
    df = DiffFile(path="memgentic/pyproject.toml", added_lines={42: '    "langchain-core>=1.2",'})
    assert len(check(rule, [df], lambda p: None)) == 1
