# Release Process

Memgentic uses PyPI Trusted Publishing via GitHub Actions. No API tokens are stored in the repo.

## One-time PyPI Setup

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name:** `memgentic`
   - **Owner:** `Chariton-kyp`
   - **Repository name:** `memgentic`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
4. Save.

Then in GitHub repo settings, create an environment named `pypi` (Settings → Environments → New environment → `pypi`).

## Cutting a Release

1. Update `CHANGELOG.md`: move `[Unreleased]` items under a new version header with today's date.
2. Bump version in `memgentic/memgentic/__version__.py`.
3. Commit the version bump: `git commit -am "Release vX.Y.Z"`.
4. Tag: `git tag vX.Y.Z && git push && git push --tags`.
5. GitHub Actions `release.yml` runs on tag push:
   - Builds sdist + wheel via `uv build`.
   - Runs tests.
   - Publishes to PyPI via trusted publishing.
6. Create a GitHub Release from the tag, copying the CHANGELOG excerpt into the release notes.

## Verifying a Release

```bash
pip install --upgrade memgentic
memgentic --version   # should print the new version
```
