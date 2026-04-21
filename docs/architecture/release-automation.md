# Release Automation — Architecture

> **Status**: Accepted — implementation in progress.
>
> **Audience**: contributors + maintainers who want to understand how
> a change they land on `main` ends up on PyPI.

## Context

Memgentic ships three PyPI packages from a single repository:

- `memgentic` — core library (CLI, MCP server, adapters, storage, daemon)
- `memgentic-api` — FastAPI REST layer that wraps core
  (depends on `memgentic[intelligence]`)
- `memgentic-native` — Rust acceleration crate via PyO3 / maturin
  (auto-detected by core at import time)

Until 2026-04-19 the three packages had drifted into independent
versions because their release workflows fired on independent tag
patterns (`v*`, `api-v*`, `native-v*`) and no process enforced
"bump together." Users installing the default install ended up with
a mix of versions whose compatibility was accidental.

This document describes the target state: **fully-automated, lockstep
releases driven by Conventional Commits**, with one manual step
between "merge the code PR" and "users get the new version via
`pip install -U`".

## Goals

1. **Single source of truth** for the current Memgentic version.
2. **Lockstep releases**: core, api, and native always ship the same
   version, even when only one package had code changes.
3. **Zero manual bumps**: no one edits `__version__.py` / `Cargo.toml` /
   `pyproject.toml` by hand. The automation does it deterministically
   from commit history.
4. **Zero manual tagging**: a merge produces the tags.
5. **Deterministic changelogs**: `CHANGELOG.md` is rewritten from the
   commit stream, not hand-curated.
6. **Human approval**: exactly one manual step remains — merging the
   "Release PR" — so maintainers retain veto power.
7. **Safe defaults**: CI blocks a merge if any version guard fails,
   and no workflow can republish an already-published PyPI version.

## Non-goals

- Perfect semver granularity per package. We pick **linked/lockstep**
  versioning on purpose; see the [Decision section](#decision).
- Multi-repo packaging (Cloud tier, desktop apps, etc.). Those live
  in separate repositories and bump independently.
- Automating PyPI trusted-publisher onboarding. One-time manual setup,
  already complete for all three packages.

## Decision

**Adopt [release-please](https://github.com/googleapis/release-please)
with `linked-versions: true` across all three packages, driven by
Conventional Commits.**

### Why release-please

Alternatives considered:

| Option | Verdict |
| --- | --- |
| **release-please** (Google) | ✅ Monorepo-first, Python + Rust first-class, linked versions supported, actively maintained, "Release PR" pattern = one merge = published |
| semantic-release | ❌ JavaScript-first; Python plugin lags; monorepo support weaker |
| python-semantic-release | ❌ Single-package focus; monorepo support weak; no Rust |
| Commitizen + manual CI | ⚠️ Handles local bumps well, but no automated Release PR pattern |
| Changesets | ❌ Node ecosystem; Python support is third-party |
| Nx Release | ❌ Built around Nx workspaces; non-standard for Python/Rust |
| Manual `scripts/release.sh` | ⚠️ Works but every contributor must remember the script; CHANGELOG stays manual |

release-please wins on four axes: **monorepo-aware**, **polyglot**
(Python + Rust in the same config), **Release PR pattern** (the sweet
spot between zero-input and full human control), and **active
maintenance** by Google with security attestations.

### Why linked (lockstep) versioning

| Argument | Winner |
| --- | --- |
| Product clarity ("Memgentic 0.7.0" = one number) | Linked |
| Users install via one `pip install` and expect one version | Linked |
| Tightly coupled: core ↔ api ↔ native are tested together | Linked |
| Fewer release streams to track | Linked |
| Semver "true" (version reflects actual code change per package) | Independent |
| "Empty" releases when a package has no diff | Independent |

For tightly-coupled products (Next.js, Vue 3, Babel, React pattern),
**linked wins**. For loosely-coupled ecosystems with independent teams
(LangChain, Kubernetes, AWS SDK), **independent wins**. Memgentic is
the former.

### Why Conventional Commits

- release-please needs a parseable commit stream to decide bump level.
- Alternatives like "ask the maintainer each release" defeat the
  automation goal.
- Industry standard since 2018; mainstream tooling support.

## Target workflow

### Authoring a change

```bash
git checkout -b feat/sqlite-vec-batch-upsert
# … code changes …
git commit -m "feat(sqlite-vec): add async batch upsert API

Accepts an iterable of (memory, embedding) pairs and writes them in a
single SQLite transaction. 50-200x faster than per-item upsert on the
ingestion hot path."
git push
# Open PR — CI validates commit message format + version consistency.
# Reviewer(s) approve + merge.
```

Commit rules — see [conventional-commits.md](./conventional-commits.md).

### release-please on merge

Every push to `main` triggers `.github/workflows/release-please.yml`:

1. release-please scans commits since the last release tag.
2. If any `feat` / `fix` / `perf` / breaking commits exist, it either:
   - **Opens** a new Release PR titled `chore(main): release X.Y.Z`, or
   - **Updates** the existing Release PR with new commits and a
     recomputed version.
3. The Release PR contains:
   - Bumped version in every pinned location:
     - `memgentic/memgentic/__version__.py`
     - `memgentic-api/pyproject.toml`
     - `memgentic-api/memgentic_api/__init__.py`
     - `memgentic-native/Cargo.toml`
     - `memgentic-native/Cargo.lock` (regenerated)
     - `memgentic-native/pyproject.toml`
     - `.release-please-manifest.json`
     - (any docs references, handled via `extra-files` in config)
   - Auto-generated `CHANGELOG.md` section grouped by type
     (`### Features`, `### Bug Fixes`, `### Breaking Changes`, etc.)
   - A label `autorelease: pending`.

### Merging the Release PR

The single manual step. Review the diff if desired, then merge.

### Post-merge automation

On merge of a Release PR:

1. release-please creates three git tags pointing at the merge commit:
   - `vX.Y.Z` (core)
   - `api-vX.Y.Z`
   - `native-vX.Y.Z`
2. Each tag triggers its existing tag-push workflow (kept as-is):
   - `release.yml` on `v*` → build + publish `memgentic` to PyPI
   - `release-api.yml` on `api-v*` → build + publish `memgentic-api`
   - `release-native.yml` on `native-v*` → build wheels + publish
     `memgentic-native`
3. Each workflow publishes via **PyPI Trusted Publishing** (OIDC, no
   API tokens), with per-package GitHub environments.
4. Each workflow creates a GitHub Release with the matching
   CHANGELOG section as body.
5. Attestations published via `actions/attest-build-provenance@v2` —
   SLSA provenance for every artifact.

### Users

```bash
pip install --upgrade memgentic        # gets latest core + matching native wheel
pip install --upgrade memgentic-api    # always in sync with core
```

No version skew.

## Guards

### 1. Conventional commit enforcement (PR-time)

`.github/workflows/commitlint.yml` runs `@commitlint/cli` with
`@commitlint/config-conventional` against:
- PR title (always required — the squashed commit message)
- PR body (checks for `BREAKING CHANGE:` footer syntax)
- Individual commits on the branch (informational, non-blocking)

A PR whose title doesn't parse fails CI and cannot merge.

### 2. Version consistency check (PR-time)

`.github/workflows/version-consistency.yml` fails when the versions
across the pinned locations disagree. This exists because a
contributor might touch one `pyproject.toml` and forget the others;
release-please is the only sanctioned editor.

Implementation: a small Python script `scripts/check_version_consistency.py`
reads each location, returns non-zero if they diverge. Runs in CI and
can be invoked locally via `make check-versions`.

### 3. Published-version guard (tag-push workflow)

Each release workflow's `verify-version` job already checks that the
pushed tag matches the in-tree version. Additionally, a probe against
PyPI fails fast if `$PROJECT==$VERSION` already exists — prevents the
"400 File already exists" failures observed in early April 2026.

### 4. Branch protection on `main`

Branch protection is a GitHub repository setting (not a tracked file)
so it cannot be provisioned in code. Configure it once, per repo, in
**Settings → Branches → Add rule → `main`**:

- **Require a pull request before merging** → ✓
- **Require status checks to pass before merging** → ✓ with the
  following required:
  - `build`
  - `test`
  - `typecheck`
  - `lint`
  - `Validate PR title` (from `commitlint.yml`)
  - `All packages agree on version` (from `version-consistency.yml`)
  - `CodeQL`
  - `Run pre-commit on changed files` (optional — allows contributors
    to skip local install without a hard block)
- **Require branches to be up to date before merging** → ✓
- **Require linear history** → recommended (clean squash-merge log)
- **Do not allow bypassing the above settings** → ✓
- **Restrict who can push to matching branches** → empty (release-please
  bot pushes via PR; tags go via the Release PR merge commit, not direct
  push)

Equivalent one-shot via `gh api`:

```bash
gh api --method PUT \
  "repos/:owner/:repo/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "build", "test", "typecheck", "lint",
      "Validate PR title",
      "All packages agree on version",
      "CodeQL"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

release-please uses `secrets.GITHUB_TOKEN` (no PAT, no GitHub App) and
its PRs go through the same protection — no bypass list needed.

### 5. Pre-commit hooks (optional but recommended)

`.pre-commit-config.yaml` with:
- `commitizen` — validates commit messages as they're written locally
- `ruff` — formatter + linter
- `pyright` — type checker (selective)
- `check-yaml` — catches workflow syntax errors before push

Installed via `pre-commit install` (one-time per contributor). A CI
job also runs the same hooks to enforce against contributors who
skipped the local install.

## Supply-chain & security

### Build provenance (SLSA)

- Every published artifact is signed via
  `actions/attest-build-provenance@v2` → uploaded to Sigstore's
  Rekor transparency log.
- PyPI displays the attestation on the project page.
- Target level: **SLSA v1.0 Build Level 3** — requires hermetic
  builds, non-falsifiable provenance, isolated build environment. All
  three workflows already satisfy Level 2; Level 3 requires pinning
  runner versions and eliminating post-build mutation.

### SBOM generation

Each release workflow runs `cyclonedx-py` after `uv build` and uploads
the SBOM alongside the wheel as a GitHub Release asset. Format:
CycloneDX 1.6 JSON. Consumer tools (Trivy, Grype, Dependency-Track)
ingest these.

### Dependency posture

- **Dependabot** opens PRs for security and version updates, grouped
  by patch/minor per week.
- **Patch auto-merge** for Dependabot: a workflow merges Dependabot
  PRs when (a) the update is `patch` severity, (b) tests pass,
  (c) CodeQL stays clean. Human review retained for minor/major.
- **OpenSSF Scorecard** runs weekly; any regression opens an issue
  via the Security tab.
- **CodeQL** scans Python + JavaScript on push and PR.

### Signing (stretch goal)

**Sigstore cosign** signatures on the final artifacts beyond PyPI's
attestation. Decision deferred until SLSA Level 3 lands.

## Components diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         Contributor                              │
│   git commit -m "feat(…): …"                                     │
│   git push → PR                                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Pull Request (main)                          │
│  ▸ commitlint.yml       (PR title conventional)                  │
│  ▸ version-consistency  (pinned versions agree)                  │
│  ▸ build.yml            (test + uv build sanity)                 │
│  ▸ typecheck, lint, security, CodeQL                             │
│                   merge when all green                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              .github/workflows/release-please.yml                │
│  scans commits since last release                                │
│     │                                                            │
│     ├─ no relevant commits → no-op                               │
│     │                                                            │
│     └─ has feat/fix/perf/breaking →                              │
│          opens / updates "chore(main): release X.Y.Z" PR         │
│          with version bumps + CHANGELOG diff                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                  [ maintainer merges ]
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              release-please post-merge actions                   │
│  ▸ creates tags: vX.Y.Z, api-vX.Y.Z, native-vX.Y.Z               │
│  ▸ creates GitHub Releases                                       │
│  ▸ updates .release-please-manifest.json                         │
└───────────┬─────────────────┬─────────────────┬─────────────────┘
            │                 │                 │
            ▼                 ▼                 ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────┐
│  release.yml     │ │ release-api.yml  │ │ release-native.yml   │
│  on v*           │ │ on api-v*        │ │ on native-v*         │
│                  │ │                  │ │                      │
│  verify-version  │ │ verify-version   │ │  build 10 wheels     │
│  test + build    │ │ test + build     │ │  build sdist         │
│  Trusted Publish │ │ Trusted Publish  │ │  Trusted Publish     │
│  GH Release      │ │ GH Release       │ │  GH Release          │
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   pypi.org/p/memgentic    pypi.org/p/            pypi.org/p/
                           memgentic-api          memgentic-native
```

## Migration strategy

Implemented as a sequence of small, self-contained PRs — each
independently mergeable and revertible, so intermediate states are
all valid. This keeps review cheap and allows the migration to pause
safely at any point without breaking releases.

## Observability

- release-please run history: **GitHub Actions** → workflow
  "Release Please"
- Release status per tag: `gh release list -R Chariton-kyp/Memgentic`
- PyPI status per package: `pip index versions memgentic` etc.
- CHANGELOG drift detection: a CI assertion that the top CHANGELOG
  entry matches `.release-please-manifest.json`.

## Rules for anyone landing changes

1. **Never manually edit version files.** release-please owns them.
   If you need to force a version, do it via a `chore` commit with a
   `Release-As: X.Y.Z` footer (release-please convention).
2. **Never manually `git tag`** a package. release-please creates
   tags on Release PR merge.
3. **Always use Conventional Commits** — `git commit -m "feat(scope): …"`.
   See [conventional-commits.md](./conventional-commits.md).
4. **If a release fails partway** (e.g. 1/3 packages published):
   don't retry by re-tagging. Inspect the failed workflow, fix the
   root cause, and release-please will create a new Release PR on the
   next non-no-op commit.
5. **PyPI Trusted Publisher environments** are load-bearing. Do not
   rename them without updating the PyPI publisher entry first.

## Open questions

- **Pre-release channels** (`rc.1`, `beta.1`): release-please supports
  via `prerelease-type`. Deferred until there's a concrete use case.
- **Independent versioning per-package** if the project graduates and
  the packages decouple. Revisit at v1.0.
- **Auto-merge for Release PRs**: currently disabled. The explicit
  human gate is cheap insurance in alpha.
- **Cosign signing** beyond PyPI attestations — waiting for broader
  tooling support.

## References

- [release-please documentation](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md)
- [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [SemVer 2.0](https://semver.org/)
- [SLSA Build Levels](https://slsa.dev/spec/v1.0/levels)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
