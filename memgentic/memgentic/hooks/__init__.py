"""Memgentic hooks for Claude Code integration.

Shell hooks that auto-inject memory context into Claude Code sessions:
- UserPromptSubmit: searches for relevant memories on each prompt
- SessionStart: injects recent cross-tool activity summary
"""
