# Release Process

Memgentic ships two independently-versioned packages from this repo:

| Package | Tag pattern | Workflow | PyPI env | PyPI project |
| --- | --- | --- | --- | --- |
| `memgentic` (core) | `vX.Y.Z` | `release.yml` | `pypi` | https://pypi.org/p/memgentic |
| `memgentic-api` (REST layer) | `api-vX.Y.Z` | `release-api.yml` | `pypi-api` | https://pypi.org/p/memgentic-api |

Both use **PyPI Trusted Publishing** (OIDC). No API tokens or passwords are
stored in the repo — the GitHub Environment obtains a short-lived OIDC
token at publish time, and PyPI verifies the `repository + workflow +
environment` claims match the publisher entry.

## Current publisher state

Both PyPI projects and both GitHub environments are already configured —
do not re-create them. The environment names (`pypi`, `pypi-api`) and
workflow filenames are load-bearing: renaming any of them requires
updating the matching PyPI Trusted Publisher entry first, or the OIDC
claim check will fail with a 403.

## If you ever need to re-create the publisher entries

For each package separately:

1. Go to https://pypi.org/manage/project/<project>/settings/publishing/
2. "Add a new publisher" → GitHub
3. Fill in:
   - **Owner:** `Chariton-kyp`
   - **Repository:** `Memgentic`
   - **Workflow name:** `release.yml` (core) or `release-api.yml` (API)
   - **Environment name:** `pypi` (core) or `pypi-api` (API)

And in the GitHub repo at `/settings/environments`, make sure the env
exists with the exact matching name and branch protection limited to
`main` + tag refs that match each workflow's trigger.

## Cutting a release of `memgentic` (core)

1. Update `CHANGELOG.md`: move `[Unreleased]` items under a new
   `## [X.Y.Z] — YYYY-MM-DD — Title` header.
2. Bump `memgentic/memgentic/__version__.py` to match.
3. Commit: `git commit -am "chore(release): vX.Y.Z"`.
4. Tag + push: `git tag vX.Y.Z && git push && git push --tags`.
5. GitHub Actions `release.yml` runs on the tag push and:
   - Verifies the tag version matches `__version__.py` (fails loudly otherwise).
   - Runs the core test suite (with the same `--ignore` list the PR `build`
     workflow uses).
   - Builds `memgentic` sdist + wheel via `uv build`.
   - Publishes to PyPI via trusted publishing (environment `pypi`).
   - Creates a GitHub Release with the matching CHANGELOG section as body.

## Cutting a release of `memgentic-api`

The API tier versions separately, so the tag pattern has an `api-` prefix
and only the API package ships:

1. Bump the `memgentic-api` version (`memgentic-api/pyproject.toml` or the
   equivalent version file).
2. Tag + push: `git tag api-vX.Y.Z && git push --tags`.
3. `release-api.yml` runs, tests, builds, publishes to PyPI (environment
   `pypi-api`), and cuts a GitHub Release.

## Verifying a release

```bash
pip install --upgrade memgentic       # or: memgentic-api
memgentic --version   # should print the new version
```
