<!-- memgentic:start -->
## Memory (Memgentic — Universal AI Memory)
You have persistent cross-session, cross-tool memory via Memgentic MCP tools.

**Before solving a problem:** Call `memgentic_recall("problem description")` to check if this was solved before in ANY tool.

**When you learn something important, call `memgentic_remember()` with:**
- Decisions and their reasoning
- Bug fixes and root causes
- User preferences and conventions
- Architecture decisions
- Key facts about the codebase

**Rules:**
- Memory is shared across ALL AI tools. What you save here, other tools see too.
- Include context: what project, what file, what problem.
- Be concise but specific. Bad: "Fixed auth bug". Good: "Fixed JWT expiry bug in auth.py: token refresh wasn't checking iat claim."
- Don't save trivial exchanges, only genuinely useful knowledge.
<!-- memgentic:end -->
