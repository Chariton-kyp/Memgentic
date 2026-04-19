# Release Process

Memgentic uses PyPI Trusted Publishing via GitHub Actions. No API tokens are
stored in the repo — the `release` GitHub Environment obtains a short-lived
OIDC token at publish time.

## One-time PyPI Setup

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name:** `memgentic`
   - **Owner:** `Chariton-kyp`
   - **Repository name:** `Memgentic`
   - **Workflow name:** `release.yml`
   - **Environment name:** `release`
4. Save.
5. Repeat the same four steps for a second publisher with **PyPI Project
   Name:** `memgentic-api` (same repo / workflow / environment).

Then in the GitHub repo settings create an environment named `release`
(Settings → Environments → New environment → `release`). Add branch
protection on the environment so only `main`/tags can deploy.

## Cutting a Release

1. Update `CHANGELOG.md`: move `[Unreleased]` items under a new
   `## [X.Y.Z] — YYYY-MM-DD — Title` header.
2. Bump `memgentic/memgentic/__version__.py` to match.
3. Commit: `git commit -am "chore(release): vX.Y.Z"`.
4. Tag + push: `git tag vX.Y.Z && git push && git push --tags`.
5. GitHub Actions `release.yml` runs on tag push and:
   - Verifies the tag version matches `__version__.py` (fails loudly otherwise).
   - Builds sdist + wheel for both `memgentic` and `memgentic-api` via `uv build`.
   - Runs the test suite (with the same `--ignore` list the PR workflow uses).
   - Publishes both to PyPI via trusted publishing (environment: `release`).
   - Creates a GitHub Release with the matching CHANGELOG section as body.

## Verifying a Release

```bash
pip install --upgrade memgentic
memgentic --version   # should print the new version
```
