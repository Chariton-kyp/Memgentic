# Memgentic Guard — Getting Started

**Deterministic Agentic CI.** Guard checks the diffs your AI agents (and you)
write against architectural rules **you** define in a `decisions.yaml` file. It
parses the diff and applies your rules — no LLM in the enforcement path, so the
same diff always produces the same result.

Guard reports only **introduced** violations. A banned import, dependency, or
`using` namespace that already exists on the base branch is treated as
pre-existing and is **not** flagged — only what your branch adds fires the
check. (Exception: `forbidden_path` always fires when a forbidden path is
touched, since the point is "never commit or modify this file".)

---

## Installation

```bash
pip install memgentic
```

Guard works out of the box with no extra dependencies. The optional
`guard suggest` command (LLM-assisted rule drafting) needs the intelligence
extra:

```bash
pip install "memgentic[intelligence]"
```

---

## Quickstart

```bash
memgentic guard init                 # writes a starter decisions.yaml
# edit decisions.yaml — uncomment and tailor the rules you want
memgentic guard                      # check the current branch against its base
memgentic guard install-hook         # run guard automatically before each commit
```

`guard init` writes a fully-commented template — nothing is enforced until you
uncomment and edit rules. It refuses to overwrite an existing `decisions.yaml`.

---

## Writing rules

A `decisions.yaml` is a list of rules:

```yaml
rules:
  - id: <unique-id>
    type: <import_direction | banned_import | banned_dependency | forbidden_path>
    scope: "<glob>"          # optional, default "**" (all files)
    targets: ["<thing>", …]  # what the rule checks (semantics vary by type)
    message: "<shown on violation>"
    severity: <error | warn> # optional, default "error"
```

### `import_direction` — enforce dependency direction

Forbid a layer from importing other layers. Use it to keep a core package free
of upward dependencies.

```yaml
  - id: core-is-the-root
    type: import_direction
    scope: "core/**"            # only files under core/
    targets: ["app", "web"]     # core/ must not import the app or web layers
    message: "core is the dependency root — it must not import app/web."
    severity: error
```

Covers Python (`import` / `from`) and C# (`using`). The check skips imports
inside `if TYPE_CHECKING:` blocks and under `try: import … except ImportError:`
guards, and skips Python test files (so tests can import freely).

### `banned_import` — forbid specific modules

```yaml
  - id: no-requests
    type: banned_import
    targets: ["requests"]       # ban `import requests` / `from requests import …`
    message: "Use httpx, not requests (async-friendly)."
    severity: error
```

For C#, the same rule matches `using` namespaces — `targets: ["MediatR"]` bans
`using MediatR;` (and `using MediatR.Extensions.X;`) in any `.cs` file in scope.
Python test files are exempt; C# rules apply in tests too (scope your globs if
you need to exclude them).

### `banned_dependency` — forbid adding a package to a manifest

```yaml
  - id: no-moment
    type: banned_dependency
    targets: ["moment"]         # ban adding `moment` to package.json
    message: "moment is in maintenance mode — use date-fns or Temporal."
    severity: error
```

Checks `pyproject.toml`, `package.json`, `requirements.txt`, `*.csproj`, and
`Directory.Packages.props`. Package names are matched canonically (PEP 503:
case-insensitive, `-`/`_`/`.` collapsed) for Python manifests.

### `forbidden_path` — forbid touching files

```yaml
  - id: no-committed-secrets
    type: forbidden_path
    targets: ["**/.env", "**/*.pem"]
    message: "Secrets must not be committed."
    severity: error
```

Fires when the diff adds, modifies, **or** deletes a matching path. Targets are
`fnmatch` globs. A leading `**/` matches at any depth including the repo root,
so `**/.env` catches both `.env` and `sub/dir/.env` while leaving
`.env.example` alone (different basename).

---

## Scope globs

Every rule's `scope` (default `**`) restricts which files are considered before
the rule runs. Scopes are `fnmatch` globs evaluated against the repo-relative
path. Common patterns:

| Scope | Matches |
|-------|---------|
| `**` | everything (default) |
| `core/**` | every file under `core/` |
| `src/**/*.py` | Python files anywhere under `src/` |
| `services/payments/**` | one service subtree |

---

## Severity and exit codes

| Severity | Behavior |
|----------|----------|
| `error` (default) | printed and **fails** the run (exit 1) |
| `warn` | printed but does **not** fail (exit 0) |

| Exit code | Meaning |
|-----------|---------|
| `0` | clean (or only warnings) |
| `1` | at least one `error`-severity violation |
| `2` | guard/config error — not a git repo, missing explicit `--rules` file, malformed YAML |

---

## Running in pre-commit and CI

### Pre-commit hook

```bash
memgentic guard install-hook        # writes .git/hooks/pre-commit (honors core.hooksPath)
memgentic guard install-hook --force        # back up an existing hook to pre-commit.backup
memgentic guard install-hook --uninstall    # remove (only if it's ours)
```

The installed hook runs `memgentic guard --staged` with the same Python
interpreter you installed from, forces `PYTHONIOENCODING=utf-8`, and **fails
open** (exit 0 with a note) if that interpreter is later removed — so a
relocated virtualenv never wedges your commits. It blocks a commit only on an
`error`-severity violation.

### CI

Run guard against the pull request's base branch and let the exit code gate the
job:

```bash
memgentic guard --base "origin/${GITHUB_BASE_REF:-main}" --format json
```

`--format json` emits a machine-readable `{ "violation_count": N, "violations": [...] }`
payload for annotations or dashboards. Use `--repo <path>` to point at a
checkout other than the current directory.

---

## LLM-assisted drafting — `guard suggest`

```bash
memgentic guard suggest --repo .                  # uses the configured provider chain
memgentic guard suggest --repo . --model qwen3.6:35b-a3b
```

`guard suggest` reads your prose rule files (`AGENTS.md`, `CLAUDE.md`, Cursor
rules, ADRs) and proposes machine-checkable rules as ready-to-paste YAML on
stdout. It **never** writes a file and **never** enforces — you review the
output and save it as `decisions.yaml` yourself.

It requires the `[intelligence]` extra and a reachable LLM provider. A local
Ollama install works out of the box; cloud providers (Gemini, Anthropic,
OpenAI-compatible) work when configured. Smaller local models are fine for
drafting since you review every proposal.

---

## Troubleshooting

**`Not a git repository`** — Guard diffs against git history, so it must run
inside a repo. `cd` into the repo or pass `--repo <path>`.

**`No rules at …/decisions.yaml`** — There's no rules file yet. Run
`memgentic guard init` to scaffold one (or `guard suggest` to draft from your
existing docs). With no rules file and no `--rules` flag, guard exits 0.

**Base branch not found** — If your default branch isn't `main`, pass
`--base <branch>` (e.g. `--base master` or `--base origin/develop`).

**Windows / Greek (cp1253) console shows `[X]` / `[WARN]` instead of `✗` / `⚠`**
— That's expected and intentional. When stdout can't encode the Unicode glyphs,
guard automatically falls back to ASCII markers (`[OK]` / `[X]` / `[WARN]`)
instead of crashing with a `UnicodeEncodeError`. Set `PYTHONIOENCODING=utf-8`
(or use a UTF-8 console) to get the pretty glyphs back.

---

## Roadmap (not yet supported)

- **TypeScript / JavaScript import direction** — `banned_import` does not yet
  parse TS/JS imports; only Python and C# imports are analyzed.
- **C# project-reference direction** — `import_direction` checks `using`
  namespaces, not `.csproj` `<ProjectReference>` edges.
