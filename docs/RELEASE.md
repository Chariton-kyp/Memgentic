# Release Process

Memgentic ships **three linked-version packages** from this repo:

| Package | Tag pattern | Publish workflow | PyPI env | PyPI project |
| --- | --- | --- | --- | --- |
| `memgentic` (core Python) | `vX.Y.Z` | `release.yml` | `pypi` | https://pypi.org/p/memgentic |
| `memgentic-api` (REST) | `api-vX.Y.Z` | `release-api.yml` | `pypi-api` | https://pypi.org/p/memgentic-api |
| `memgentic-native` (Rust wheel) | `native-vX.Y.Z` | `release-native.yml` | `pypi-native` | https://pypi.org/p/memgentic-native |

All three use **PyPI Trusted Publishing** (OIDC — no tokens). The environment names, workflow filenames, and owner/repo are load-bearing: renaming any of them requires updating the matching PyPI Trusted Publisher entry first, or the OIDC claim check will fail with a 403.

---

## Day-to-day flow (fully automated)

You don't cut releases by hand any more. The pipeline:

1. Commit to `main` with [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `perf:`, `security:`, `docs:`, `chore:`, …). Only `feat`/`fix`/`perf`/`security` move the version.
2. `release-please.yml` opens or updates a **"chore: release main" PR** aggregating all releasable commits across the three packages.
3. `linked-version-align.yml` runs on that PR and **auto-bumps any component whose manifest entry drifted** (`memgentic-native` usually — no Rust changes most cycles). You never edit the manifest yourself.
4. You review the Release PR's diff (CHANGELOG excerpts, version bumps) and **merge** it.
5. release-please creates three tags on the merge commit: `vX.Y.Z`, `api-vX.Y.Z`, `native-vX.Y.Z`.
6. Each tag fires its matching publish workflow → wheels + sdist built → attested via SLSA build provenance → uploaded to PyPI via Trusted Publisher → GitHub Release created with the matching CHANGELOG section.

Everything after step 4 is unattended.

### Commit types and version bumps

| Commit type | Bump | In CHANGELOG? |
| --- | --- | --- |
| `feat` | minor | yes (**Features**) |
| `fix` | patch | yes (**Bug Fixes**) |
| `perf` | patch | yes (**Performance**) |
| `security` | patch | yes (**Security**) |
| `revert` | patch | yes (**Reverts**) |
| `docs`, `test`, `refactor`, `build`, `ci`, `chore`, `style` | none | hidden |

Breaking changes require `!` in the type (e.g. `feat!: rename foo to bar`) or a `BREAKING CHANGE:` footer — triggers a major bump once we're past 1.0.

---

## Infrastructure

### GitHub Secrets

| Secret | Role | Scope |
| --- | --- | --- |
| `RELEASE_PLEASE_TOKEN` | Personal access token owned by the maintainer (`@Chariton-kyp`). Used by `release-please.yml`, `linked-version-align.yml`, and `dependabot-auto-merge.yml` so their pushes / reviews **fire downstream workflows** and **satisfy the CODEOWNERS gate**. | `contents: write`, `pull_requests: write` on this repo only. |
| _(no PyPI token)_ | PyPI uses OIDC Trusted Publishing; no long-lived secret exists. | — |

When the PAT expires, rotate it and update the secret. The workflows fall back to `GITHUB_TOKEN` if the PAT is absent — automation stays green but downstream CI won't fire on release-please pushes until the PAT is set.

### Branch protection on `main`

- 7 required status checks (build / test / typecheck / lint / Validate PR title / All packages agree on version / CodeQL).
- Linear history required.
- No force push, no tag deletion.
- `required_pull_request_reviews` with `required_approving_review_count: 1` and `require_code_owner_reviews: true`.
- `enforce_admins: false` — solo maintainer admin-bypass is allowed during bootstrap / hotfixes but stays legible in the merge graph.

CODEOWNERS lives at `.github/CODEOWNERS` and pins every path to `@Chariton-kyp`. Reviews posted as `github-actions[bot]` do **not** satisfy the code-owner gate; the PAT-based bots post as the owner, which does.

### Dependabot

`.github/dependabot.yml` has entries for `github-actions`, `pip` (workspace-root — reads `uv.lock`), `cargo` (`/memgentic-native` — reads `Cargo.lock`), `npm` (`/dashboard`), and `docker` (`/`). Weekly cadence, Monday 06:00 Europe/Athens. `.github/workflows/dependabot-auto-merge.yml` auto-approves + auto-merges **patch-level** bumps via the PAT. Minor + major updates require manual review. Specific ignores are documented inline in `dependabot.yml` (pyo3, next, react, react-dom, tailwindcss — all majors need dedicated migration PRs).

### The linked-version-align workflow

`.github/workflows/linked-version-align.yml` runs on every push to any `release-please--branches--*` PR branch. It invokes `scripts/align_linked_versions.py` which:

1. Reads `.release-please-manifest.json`.
2. If all three entries already match, exits `changed=false` and the workflow no-ops.
3. Otherwise picks the max version as target, rewrites the lagging component's version-bearing files (`__version__.py` / `__init__.py` / `pyproject.toml` / `Cargo.toml` / `Cargo.lock`), and updates the manifest entry.
4. Emits `changed=true`; the workflow step commits + pushes via the PAT (which re-triggers CI on the PR).

The push itself doesn't cause an infinite loop — the next invocation reads the now-aligned manifest and no-ops at step 2.

---

## Recovering from a stuck tag

Sometimes `release-please` creates tags that never fire downstream publishes (happens when `RELEASE_PLEASE_TOKEN` is missing — tags pushed by `GITHUB_TOKEN` do not trigger workflows). Each publish workflow accepts `workflow_dispatch` with a `tag` input as an escape hatch:

```bash
gh workflow run release.yml         -f tag=vX.Y.Z
gh workflow run release-api.yml     -f tag=api-vX.Y.Z
gh workflow run release-native.yml  -f tag=native-vX.Y.Z
```

Each dispatched run re-reads the tagged commit (`actions/checkout@v6` with `ref: env.TAG_NAME`), re-verifies the version matches the in-tree files, and runs the normal publish + GitHub Release steps. The `verify-version` step refuses to re-publish a version already on PyPI — safe to retry.

---

## Verifying a release

```bash
# All three should report the new version
python -c "import memgentic; print(memgentic.__version__)"
python -c "import memgentic_api; print(memgentic_api.__version__)"
python -c "import memgentic_native; print(memgentic_native.__version__)"
```

PyPI project pages surface:

- **Release history** tab — list of every version + date + files.
- **Meta / Project links** sidebar — Homepage, Documentation, Issues, **Changelog**, Source.
- **Long description** — rendered from each package's `README.md`.

The `Changelog` sidebar link points at the repo's `CHANGELOG.md` file (root = aggregate; each package also maintains its own CHANGELOG that release-please updates).

---

## Historical notes

- **v0.4.x — v0.5.x:** Releases were cut by hand (`git tag vX.Y.Z && git push --tags`). This doc previously described that flow.
- **v0.6.0:** First release-please-driven cycle. Only the core package bumped cleanly; `memgentic-api` + `memgentic-native` fell out of sync.
- **v0.7.0:** First fully-linked release across all three. Several infra gaps found and fixed in the process:
  - `RELEASE_PLEASE_TOKEN` PAT now required (see Infrastructure above).
  - `workflow_dispatch` escape hatch added to all three publish workflows.
  - `linked-version-align.yml` + `scripts/align_linked_versions.py` added to automate the manual native-alignment step.
  - Branch protection tightened with CODEOWNERS review requirement.
  - SBOM step temporarily removed; will be re-added via `cargo-cyclonedx` (native) + env-native cyclonedx for Python packages.

Keep this doc in lockstep with the real workflows — if you change an env name, a tag pattern, or a secret, update the tables above in the same PR.
