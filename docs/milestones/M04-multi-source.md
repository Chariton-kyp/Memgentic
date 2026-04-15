# M4: Multi-Source Adapters

> Support automatic capture from 6+ AI tools.

**Prerequisites:** M2 (Production Core)
**Estimated complexity:** Medium
**Can run in parallel with:** M3 (REST API), M5 (Intelligence)
**Exit criteria:** All 7 adapters working, daemon watches all paths, import-existing handles all sources.

---

## Phase 4.1: Gemini CLI Adapter

**Goal:** Parse conversations from `~/.gemini/tmp/*/chats/`.

### Research

- Gemini CLI stores conversations in JSON format
- Project-specific hash directories under `~/.gemini/tmp/`
- Each chat is a JSON file with turns
- 30-day default retention (configurable in Gemini CLI settings)

### Tasks

1. **Create `memgentic/memgentic/adapters/gemini_cli.py`:**
   - `platform = Platform.GEMINI_CLI`
   - `watch_paths = [Path.home() / ".gemini" / "tmp"]`
   - `file_patterns = ["*.json"]`
   - Parse JSON conversation format
   - Extract turns (user/model roles)
   - Handle multi-modal content (text only, skip images)

2. **Register adapter in daemon and CLI:**
   - Add to adapter list in `cli.py` daemon command
   - Add to import-existing command

3. **Create tests:**
   - `memgentic/tests/test_gemini_cli_adapter.py`
   - Test with sample JSON conversation files

### Files to Create
- `memgentic/memgentic/adapters/gemini_cli.py`
- `memgentic/tests/test_gemini_cli_adapter.py`

### Acceptance Criteria
- [ ] Adapter parses Gemini CLI JSON conversations
- [ ] Daemon watches `~/.gemini/tmp/` recursively
- [ ] Import-existing discovers and imports Gemini conversations
- [ ] Tests pass with sample data

---

## Phase 4.2: ChatGPT JSON Import Adapter

**Goal:** Parse exported conversations from ChatGPT (conversations.json).

### Research

- ChatGPT export: Settings → Data Controls → Export Chat History
- Produces a `conversations.json` file with all conversations
- Each conversation has: `title`, `create_time`, `mapping` (nested turn tree)
- Turns have `author.role` (system/user/assistant/tool) and `content.parts`

### Tasks

1. **Create `memgentic/memgentic/adapters/chatgpt_import.py`:**
   - `platform = Platform.CHATGPT`
   - `watch_paths = []` (import-only, no file watching)
   - `file_patterns = ["conversations.json"]`
   - Parse the nested mapping structure
   - Flatten turn tree into chronological order
   - Extract text from `content.parts` (skip image references)
   - Use `create_time` as `original_timestamp`
   - Use conversation `title` as `session_title`

2. **Add CLI import command for ChatGPT:**
   ```bash
   memgentic import-chatgpt /path/to/conversations.json
   ```

3. **Create tests with realistic sample data**

### Files to Create
- `memgentic/memgentic/adapters/chatgpt_import.py`
- `memgentic/tests/test_chatgpt_adapter.py`

### Acceptance Criteria
- [ ] Can import a full ChatGPT export file
- [ ] Preserves conversation titles and timestamps
- [ ] Handles multi-turn conversations with correct ordering
- [ ] Tests pass

---

## Phase 4.3: Aider Adapter

**Goal:** Parse `.aider.chat.history.md` files.

### Research

- Aider stores chat history as Markdown per project directory
- File: `.aider.chat.history.md` in the project root
- Format: Markdown with `#### user` / `#### assistant` headers
- Also: `.aider.input.history` (just user prompts)
- Very simple, plain text

### Tasks

1. **Create `memgentic/memgentic/adapters/aider.py`:**
   - `platform = Platform.AIDER`
   - `watch_paths = []` (user configures per-project)
   - `file_patterns = [".aider.chat.history.md"]`
   - Parse Markdown headers to identify turns
   - Group into exchanges

2. **Add configurable watch paths:**
   - Allow users to specify Aider project paths in config
   - Scan common locations

3. **Create tests**

### Files to Create
- `memgentic/memgentic/adapters/aider.py`
- `memgentic/tests/test_aider_adapter.py`

### Acceptance Criteria
- [ ] Parses Aider Markdown chat history
- [ ] Groups exchanges correctly
- [ ] Tests pass

---

## Phase 4.4: Codex CLI Adapter

**Goal:** Parse conversations from `~/.codex/sessions/`.

### Research

- Codex CLI stores sessions in SQLite + Markdown
- `~/.codex/sessions/` directory
- Each session is a directory with `session.db` (SQLite) and `conversation.md`
- SQLite contains structured data, Markdown is human-readable

### Tasks

1. **Create `memgentic/memgentic/adapters/codex_cli.py`:**
   - `platform = Platform.CODEX_CLI`
   - `watch_paths = [Path.home() / ".codex" / "sessions"]`
   - `file_patterns = ["conversation.md", "*.md"]`
   - Parse the Markdown conversation file
   - Optionally read SQLite for richer metadata

2. **Create tests**

### Files to Create
- `memgentic/memgentic/adapters/codex_cli.py`
- `memgentic/tests/test_codex_cli_adapter.py`

### Acceptance Criteria
- [ ] Parses Codex CLI conversations
- [ ] Daemon watches `~/.codex/sessions/`
- [ ] Tests pass

---

## Phase 4.5: Copilot CLI Adapter

**Goal:** Parse conversations from `~/.copilot/session-state/`.

### Research

- Copilot CLI stores session state in JSON
- `~/.copilot/session-state/` directory
- Ephemeral — files may be cleaned up quickly
- JSON format with messages array

### Tasks

1. **Create `memgentic/memgentic/adapters/copilot_cli.py`:**
   - `platform = Platform.COPILOT_CLI`
   - `watch_paths = [Path.home() / ".copilot" / "session-state"]`
   - `file_patterns = ["*.json"]`
   - Parse JSON session files
   - Handle ephemeral nature (capture quickly before cleanup)

2. **Create tests**

### Files to Create
- `memgentic/memgentic/adapters/copilot_cli.py`
- `memgentic/tests/test_copilot_cli_adapter.py`

### Acceptance Criteria
- [ ] Parses Copilot CLI JSON sessions
- [ ] Daemon watches the session-state directory
- [ ] Tests pass

---

## Phase 4.6: Antigravity Adapter

**Goal:** Import Protocol Buffer conversations from `~/.gemini/antigravity/conversations/`.

### Research

- Antigravity (Google's coding agent) stores conversations in `.pb` files
- Protocol Buffer binary format
- PyPI package `antigravity-history` exists for export
- Can use protobuf library to parse

### Tasks

1. **Add `protobuf` dependency to memgentic** (conditional/optional)

2. **Create `memgentic/memgentic/adapters/antigravity.py`:**
   - `platform = Platform.ANTIGRAVITY`
   - `watch_paths = [Path.home() / ".gemini" / "antigravity" / "conversations"]`
   - `file_patterns = ["*.pb"]`
   - Investigate if `antigravity-history` provides proto definitions
   - If not, try to reverse-engineer the format or use raw protobuf parsing

3. **Create tests** (may need actual .pb sample files)

### Files to Create
- `memgentic/memgentic/adapters/antigravity.py`
- `memgentic/tests/test_antigravity_adapter.py`

### Acceptance Criteria
- [ ] Can parse Antigravity .pb files
- [ ] Extracts conversation turns
- [ ] Tests pass (at least with mock data)

---

## Phase 4.7: Claude Web/Desktop Import

**Goal:** Import exported conversations from Claude web and desktop apps.

### Tasks

1. **Create `memgentic/memgentic/adapters/claude_web_import.py`:**
   - `platform = Platform.CLAUDE_WEB` / `Platform.CLAUDE_DESKTOP`
   - Parse exported JSON from claude.ai
   - Handle the conversation export format
   - Extract turns, timestamps, titles

2. **Add CLI command:**
   ```bash
   memgentic import-claude /path/to/export.json
   ```

### Files to Create
- `memgentic/memgentic/adapters/claude_web_import.py`
- `memgentic/tests/test_claude_web_adapter.py`

---

## Phase 4.8: Adapter Registration System

**Goal:** Clean adapter discovery and registration.

### Tasks

1. **Create adapter registry in `adapters/__init__.py`:**
   ```python
   def get_all_adapters() -> list[BaseAdapter]:
       return [
           ClaudeCodeAdapter(),
           GeminiCliAdapter(),
           AiderAdapter(),
           CodexCliAdapter(),
           CopilotCliAdapter(),
       ]

   def get_import_adapters() -> list[BaseAdapter]:
       return get_all_adapters() + [
           ChatGPTImportAdapter(),
           AntigravityAdapter(),
           ClaudeWebImportAdapter(),
       ]
   ```

2. **Update CLI and daemon to use registry**
3. **Update daemon to skip adapters whose watch paths don't exist**

### Acceptance Criteria
- [ ] All adapters registered centrally
- [ ] Daemon uses all available adapters
- [ ] Import uses all adapters including import-only ones
