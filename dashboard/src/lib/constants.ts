/** Platform colors, icons, and display names. */

export const PLATFORM_CONFIG: Record<
  string,
  { label: string; color: string; bgColor: string }
> = {
  claude_code: { label: "Claude Code", color: "#D97706", bgColor: "bg-amber-100 dark:bg-amber-900/30" },
  claude_web: { label: "Claude Web", color: "#D97706", bgColor: "bg-amber-100 dark:bg-amber-900/30" },
  chatgpt: { label: "ChatGPT", color: "#10A37F", bgColor: "bg-emerald-100 dark:bg-emerald-900/30" },
  gemini_cli: { label: "Gemini CLI", color: "#4285F4", bgColor: "bg-blue-100 dark:bg-blue-900/30" },
  aider: { label: "Aider", color: "#8B5CF6", bgColor: "bg-violet-100 dark:bg-violet-900/30" },
  codex_cli: { label: "Codex CLI", color: "#EF4444", bgColor: "bg-red-100 dark:bg-red-900/30" },
  copilot_cli: { label: "Copilot CLI", color: "#6366F1", bgColor: "bg-indigo-100 dark:bg-indigo-900/30" },
  unknown: { label: "Unknown", color: "#6B7280", bgColor: "bg-gray-100 dark:bg-gray-900/30" },
};

export const CONTENT_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  fact: { label: "Fact", color: "bg-blue-500" },
  decision: { label: "Decision", color: "bg-purple-500" },
  code_snippet: { label: "Code", color: "bg-green-500" },
  preference: { label: "Preference", color: "bg-yellow-500" },
  learning: { label: "Learning", color: "bg-cyan-500" },
  action_item: { label: "Action Item", color: "bg-red-500" },
  raw_exchange: { label: "Exchange", color: "bg-gray-500" },
  conversation_summary: { label: "Summary", color: "bg-indigo-500" },
};

export function getPlatformConfig(platform: string) {
  return PLATFORM_CONFIG[platform] || PLATFORM_CONFIG.unknown;
}

export function getContentTypeConfig(type: string) {
  return CONTENT_TYPE_CONFIG[type] || { label: type, color: "bg-gray-500" };
}
