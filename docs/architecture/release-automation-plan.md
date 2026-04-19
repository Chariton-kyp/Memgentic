# Release Automation — Implementation Plan

> **Purpose**: Turn the design in [release-automation.md](./release-automation.md)
> into a landed, working system. Split across 8 atomic PRs so review,
> rollback, and session-handoff stay cheap.
>
> **How to use this doc**: when you land on this repo, scroll down until
> you see an unchecked `- [ ]` item. That's the next PR to open. Each
> PR has a stated scope, acceptance criteria, and a rollback plan. Do
> not merge out of order — later PRs assume earlier PRs are in place.
>
> **Tick boxes as PRs merge**, don't delete rows.

## Status board

| # | PR | Status | Merged commit |
| --- | --- | --- | --- |
| 0 | Baseline audit | n/a | — |
| 1 | Spec docs (this PR) | ⏳ open | — |
| 2 | Fix current version skew | ☐ | — |
| 3 | Version-consistency CI guard | ☐ | — |
| 4 | Commitlint CI + PR template | ☐ | — |
| 5 | CONTRIBUTING.md + CLAUDE.md convention section | ☐ | — |
| 6 | release-please config + workflow | ☐ | — |
| 7 | Pre-commit hooks + local dev config | ☐ | — |
| 8 | Dependabot auto-merge + SBOM upload | ☐ | — |

Legend: `☐` = not started · `⏳` = PR open · `✅` = merged · `❌` = reverted

---

## PR 1 — Spec docs (this PR)

**Branch**: `docs/release-automation-spec`

**Scope**
- `docs/architecture/release-automation.md` — system design + rationale
- `docs/architecture/release-automation-plan.md` — this checklist
- `docs/architecture/conventional-commits.md` — commit convention reference
- Link the new docs from `docs/RELEASE.md` and `CLAUDE.md` ("see architecture…")

**Acceptance**
- ✔ Docs exist and render on GitHub
- ✔ No code changes — the PR is pure documentation
- ✔ `CHANGELOG.md` not touched (this PR doesn't change user-visible behavior)

**Rollback**: delete the three files; zero runtime impact.

---

## PR 2 — Fix current version skew

**Branch**: `chore/sync-versions-0.6.0`

**Problem**
- `memgentic` is 0.6.0 on PyPI ✓
- `memgentic-native` is 0.5.0 on PyPI, and `main` has metadata aligned ✓
- `memgentic-api` is still 0.4.5 on PyPI and `main` — drifted

**Scope**
- Bump `memgentic-api/pyproject.toml` version 0.4.5 → 0.6.0
- Fix `memgentic-api/memgentic_api/__init__.py` version 0.1.0 → 0.6.0
  (it was already out of sync with pyproject)
- Bump `memgentic-native/pyproject.toml` + `Cargo.toml` + `Cargo.lock`
  0.5.0 → 0.6.0 (no src change — rationale in commit message)
- After merge: push `api-v0.6.0` and `native-v0.6.0` tags so the
  existing release workflows publish the catch-up versions.

**Acceptance**
- ✔ All 9 version-pinned locations show `0.6.0`
- ✔ `pip install memgentic-api==0.6.0` works after PR 2 + tag push
- ✔ `pip install memgentic-native==0.6.0` works after PR 2 + tag push
- ✔ All three PyPI projects now show `0.6.0` as latest

**Rollback**
- Revert the PR. PyPI publishes of 0.6.0 are permanent (file-name reuse
  disallowed), but that's harmless — we'd just bump to 0.6.1 next.

**Note**: This PR is the *last* manual version bump. After PR 6 lands,
release-please owns all bumps.

---

## PR 3 — Version-consistency CI guard

**Branch**: `ci/version-consistency`

**Scope**
- Add `scripts/check_version_consistency.py`:
  - Reads the 9 pinned locations
  - Fails with a non-zero exit and clear diff if any disagree
  - Prints the canonical version from `.release-please-manifest.json`
    once that exists, else from `__version__.py`
- Add `.github/workflows/version-consistency.yml`:
  - Triggers on `pull_request` + `push` to `main`
  - Runs the script; fails the check on drift
  - Job name: `version-consistency` (lowercase, hyphenated — used in
    branch-protection later)
- Add `Makefile` target `check-versions` that runs the same script
- Update `CLAUDE.md` with "run `make check-versions` before commit"

**Acceptance**
- ✔ A PR that intentionally drifts one `pyproject.toml` fails the check
- ✔ A clean PR passes
- ✔ Job name `version-consistency` appears in PR status checks

**Rollback**: delete the workflow file; script is inert without it.

---

## PR 4 — Commitlint CI + PR template

**Branch**: `ci/commitlint`

**Scope**
- Add `.github/workflows/commitlint.yml`:
  - Runs `@commitlint/cli` with `@commitlint/config-conventional`
  - Validates PR title (blocking — squash-merge uses the title)
  - Validates all commits on the PR (informational for now, not
    blocking, to ease the migration for in-flight branches)
- Add `commitlint.config.js` at repo root referencing the shared config
  and pinning scope types to our package + subsystem list
- Add `.github/pull_request_template.md`:
  - PR title reminder ("`feat(sqlite-vec): add async upsert`")
  - `BREAKING CHANGE:` footer slot
  - Checklist: tests added, docs updated, CHANGELOG not manually edited

**Acceptance**
- ✔ A PR titled `Add thing` fails commitlint
- ✔ A PR titled `feat(core): add thing` passes
- ✔ Opening a new PR auto-populates the template

**Rollback**: delete the workflow and template.

---

## PR 5 — CONTRIBUTING.md + CLAUDE.md convention section

**Branch**: `docs/contributing-and-conventions`

**Scope**
- Write (or rewrite) `CONTRIBUTING.md` covering:
  - How to set up a dev environment (`uv sync --dev`)
  - Branch naming convention
  - Commit message convention — link to `docs/architecture/conventional-commits.md`
  - PR template expectations
  - How releases work — link to `docs/RELEASE.md` (which we shorten
    in the next PR)
  - Running tests locally
- Add a "Conventions" section to `CLAUDE.md` that tells future Claude
  sessions the same rules:
  - Conventional commits are mandatory
  - Never edit version files manually
  - Use `gsd`/`feature-dev` style branching if relevant
- Shorten `docs/RELEASE.md` to: "releases are fully automated by
  release-please. To cut a release, merge the Release PR. See
  architecture/release-automation.md for the full design."

**Acceptance**
- ✔ CONTRIBUTING.md is the canonical entry point for new contributors
- ✔ CLAUDE.md has a clear "Claude-specific rules" section
- ✔ `docs/RELEASE.md` is under 30 lines

**Rollback**: `git revert` — pure doc change.

---

## PR 6 — release-please config + workflow

**Branch**: `ci/release-please`

**Scope**
- Add `release-please-config.json`:
  ```jsonc
  {
    "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
    "release-type": "python",
    "bump-minor-pre-major": true,
    "bump-patch-for-minor-pre-major": false,
    "include-component-in-tag": true,
    "separate-pull-requests": false,
    "tag-separator": "-",
    "linked-versions": [
      {
        "components": ["memgentic", "memgentic-api", "memgentic-native"]
      }
    ],
    "packages": {
      "memgentic": {
        "component": "memgentic",
        "release-type": "python",
        "package-name": "memgentic",
        "extra-files": [
          {"type": "generic", "path": "memgentic/memgentic/__version__.py"}
        ]
      },
      "memgentic-api": {
        "component": "memgentic-api",
        "release-type": "python",
        "package-name": "memgentic-api",
        "tag-prefix": "api-v",
        "extra-files": [
          {"type": "generic", "path": "memgentic-api/memgentic_api/__init__.py"}
        ]
      },
      "memgentic-native": {
        "component": "memgentic-native",
        "release-type": "rust",
        "package-name": "memgentic-native",
        "tag-prefix": "native-v"
      }
    }
  }
  ```
- Add `.release-please-manifest.json`:
  ```json
  {
    "memgentic": "0.6.0",
    "memgentic-api": "0.6.0",
    "memgentic-native": "0.6.0"
  }
  ```
  (Valid only after PR 2 ships — this PR assumes it.)
- Add `.github/workflows/release-please.yml`:
  ```yaml
  name: Release Please
  on:
    push:
      branches: [main]
  permissions:
    contents: write
    pull-requests: write
  jobs:
    release-please:
      runs-on: ubuntu-latest
      steps:
        - uses: googleapis/release-please-action@v4
          with:
            config-file: release-please-config.json
            manifest-file: .release-please-manifest.json
  ```
- Update existing `release.yml`, `release-api.yml`, `release-native.yml`:
  - Leave tag triggers as-is (`v*`, `api-v*`, `native-v*`)
  - Add a "release-please created this tag" detection log line
  - Ensure each publishes only its own package (verified by PRs already merged)
- Update branch protection: allow the `release-please` bot to push
  to `main` and create PRs (may require admin touch in GitHub UI —
  note in PR body).

**Acceptance**
- ✔ After merge + a follow-up `feat:` or `fix:` commit on main,
  release-please opens a "chore(main): release 0.6.1" PR within 5 min.
- ✔ The Release PR correctly bumps all 9 locations and writes a
  CHANGELOG block.
- ✔ Merging the Release PR produces three tags and the three tag-push
  workflows fire — all succeed.

**Rollback**
- Revert the PR. Existing tag-triggered workflows keep working
  (we left them untouched). No PyPI state changes.

**Validation plan** (before merging this PR)
1. Dry-run locally with `npx release-please release-pr --dry-run
   --repo-url=… --token=…` → inspect the planned PR body.
2. After merge: push a tiny `fix(docs): typo` to main → confirm the
   Release PR appears.
3. Merge the Release PR in a scratch test first if possible, or
   accept that the first real release is the test.

---

## PR 7 — Pre-commit hooks + local dev config

**Branch**: `dx/precommit-hooks`

**Scope**
- Add `.pre-commit-config.yaml`:
  - `commitizen` hook — validates commit messages locally
  - `ruff` (format + lint)
  - `pyright` (selective — see `[tool.pyright]` ignores)
  - `check-yaml` — workflow sanity
  - `end-of-file-fixer`, `trailing-whitespace`
- Add `.github/workflows/pre-commit.yml` that runs the same set in CI
  so contributors who skip the local install still get checked
- Update `CONTRIBUTING.md` with "run `pre-commit install` after clone"
- Ensure `ruff`/`pyright` configs in existing `pyproject.toml` agree
  with what pre-commit expects

**Acceptance**
- ✔ A commit with a bad message (e.g. `Update thing`) fails
  pre-commit locally
- ✔ `pre-commit run --all-files` passes on clean `main`

**Rollback**: delete `.pre-commit-config.yaml` and the workflow.

---

## PR 8 — Dependabot auto-merge + SBOM upload

**Branch**: `ci/dependabot-automerge-and-sbom`

**Scope**
- `.github/workflows/dependabot-automerge.yml`:
  - Triggers on pull-request labeled `dependencies` and
    authored by `dependabot[bot]`
  - Auto-merges only if:
    - Update type is `version-update:semver-patch`
    - Required checks all passing
  - Approves the PR and merges with squash
- Update release workflows (release.yml, release-api.yml,
  release-native.yml) to generate a CycloneDX SBOM after `uv build`:
  - `uv pip install cyclonedx-bom`
  - `cyclonedx-py environment --of JSON -o dist/sbom.json`
  - Upload `dist/sbom.json` as a release asset via
    `softprops/action-gh-release@v2` `files:` parameter
- (Stretch) Enable GitHub's "Attest artifact" action for each uploaded
  asset beyond the wheel (already done for wheels)

**Acceptance**
- ✔ A Dependabot patch PR that passes CI auto-merges within 10 min
  (requires at least one test patch update to verify)
- ✔ A fresh release includes `sbom.json` as a release asset
- ✔ Running `trivy sbom sbom.json` on the asset surfaces vulns

**Rollback**: disable the auto-merge workflow (keeps SBOM generation).

---

## Out of scope — deferred

These are good ideas but not part of this pipeline:

- **Cosign signing beyond PyPI attestations** — defer to post-v1.0
- **Multi-arch Docker image automation** — separate concern, separate workflow
- **Nightly pre-release builds** (`0.7.0-dev.YYYYMMDD`) — defer until we
  have beta testers who want to live on the tip
- **Switching off GitHub Actions to self-hosted runners** — decision for
  scale, not for correctness

## Execution notes for future Claude sessions

- **Work on one PR at a time.** Don't stack PRs 6 and 7 — PR 7 can't
  merge until 6 because pre-commit checks commit messages, which needs
  the convention established.
- **Each PR has one commit** (squash-merge the worktree). Small,
  reviewable deltas.
- **After every merge**, come back to this document and tick the box.
- **If a PR has to grow beyond its scope**, stop — spawn a new PR.
- **If release-please behaves unexpectedly after PR 6**, disable the
  workflow (rename file to `.yml.disabled`) before debugging. That
  stops the flood of noisy Release PRs.
- **Test environment**: consider cutting the first post-automation
  release as `0.6.1` or `0.7.0-rc.1` so we have a clean "before vs
  after" comparison.

## Reference links

- [release-automation.md](./release-automation.md) — the design
- [conventional-commits.md](./conventional-commits.md) — commit format
- [release-please action](https://github.com/googleapis/release-please-action)
- [commitlint](https://github.com/conventional-changelog/commitlint)
- [pre-commit](https://pre-commit.com/)
- [Dependabot auto-merge guide](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/automating-dependabot-with-github-actions#enable-auto-merge-on-a-pull-request)
