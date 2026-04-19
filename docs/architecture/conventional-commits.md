# Conventional Commits — Memgentic Reference

> Every commit that lands on `main` MUST follow the Conventional
> Commits 1.0 spec. Our release automation
> ([release-automation.md](./release-automation.md)) parses this stream
> to decide version bumps and build the CHANGELOG.
>
> This file is the **canonical reference** for what we accept. PR titles
> are validated in CI; individual commits are validated locally via
> pre-commit.

## Format

```
<type>(<scope>)<!>: <subject>

<body>

<footer>
```

- **`<type>`**: one of the types in the table below. Required.
- **`<scope>`**: optional, one of our approved scopes (see below).
  Omit if the change is genuinely global.
- **`<!>`**: optional `!` after type/scope = breaking change. Always
  combined with a `BREAKING CHANGE:` footer for full context.
- **`<subject>`**: imperative, ≤72 chars, no trailing period.
  Example: `add async batch upsert`, not `added async batch upsert` or
  `Adds the new async batch upsert method.`
- **`<body>`**: optional, wraps at 100 chars. Explain the *why*, not
  the *what* — the diff shows the what.
- **`<footer>`**: optional. Uses git-trailer syntax. Recognized:
  - `BREAKING CHANGE: <description>` — required for every `!` commit
  - `Closes #N`, `Fixes #N`, `Refs #N`
  - `Co-Authored-By: Name <email>`
  - `Release-As: X.Y.Z` — force release-please to use this version
    (escape hatch, rarely used)

## Types and their release effect

| Type | Bump (pre-1.0) | Bump (post-1.0) | CHANGELOG section |
| --- | --- | --- | --- |
| `feat` | minor | minor | Features |
| `fix` | patch | patch | Bug Fixes |
| `perf` | patch | patch | Performance |
| `revert` | patch | patch | Reverts |
| `refactor` | none | none | — (or "Code Refactoring" if configured) |
| `docs` | none | none | — |
| `test` | none | none | — |
| `build` | none | none | — |
| `ci` | none | none | — |
| `chore` | none | none | — |
| `style` | none | none | — |
| `!` (breaking) on any type | **minor** | **major** | Breaking Changes |

**Why minor for breaking pre-1.0?** SemVer 2.0 allows breaking changes
on `0.X.Y` bumps; we treat `0.X → 0.(X+1)` as the breaking-change
signal so users have a predictable lane. `0.X.Y → 0.X.(Y+1)` remains
backward-compatible within a minor.

## Scopes (pick one, lowercase)

### Package scopes

- `core` — general changes to the `memgentic` core package
- `api` — `memgentic-api` REST layer
- `native` — `memgentic-native` Rust crate

### Subsystem scopes (within core)

- `cli` — the CLI entry point (`memgentic/cli.py`)
- `mcp` — MCP server (`memgentic/mcp/`)
- `daemon` — file watcher daemon
- `sqlite-vec` — sqlite-vec backend
- `qdrant` — Qdrant backend
- `storage` — generic storage concerns
- `embedder` — embedding pipeline
- `intelligence` — LLM classification / distillation
- `adapters` — AI-tool file format adapters
- `doctor` — `memgentic doctor` command
- `setup` / `init` — onboarding wizards
- `security` — scrubber, credential handling

### Infrastructure scopes

- `ci` — GitHub Actions
- `release` — release workflows specifically
- `deps` — dependency bumps (Dependabot uses this)
- `docs` — documentation
- `tests` — test fixtures, infra
- `dx` — developer experience (pre-commit, editor configs)

If your change doesn't fit any scope cleanly, omit the scope. Don't
invent new scopes silently — open a PR to this file first.

## Examples

### Features

```
feat(sqlite-vec): add async batch upsert
```

```
feat(doctor): detect GPU memory and recommend embedding tier

Reads nvidia-smi output (Linux) and wmic (Windows) to estimate VRAM.
Uses the result to pick between qwen3-embedding:0.6b and the 4B variant.
```

### Fixes

```
fix(mcp): redirect structlog to stderr so stdio stream stays clean JSON-RPC
```

```
fix(daemon): reclaim stale .daemon.pid when the holder is dead

Closes #99.
```

### Breaking changes

```
feat(config)!: default storage_backend is now sqlite_vec

BREAKING CHANGE: `MEMGENTIC_STORAGE_BACKEND` defaults to `sqlite_vec`
(was `local`). Existing 0.5.x users must run `memgentic migrate-storage
--from local --to sqlite_vec` once or explicitly set the env var back.
```

### Performance

```
perf(sqlite-vec): over-fetch KNN candidates so filters don't starve recall
```

### Chore / docs (no release impact)

```
docs(architecture): add release-automation spec
```

```
chore(deps): bump structlog 25.0 → 26.0
```

```
ci: pin ossf/scorecard-action to a real SHA (v2.4.3)
```

## Anti-patterns

These are commit messages that will fail commitlint:

- ❌ `Fix bug` — missing type, missing scope
- ❌ `Fixed the daemon crash` — past tense
- ❌ `feat: Added async upsert.` — past tense + trailing period
- ❌ `feat: add this thing and also fix that other thing` — one commit, one reason
- ❌ `WIP` — squash-merge away any WIP commits before landing
- ❌ Blank subject: `feat: ` — subject required
- ❌ `feat(SQLite-Vec):` — scope must be lowercase
- ❌ `Feat(core):` — type must be lowercase

## Special footers

### `BREAKING CHANGE:`

Required when the `!` marker is used. Describes what broke and the
migration path in 1-3 lines. Goes into the CHANGELOG's "Breaking
Changes" section verbatim.

```
feat(api)!: rename `list_memories` endpoint to `search_memories`

BREAKING CHANGE: `/v1/list_memories` now returns 410 Gone. Clients
must move to `/v1/search_memories`. The response shape is unchanged.
```

### `Release-As:`

Escape hatch for when release-please's computed bump is wrong (e.g.
you want to cut `1.0.0` from a `feat:` commit pre-1.0):

```
feat(api): stable public API

Release-As: 1.0.0
```

Use sparingly — it sidesteps the automation's intent.

### `Closes` / `Fixes` / `Refs`

Auto-closes linked issues on PR merge. Standard GitHub behavior.

## Authoring tips

### Local commits

Install the commitizen pre-commit hook (described in the release
automation doc) and either:

- Write commit messages by hand — the hook validates on commit.
- Use `cz commit` — interactive wizard that builds a valid message.

### In PRs

The PR **title** is what gets squash-merged. Keep it valid — CI
blocks invalid titles. Individual commits within the PR are lenient;
squash lets you stage messy WIP commits locally and land a single
clean one.

### Long-running branches

Before opening the PR, rewrite the branch so the final commit
message (or PR title) is conventional. `git commit --amend` and
`git rebase -i` are your friends.

## Validation

- **commitlint CI**: runs on every PR, blocks invalid PR titles.
- **commitizen pre-commit**: runs locally when you `git commit`
  (after the pre-commit hook PR lands).
- **release-please**: parses the stream; non-conforming commits are
  silently ignored (worst-case outcome: your feature doesn't get a
  CHANGELOG entry).

## References

- [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [Angular commit format](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md) — our conventions are compatible
- [commitlint/config-conventional](https://github.com/conventional-changelog/commitlint/tree/master/@commitlint/config-conventional)
- [release-please commit parsing](https://github.com/googleapis/release-please/blob/main/docs/customizing.md#how-release-please-parses-commits)
