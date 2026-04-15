# Contributing to Memgentic

Thanks for your interest! Memgentic is Apache 2.0 and welcomes contributions of all kinds.

## Quick Contributor Setup

```bash
git clone https://github.com/Chariton-kyp/memgentic.git
cd memgentic/memgentic
uv sync --all-extras
uv run python -m pytest tests/ -q
```

You should see `500+ passed, 0 failed`.

### Prerequisites

- Python 3.12+
- [UV](https://docs.astral.sh/uv/) package manager
- [Ollama](https://ollama.com/) running locally (or set `MEMGENTIC_EMBEDDING_PROVIDER=openai`)
- Embedding model: `ollama pull qwen3-embedding:0.6b`

## Development Loop

1. Create a feature branch: `git checkout -b feature/my-change`
2. Make your changes
3. Run tests: `uv run python -m pytest tests/ -x -q`
4. Lint: `uv run ruff check memgentic/ tests/`
5. Format: `uv run ruff format memgentic/ tests/`
6. Commit (see commit message style below)
7. Push and open a PR

## Adding an Adapter

Adapters live in `memgentic/memgentic/adapters/`. To add support for a new AI tool:

1. Create `memgentic/adapters/my_tool.py` inheriting from `BaseAdapter`
2. Implement the required methods:
   - `platform` — return a value from `Platform` enum (add to `models.py` if needed)
   - `watch_paths` — directories to monitor
   - `file_patterns` — glob patterns
   - `parse_file()` — extract `ConversationChunk` objects
   - `get_session_id()` — extract session identifier
   - `get_session_title()` — optional, for better UX
3. Register in `adapters/__init__.py::get_daemon_adapters()` or `get_import_adapters()`
4. Add tests in `tests/test_my_tool_adapter.py`
5. Add an integration guide in `docs/integrations/my-tool.md`

See `memgentic/adapters/claude_code.py` for a reference implementation.

## Code Style

- **Python 3.12+** with `from __future__ import annotations`
- **Pydantic v2** for data models
- **structlog** for all logging (no `print()`)
- **async-first** — use `aiosqlite`, not `sqlite3`
- **Type hints** on all public APIs
- **Ruff** for linting and formatting (config in `pyproject.toml`)

## Commit Message Style

We follow a modified Conventional Commits style:

```
Phase N: short summary

- Bullet point of what changed
- Another bullet
- Third bullet with rationale if non-obvious
```

For non-phase work:
```
Fix: short description

Fixes #123
```

Sign commits with `Co-Authored-By: <model> <noreply@anthropic.com>` if AI-assisted.

## Testing Philosophy

- **Offline-first:** tests must not require Ollama or Qdrant to run in CI
- **Mock external services** (Ollama, OpenAI, etc.)
- **Use `uv run python -m pytest`** not bare `pytest`
- **Target coverage:** >=75% (enforced by `--cov-fail-under=75`)
- **Benchmark tests** are marked with `@pytest.mark.benchmark` and excluded by default

### Running Tests

```bash
uv run python -m pytest                          # All tests
uv run python -m pytest memgentic/tests/         # Core tests only
uv run python -m pytest -x --tb=short            # Stop on first failure
```

## Release Process

1. Update `CHANGELOG.md` with new version section
2. Bump version in `memgentic/memgentic/__version__.py`
3. Tag: `git tag v0.X.Y && git push --tags`
4. GitHub Actions publishes to PyPI via trusted publishing (see `docs/RELEASE.md`)
5. Create GitHub release with CHANGELOG excerpt

## Quality Bar for PRs

- [ ] All 500+ existing tests pass
- [ ] New functionality has tests
- [ ] Ruff lint passes
- [ ] CHANGELOG.md updated if user-visible
- [ ] Docs updated if behavior changed
- [ ] No new dependencies without justification

## Project Structure

```
memgentic/          Core package (adapters, pipeline, search, MCP)
memgentic-api/      REST API (FastAPI)
dashboard/          Web UI (Next.js)
docs/               Technical documentation
```

## Where to Ask Questions

- GitHub Discussions: general questions, feature requests
- GitHub Issues: bug reports, concrete tasks
- Discord: real-time chat (link in README)

## Code of Conduct

Be kind. No harassment. Disagreements are fine, disrespect is not. Report violations to chariton@ellinai.com.

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
