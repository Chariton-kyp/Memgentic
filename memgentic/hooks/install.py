"""Install Memgentic hooks into Claude Code settings.

Adds a SessionStart hook that injects recent memory context at the
beginning of each session. No UserPromptSubmit hook — memory retrieval
is pull-based via MCP tools and SKILL.md subagent.

Usage:
    python -m memgentic.hooks.install [--global]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def get_hook_commands() -> dict[str, str]:
    """Return hook event -> command mappings."""
    hooks_dir = Path(__file__).parent.resolve()
    python = sys.executable
    return {
        "SessionStart": f'"{python}" "{hooks_dir / "session_start.py"}"',
    }


def install_hooks(settings_path: Path) -> None:
    """Add Memgentic hooks to a Claude Code settings file."""
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    hooks = data.setdefault("hooks", {})
    commands = get_hook_commands()

    for event, command in commands.items():
        event_hooks = hooks.setdefault(event, [])

        # Check if already installed
        already = False
        for matcher in event_hooks:
            for h in matcher.get("hooks", []):
                if "memgentic" in h.get("command", ""):
                    already = True
                    break

        if already:
            print(f"  {event}: already installed")
            continue

        event_hooks.append(
            {
                "hooks": [{"type": "command", "command": command}],
            }
        )
        print(f"  {event}: installed")

    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSettings saved to: {settings_path}")


def main() -> None:
    use_global = "--global" in sys.argv

    if use_global:
        settings_path = Path.home() / ".claude" / "settings.json"
        print("Installing Memgentic hooks globally...")
    else:
        settings_path = Path.cwd() / ".claude" / "settings.json"
        print("Installing Memgentic hooks for this project...")

    install_hooks(settings_path)
    print("\nDone. Restart Claude Code to activate hooks.")


if __name__ == "__main__":
    main()
