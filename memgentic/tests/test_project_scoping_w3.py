"""W3 per-project / per-repository scoping tests.

Covers four surfaces:
- ``resolve_current_project`` priority (explicit > session > env > cwd) + the
  global sentinel bypass.
- repo-aware ``project_from_cwd`` / ``project_from_git_repo`` (subdirs of one
  repo collapse to a single key; non-repo dirs fall back to the basename).
- ``memgentic_recall`` scope application: auto-scope to the current project,
  strict vs graceful-fallback semantics, and the ``project='*'`` / global
  bypass.
- capture stamping: ``ingest_single`` writes the project, and
  ``memgentic_remember`` resolves + passes the current project.

Recall tests monkeypatch the module-level ``_execute_recall`` so the scope/
fallback logic is exercised without a live vector store.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.processing.project import (
    is_global_project,
    project_from_cwd,
    project_from_git_repo,
    resolve_current_project,
)

# ---------------------------------------------------------------------------
# resolve_current_project — priority + sentinel
# ---------------------------------------------------------------------------


class TestResolveCurrentProject:
    def test_explicit_wins_over_everything(self) -> None:
        out = resolve_current_project(
            explicit="ExplicitProj",
            session_project="session-proj",
            env={"MEMGENTIC_PROJECT": "env-proj"},
            cwd=r"C:\\some\\cwd-proj",
        )
        assert out == "explicitproj"

    def test_session_wins_over_env_and_cwd(self) -> None:
        out = resolve_current_project(
            session_project="Session_Proj",
            env={"MEMGENTIC_PROJECT": "env-proj"},
            cwd=r"C:\\some\\cwd-proj",
        )
        assert out == "session-proj"

    def test_env_wins_over_cwd(self) -> None:
        out = resolve_current_project(
            env={"MEMGENTIC_PROJECT": "Env-Proj"},
            cwd=r"C:\\some\\cwd-proj",
        )
        assert out == "env-proj"

    def test_cwd_used_when_nothing_else(self) -> None:
        out = resolve_current_project(env={}, cwd=r"C:\\some\\Cwd_Proj")
        assert out == "cwd-proj"

    def test_returns_none_when_nothing_resolves(self) -> None:
        assert resolve_current_project(env={}, cwd=None) is None
        assert resolve_current_project(env={}, cwd="") is None

    def test_blank_values_fall_through(self) -> None:
        out = resolve_current_project(
            explicit="   ",
            session_project="",
            env={"MEMGENTIC_PROJECT": "  "},
            cwd=r"C:\\x\\real-proj",
        )
        assert out == "real-proj"

    @pytest.mark.parametrize("sentinel", ["*", "all", "global", " * ", "ALL"])
    def test_explicit_global_sentinel_forces_none(self, sentinel: str) -> None:
        # An explicit "search everywhere" must beat a lower-priority concrete
        # project rather than fall through to the cwd.
        out = resolve_current_project(
            explicit=sentinel,
            env={"MEMGENTIC_PROJECT": "env-proj"},
            cwd=r"C:\\x\\cwd-proj",
        )
        assert out is None

    def test_session_sentinel_forces_none(self) -> None:
        out = resolve_current_project(
            session_project="*",
            env={"MEMGENTIC_PROJECT": "env-proj"},
            cwd=r"C:\\x\\cwd-proj",
        )
        assert out is None

    # --- Fix 2: cwd sentinel check ------------------------------------------

    def test_cwd_named_sentinel_returns_none(self, tmp_path: Path) -> None:
        """A real cwd directory whose basename is a global sentinel returns None.

        Before the fix, a directory named 'global' would be treated as a
        literal project key rather than the 'go global' escape.
        """
        sentinel_dir = tmp_path / "global"
        sentinel_dir.mkdir()
        out = resolve_current_project(env={}, cwd=str(sentinel_dir))
        assert out is None

    @pytest.mark.parametrize("sentinel_name", ["global", "all"])
    def test_cwd_named_any_sentinel_returns_none(self, tmp_path: Path, sentinel_name: str) -> None:
        """cwd dir names matching a sentinel ('global', 'all') short-circuit to None.

        The '*' sentinel is not a valid directory name on most OS so it is
        tested via monkeypatch rather than a real directory.
        """
        sentinel_dir = tmp_path / sentinel_name
        sentinel_dir.mkdir()
        out = resolve_current_project(env={}, cwd=str(sentinel_dir))
        assert out is None

    def test_cwd_returning_star_sentinel_is_treated_as_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """project_from_cwd returning '*' (pathological) should yield None, not a literal key."""
        import memgentic.processing.project as proj_mod

        monkeypatch.setattr(proj_mod, "project_from_cwd", lambda _cwd: "*")
        out = resolve_current_project(env={}, cwd="/some/cwd")
        assert out is None


class TestIsGlobalProject:
    @pytest.mark.parametrize("value", ["*", "all", "global", "  *  ", "ALL", "Global"])
    def test_true_for_sentinels(self, value: str) -> None:
        assert is_global_project(value) is True

    @pytest.mark.parametrize("value", [None, "", "  ", "vetervo", "memgentic"])
    def test_false_otherwise(self, value: str | None) -> None:
        assert is_global_project(value) is False


# ---------------------------------------------------------------------------
# repo-aware derivation
# ---------------------------------------------------------------------------


class TestRepoAwareDerivation:
    def _make_repo(self, root: Path, name: str) -> Path:
        repo = root / name
        (repo / ".git").mkdir(parents=True)
        return repo

    def test_subdirs_of_repo_map_to_one_key(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path, "MyRepo")
        deep = repo / "backend" / "api"
        deep.mkdir(parents=True)

        root_key = project_from_cwd(str(repo))
        deep_key = project_from_cwd(str(deep))
        assert root_key == deep_key == "myrepo"

    def test_git_worktree_file_marker_is_detected(self, tmp_path: Path) -> None:
        # Worktrees / submodules use a `.git` FILE, not a directory.
        repo = tmp_path / "worktree-proj"
        sub = repo / "pkg"
        sub.mkdir(parents=True)
        (repo / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
        assert project_from_cwd(str(sub)) == "worktree-proj"

    def test_repo_name_is_normalised(self, tmp_path: Path) -> None:
        repo = self._make_repo(tmp_path, "My_Cool Repo")
        assert project_from_git_repo(str(repo)) == "my-cool-repo"

    def test_non_repo_dir_falls_back_to_basename(self, tmp_path: Path) -> None:
        plain = tmp_path / "PlainDir"
        plain.mkdir()
        # No .git anywhere up the (temp) tree → no repo identity.
        assert project_from_git_repo(str(plain)) == ""
        # …but project_from_cwd still yields the basename.
        assert project_from_cwd(str(plain)) == "plaindir"

    def test_foreign_nonexistent_path_uses_basename(self) -> None:
        # A path recorded on another machine doesn't exist locally → no git
        # probe, basename heuristic still works.
        foreign = r"C:\\Users\\someone\\Desktop\\Business_Projects\\Vetervo"
        assert project_from_git_repo(foreign) == ""
        assert project_from_cwd(foreign) == "vetervo"

    # --- Fix 1: worktree .git FILE resolves to main repo name ---------------

    def test_worktree_git_file_resolves_to_main_repo_name(self, tmp_path: Path) -> None:
        """A worktree whose .git FILE points to a live main repo returns the main repo name.

        Before the fix, project_from_git_repo returned the worktree dir name,
        fragmenting the project key across worktrees of the same repo.
        """
        # Create the main repo's .git directory.
        main_repo = tmp_path / "main-repo"
        main_git = main_repo / ".git"
        main_git.mkdir(parents=True)
        # Create the worktree gitdir entry under the main .git directory.
        wt_name = "feat-branch"
        gitdir = main_git / "worktrees" / wt_name
        gitdir.mkdir(parents=True)
        # Create the worktree directory with a .git FILE pointing at the gitdir.
        wt = tmp_path / "feat-branch-worktree"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {gitdir}\n")

        assert project_from_git_repo(str(wt)) == "main-repo"
        # project_from_cwd also resolves to the main repo name.
        assert project_from_cwd(str(wt)) == "main-repo"

    def test_worktree_normal_git_dir_still_returns_repo_name(self, tmp_path: Path) -> None:
        """A normal .git directory (non-worktree checkout) is unchanged by the fix."""
        repo = self._make_repo(tmp_path, "my-project")
        assert project_from_git_repo(str(repo)) == "my-project"

    def test_worktree_git_file_with_missing_main_repo_falls_back(self, tmp_path: Path) -> None:
        """If the main repo can't be found from the gitdir, fall back to the worktree name."""
        wt = tmp_path / "my-worktree"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /nonexistent/repo/.git/worktrees/wt\n")
        # /nonexistent/repo doesn't exist → fall back to worktree dir name.
        assert project_from_git_repo(str(wt)) == "my-worktree"

    def test_worktree_unparseable_git_file_falls_back_gracefully(self, tmp_path: Path) -> None:
        """A .git file without a 'gitdir:' prefix falls back to the worktree dir name."""
        wt = tmp_path / "broken-worktree"
        wt.mkdir()
        (wt / ".git").write_text("this is not a valid gitdir file\n")
        assert project_from_git_repo(str(wt)) == "broken-worktree"


# ---------------------------------------------------------------------------
# memgentic_recall scope application
# ---------------------------------------------------------------------------


def _ctx_with_session(session_id: str = "w3-session") -> MagicMock:
    session = MagicMock(spec=["session_id"])
    session.session_id = session_id
    request_ctx = MagicMock()
    request_ctx.session = session
    state = {
        "metadata_store": AsyncMock(),
        "vector_store": AsyncMock(),
        "embedder": AsyncMock(),
        "graph": None,
    }
    request_ctx.lifespan_context = state
    ctx = MagicMock()
    ctx.request_context = request_ctx
    return ctx


@pytest.fixture(autouse=True)
def _clear_session_state():
    from memgentic.mcp import server

    server._session_configs.clear()
    server._session_contexts.clear()
    yield
    server._session_configs.clear()
    server._session_contexts.clear()


def _result(mid: str) -> dict:
    return {
        "id": mid,
        "relevance": 0.9,
        "payload": {"content": f"content {mid}", "content_type": "fact"},
    }


@pytest.fixture()
def recall_spy(monkeypatch):
    """Patch _execute_recall to record the include_projects used per call.

    ``queue`` is a list of result-lists returned in order (one per call).
    """
    from memgentic.mcp import server

    state = {"calls": [], "queue": []}

    async def fake_execute(*, query, config, limit, min_relevance, **kwargs):
        state["calls"].append(list(config.include_projects) if config.include_projects else None)
        return state["queue"].pop(0) if state["queue"] else []

    monkeypatch.setattr(server, "_execute_recall", fake_execute)
    return state


class TestRecallScoping:
    async def test_auto_scopes_to_current_project(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        recall_spy["queue"] = [[_result("a"), _result("b")]]

        ctx = _ctx_with_session()
        out = await memgentic_recall(RecallInput(query="anything", limit=2), ctx)

        assert "Memory Recall" in out
        # Single call, scoped to the resolved project (full results → no widen).
        assert recall_spy["calls"] == [["myproj"]]

    async def test_strict_returns_nothing_cross_project(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", True)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "emptyproj")
        recall_spy["queue"] = [[]]  # project has nothing

        ctx = _ctx_with_session()
        out = await memgentic_recall(RecallInput(query="anything", limit=5), ctx)

        assert "No memories found" in out
        # Strict: no global fallback.
        assert recall_spy["calls"] == [["emptyproj"]]

    async def test_non_strict_falls_back_to_global(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "emptyproj")
        # First (scoped) call empty, second (global) call has a hit.
        recall_spy["queue"] = [[], [_result("g1")]]

        ctx = _ctx_with_session()
        out = await memgentic_recall(RecallInput(query="anything", limit=5), ctx)

        assert "g1" in out
        # Scoped first, then widened to global (include_projects=None).
        assert recall_spy["calls"] == [["emptyproj"], None]

    async def test_partial_results_also_widen(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        # 1 scoped hit but limit=3 → widen and merge (dedup keeps order).
        recall_spy["queue"] = [[_result("a")], [_result("a"), _result("b"), _result("c")]]

        ctx = _ctx_with_session()
        out = await memgentic_recall(RecallInput(query="anything", limit=3), ctx)

        assert recall_spy["calls"] == [["myproj"], None]
        # Merged + de-duped: a (scoped) then b, c (global), no duplicate a.
        for mid in ("a", "b", "c"):
            assert mid in out

    async def test_global_sentinel_bypasses_scope(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        recall_spy["queue"] = [[_result("x")]]

        ctx = _ctx_with_session()
        await memgentic_recall(RecallInput(query="anything", project="*"), ctx)

        # project='*' forces global despite the env project; single unscoped call.
        assert recall_spy["calls"] == [None]

    async def test_explicit_project_is_strict_no_fallback(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        recall_spy["queue"] = [[]]  # explicit project empty

        ctx = _ctx_with_session()
        out = await memgentic_recall(RecallInput(query="anything", project="vetervo", limit=5), ctx)

        # Explicit choice honoured strictly — no auto widen to global.
        assert recall_spy["calls"] == [["vetervo"]]
        assert "No memories found" in out

    async def test_global_scope_setting_disables_scoping(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "global")
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        recall_spy["queue"] = [[_result("x")]]

        ctx = _ctx_with_session()
        await memgentic_recall(RecallInput(query="anything"), ctx)

        assert recall_spy["calls"] == [None]

    async def test_session_project_is_honoured(self, recall_spy, monkeypatch):
        from memgentic.mcp import server
        from memgentic.mcp.server import (
            RecallInput,
            SessionConfig,
            memgentic_recall,
        )

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "env-proj")
        recall_spy["queue"] = [[]]

        ctx = _ctx_with_session()
        server._set_session_config("w3-session", SessionConfig(include_projects=["session-proj"]))

        await memgentic_recall(RecallInput(query="anything", limit=5), ctx)

        # Session-configured project wins over the env auto-resolution and is
        # honoured strictly (no widen).
        assert recall_spy["calls"] == [["session-proj"]]

    # --- Fix 2: session include_projects sentinel forces global recall -------

    @pytest.mark.parametrize("sentinel", ["*", "all", "global"])
    async def test_session_include_projects_sentinel_forces_global_recall(
        self, sentinel, recall_spy, monkeypatch
    ):
        """A sentinel value in the session include_projects list forces global recall.

        Before the fix, '*' was treated as a literal project-key filter (SQL
        WHERE project IN ('*')) which returns 0 results, not a global search.
        """
        from memgentic.mcp import server
        from memgentic.mcp.server import RecallInput, SessionConfig, memgentic_recall

        monkeypatch.setattr(server.settings, "recall_scope", "project")
        monkeypatch.setattr(server.settings, "recall_scope_strict", False)
        monkeypatch.setenv("MEMGENTIC_PROJECT", "myproj")
        recall_spy["queue"] = [[_result("global-hit")]]

        ctx = _ctx_with_session()
        # Session configured with a sentinel → should force a global (unscoped) search.
        server._set_session_config("w3-session", SessionConfig(include_projects=[sentinel]))

        out = await memgentic_recall(RecallInput(query="anything"), ctx)

        assert "global-hit" in out
        # Sentinel wins: single call with include_projects=None (global).
        assert recall_spy["calls"] == [None]


# ---------------------------------------------------------------------------
# capture stamping
# ---------------------------------------------------------------------------

_DIMS = 768


@pytest.fixture()
def _pipeline_embedder():
    embedder = AsyncMock()
    vec = [0.1 + i * 0.0001 for i in range(_DIMS)]
    embedder.embed.return_value = vec
    embedder.embed_query = embedder.embed
    embedder.embed_document = embedder.embed
    embedder.embed_batch.side_effect = lambda texts: [vec for _ in texts]
    embedder.embed_batch_documents = embedder.embed_batch
    return embedder


@pytest.fixture()
async def pipeline(tmp_path, metadata_store, _pipeline_embedder):
    """IngestionPipeline with a real MetadataStore + mocked embedder/vectors."""
    from memgentic.config import MemgenticSettings, StorageBackend
    from memgentic.processing.pipeline import IngestionPipeline

    settings = MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=_DIMS,
    )
    vectors = AsyncMock()
    return IngestionPipeline(
        settings=settings,
        metadata_store=metadata_store,
        vector_store=vectors,
        embedder=_pipeline_embedder,
    )


class TestIngestSingleStampsProject:
    async def test_project_is_stored(self, pipeline) -> None:
        memory = await pipeline.ingest_single(content="a scoped fact", project="MyProj")
        assert memory.project == "myproj"
        loaded = await pipeline._metadata.get_memory(memory.id)
        assert loaded is not None
        assert loaded.project == "myproj"

    async def test_no_project_is_empty(self, pipeline) -> None:
        memory = await pipeline.ingest_single(content="an unscoped fact")
        assert memory.project == ""


class TestRememberStampsProject:
    async def test_remember_passes_resolved_project(self, monkeypatch) -> None:
        from memgentic.mcp.server import RememberInput, memgentic_remember

        monkeypatch.setenv("MEMGENTIC_PROJECT", "RememberProj")

        pipeline = AsyncMock()
        from datetime import UTC, datetime

        from memgentic.models import (
            CaptureMethod,
            ContentType,
            Memory,
            Platform,
            SourceMetadata,
        )

        pipeline.ingest_single.return_value = Memory(
            id="m-1",
            content="x",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.MCP_TOOL,
                original_timestamp=datetime.now(UTC),
            ),
        )
        ctx = _ctx_with_session()
        ctx.request_context.lifespan_context = {"pipeline": pipeline}

        await memgentic_remember(RememberInput(content="remember this", source="claude_code"), ctx)

        pipeline.ingest_single.assert_awaited_once()
        assert pipeline.ingest_single.call_args.kwargs["project"] == "rememberproj"
