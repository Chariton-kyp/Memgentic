from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from memgentic.guard import blobs, diff
from memgentic.guard.checks import dependencies, import_direction, imports, paths
from memgentic.models import GuardRule, GuardRuleType, Violation

_CHECKS = {
    GuardRuleType.IMPORT_DIRECTION: import_direction.check,
    GuardRuleType.BANNED_DEPENDENCY: dependencies.check,
    GuardRuleType.BANNED_IMPORT: imports.check,
    GuardRuleType.FORBIDDEN_PATH: paths.check,
}


def load_rules(path: Path) -> list[GuardRule]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules: list[GuardRule] = []
    # ``rules:`` with no value parses to None (e.g. the all-commented starter
    # template from ``guard init``); treat it as an empty ruleset, not a crash.
    for i, r in enumerate(data.get("rules") or []):
        try:
            rules.append(GuardRule(**r))
        except ValidationError as exc:
            rid = r.get("id", f"<index {i}>") if isinstance(r, dict) else f"<index {i}>"
            raise ValueError(f"Invalid rule '{rid}' in {path}: {exc}") from exc
    return rules


def run(repo: Path, rules: list[GuardRule], *, base: str | None, staged: bool) -> list[Violation]:
    text = diff.get_diff(repo, base=base, staged=staged)
    diff_files = diff.parse_diff(text)
    ref = ":0" if staged else "HEAD"
    getter = blobs.make_blob_getter(repo, ref)
    base_ref = "HEAD" if staged else (base or "main")
    base_getter = blobs.make_blob_getter(repo, base_ref)
    out: list[Violation] = []
    for rule in rules:
        out.extend(_CHECKS[rule.type](rule, diff_files, getter, base_blob_getter=base_getter))
    return out
