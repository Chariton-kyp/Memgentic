import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

export const metadata: Metadata = {
  title: "Memgentic — Universal AI memory, across every tool you use",
  description:
    "One memory layer across Claude Code, Cursor, Gemini CLI, Codex, ChatGPT, Aider, and more. Local-first. Dashboard-first. Team-ready. Apache 2.0.",
};

// ---------------------------------------------------------------------------
// Data — kept inline so this page is a pure, static render with no API calls.
// The Watchers matrix mirrors the README matrix exactly (same 9 rows, same
// wording) so marketing and docs can't drift.
// ---------------------------------------------------------------------------

type RecallTier = {
  id: string;
  name: string;
  tagline: string;
  defaultLoad: string;
  budget: string;
  source: string;
};

const RECALL_TIERS: RecallTier[] = [
  {
    id: "T0",
    name: "Persona",
    tagline: "Who the agent is",
    defaultLoad: "Always",
    budget: "~100 tokens",
    source: "~/.memgentic/persona.yaml",
  },
  {
    id: "T1",
    name: "Horizon",
    tagline: "Top memories + top skills",
    defaultLoad: "Always",
    budget: "400–1500 tokens",
    source: "importance × recency × pinned × cluster × skill-link, MMR λ=0.5",
  },
  {
    id: "T2",
    name: "Orbit",
    tagline: "Scoped by collection or topic",
    defaultLoad: "On match",
    budget: "200–500 tokens per call",
    source: "Collection / topic filter over metadata store",
  },
  {
    id: "T3",
    name: "Deep Recall",
    tagline: "Full hybrid search",
    defaultLoad: "Explicit",
    budget: "Unlimited",
    source: "Semantic vectors + FTS5 keyword, RRF-fused",
  },
  {
    id: "T4",
    name: "Atlas",
    tagline: "Knowledge-graph traversal",
    defaultLoad: "On KG query",
    budget: "Variable",
    source: "Chronograph bitemporal triples (valid_from / valid_to)",
  },
];

type WatcherRow = {
  tool: string;
  mechanism: string;
  status: "Shipped" | "Planned";
  notes: string;
};

// Keep this in sync with the Watchers matrix in README.md.
const WATCHER_ROWS: WatcherRow[] = [
  {
    tool: "Claude Code",
    mechanism: "Hook (Stop, PreCompact, SessionStart, UserPromptSubmit)",
    status: "Shipped",
    notes:
      "Edits ~/.claude/settings.json; SessionStart injects T0+T1 briefing",
  },
  {
    tool: "Codex CLI",
    mechanism: "Hook (Stop, PreCompact)",
    status: "Shipped",
    notes: "Edits ~/.codex/hooks.json",
  },
  {
    tool: "Gemini CLI",
    mechanism: "File watcher (JSONL tail)",
    status: "Shipped",
    notes:
      "Watches ~/.gemini/tmp/*/chats/*.json; delta-only via last_offset",
  },
  {
    tool: "Copilot CLI",
    mechanism: "File watcher (log appends)",
    status: "Shipped",
    notes: "Parses ~/.copilot/... log stream",
  },
  {
    tool: "Aider",
    mechanism: "File watcher (markdown appends)",
    status: "Shipped",
    notes:
      "Parses <project>/.aider.chat.history.md by session header",
  },
  {
    tool: "ChatGPT import",
    mechanism: "One-shot import (JSON)",
    status: "Shipped",
    notes: "memgentic import chatgpt <export.json>",
  },
  {
    tool: "Claude Web import",
    mechanism: "One-shot import (JSON)",
    status: "Shipped",
    notes: "memgentic import claude-web <export.json>",
  },
  {
    tool: "Cursor",
    mechanism: "MCP (agent-initiated)",
    status: "Shipped",
    notes:
      "No file watcher — Cursor's agent calls memgentic_remember / memgentic_recall directly",
  },
  {
    tool: "Antigravity",
    mechanism: "File watcher + protobuf decode",
    status: "Shipped",
    notes:
      "Watches ~/.gemini/antigravity/conversations/; schema-pinned, graceful skip on mismatch",
  },
];

// Comparison rows are verified against README.md's "How Memgentic compares"
// table (itself verified against each project's current public README,
// April 2026). Where a row can't be verified upstream we use a generic label
// ("typical single-tool memory") rather than an unattributed claim.
type ComparisonRow = {
  capability: string;
  memgentic: string;
  singleTool: string;
  verbatimLocal: string;
};

const COMPARISON_ROWS: ComparisonRow[] = [
  {
    capability: "License",
    memgentic: "Apache 2.0",
    singleTool: "Varies by project",
    verbatimLocal: "MIT / AGPL typical",
  },
  {
    capability: "AI tools captured",
    memgentic:
      "9 live (hooks, watchers, MCP, import) + one-shot JSON imports",
    singleTool: "One primary tool, optional secondaries",
    verbatimLocal: "One primary tool + any MCP-compatible client",
  },
  {
    capability: "Primary surfaces",
    memgentic: "CLI + MCP + REST + Next.js dashboard",
    singleTool: "CLI + MCP (+ optional local viewer)",
    verbatimLocal: "CLI + MCP",
  },
  {
    capability: "Skills distribution (Agent Skills standard)",
    memgentic: "Yes — daemon writes SKILL.md to 26+ tool paths",
    singleTool: "Varies",
    verbatimLocal: "Not a core feature",
  },
  {
    capability: "Knowledge graph",
    memgentic:
      "Co-occurrence graph + Chronograph (bitemporal triples, user-validated)",
    singleTool: "Usually none",
    verbatimLocal: "Temporal entity-relationship graph",
  },
  {
    capability: "Team / workspace support",
    memgentic: "Phase C on roadmap (auth + workspaces + RBAC)",
    singleTool: "Typically single-user",
    verbatimLocal: "Typically single-user",
  },
  {
    capability: "Native acceleration",
    memgentic: "Optional Rust / PyO3 (5–50× on hot paths)",
    singleTool: "Typically none",
    verbatimLocal: "Typically none",
  },
  {
    capability: "Published retrieval benchmarks",
    memgentic: "Benchmark harness in this repo (LongMemEval / LoCoMo / ConvoMem)",
    singleTool: "Varies",
    verbatimLocal: "Published LongMemEval numbers — mature",
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WelcomePage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <TopBar />
      <Hero />
      <DemoSlot />
      <RecallTiersSection />
      <WatchersSection />
      <ComparisonSection />
      <WhySection />
      <Footer />
    </main>
  );
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

function TopBar() {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4">
        <Link href="/welcome" className="flex items-center gap-2">
          <span className="inline-block size-6 rounded-md bg-primary" aria-hidden />
          <span className="font-heading text-lg font-semibold tracking-tight">
            Memgentic
          </span>
        </Link>
        <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <a href="#recall-tiers" className="hover:text-foreground">
            Recall Tiers
          </a>
          <a href="#watchers" className="hover:text-foreground">
            Watchers
          </a>
          <a href="#compare" className="hover:text-foreground">
            Compare
          </a>
          <a href="#why" className="hover:text-foreground">
            Why Memgentic
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <Link
            href="https://github.com/Chariton-kyp/memgentic"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            GitHub
          </Link>
          <Link
            href="/login"
            className="inline-flex h-7 items-center rounded-lg border border-border bg-background px-2.5 text-[0.8rem] font-medium transition-colors hover:bg-muted hover:text-foreground"
          >
            Open dashboard
          </Link>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b">
      <div className="mx-auto w-full max-w-6xl px-6 py-24 sm:py-32">
        <div className="max-w-3xl">
          <Badge variant="secondary" className="mb-6 rounded-full">
            Local-first · Apache 2.0
          </Badge>
          <h1 className="font-heading text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            Universal AI memory,
            <span className="block text-muted-foreground">
              across every tool you use.
            </span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground sm:text-xl">
            One memory layer across Claude Code, Cursor, Gemini CLI, Codex,
            ChatGPT, Aider, and more. Captured automatically. Searchable
            everywhere. Your data, your machine.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3 text-sm">
            <span className="rounded-md border bg-muted px-3 py-1.5 font-mono">
              pip install memgentic
            </span>
            <span className="rounded-md border bg-muted px-3 py-1.5 font-mono">
              memgentic init
            </span>
            <span className="rounded-md border bg-muted px-3 py-1.5 font-mono">
              memgentic daemon
            </span>
          </div>
          <div className="mt-10 grid gap-3 sm:grid-cols-3">
            <HeroStat value="9" label="AI tools captured" />
            <HeroStat value="5" label="recall tiers (T0–T4)" />
            <HeroStat value="26+" label="Agent Skills targets" />
          </div>
        </div>
      </div>
    </section>
  );
}

function HeroStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="font-heading text-3xl font-semibold">{value}</div>
      <div className="mt-1 text-sm text-muted-foreground">{label}</div>
    </div>
  );
}

function DemoSlot() {
  return (
    <section className="border-b bg-muted/20">
      <div className="mx-auto w-full max-w-6xl px-6 py-14">
        {/* TODO: 60s muted-autoplay demo video slot */}
        <div className="flex aspect-video w-full items-center justify-center rounded-2xl border border-dashed bg-card text-sm text-muted-foreground">
          Demo video — coming soon
        </div>
      </div>
    </section>
  );
}

function RecallTiersSection() {
  return (
    <section id="recall-tiers" className="border-b">
      <div className="mx-auto w-full max-w-6xl px-6 py-24">
        <div className="mb-12 max-w-3xl">
          <Badge variant="outline" className="mb-4 rounded-full">
            Recall Tiers
          </Badge>
          <h2 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">
            Five tiers of context,
            <span className="block text-muted-foreground">
              loaded only when they&apos;re needed.
            </span>
          </h2>
          <p className="mt-5 text-lg text-muted-foreground">
            Every agent session opens cold. Dumping everything wastes tokens;
            dumping nothing forces re-discovery. Recall Tiers give the agent a
            small, deterministic wake-up (T0 + T1 under ~900 tokens by default)
            and leave deeper recall one call away.
          </p>
        </div>

        <ol className="grid gap-4 md:grid-cols-5">
          {RECALL_TIERS.map((tier, idx) => (
            <li
              key={tier.id}
              className="group relative flex flex-col rounded-xl border bg-card p-5 transition-colors hover:border-foreground/20"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-muted-foreground">
                  {tier.id}
                </span>
                <span className="text-xs text-muted-foreground">
                  {tier.defaultLoad}
                </span>
              </div>
              <h3 className="mt-3 font-heading text-lg font-semibold">
                {tier.name}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {tier.tagline}
              </p>
              <div className="mt-4 space-y-2 text-xs">
                <div>
                  <span className="text-muted-foreground">Budget: </span>
                  <span className="font-mono">{tier.budget}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Source: </span>
                  <span>{tier.source}</span>
                </div>
              </div>
              {idx < RECALL_TIERS.length - 1 && (
                <div
                  aria-hidden
                  className="absolute right-[-14px] top-1/2 hidden h-px w-7 -translate-y-1/2 bg-border md:block"
                />
              )}
            </li>
          ))}
        </ol>

        <div className="mt-10 rounded-2xl border bg-muted/30 p-6 font-mono text-xs leading-relaxed sm:text-sm">
          <div className="mb-2 text-muted-foreground">
            {"// memgentic_briefing() — default T0 + T1"}
          </div>
          <pre className="whitespace-pre-wrap">{`## T0 — Persona
You are Atlas, personal AI assistant for Alice.
Tone: warm, direct, remembers everything.
Active projects: journaling-app (next.js + postgres).

## T1 — Horizon
[collection:journaling-app]
  - decided Clerk over Auth0 (pricing) — 2026-02-01, pinned
  - Kai fixed OAuth refresh flow in middleware.ts — 2026-02-08
  - migrated to PostgreSQL 18 for pgvector support — 2026-03-14, pinned
[skills:top]
  - debugging/pr-review (used 34x)
  - deploy-runbook (used 21x)`}</pre>
        </div>
      </div>
    </section>
  );
}

function WatchersSection() {
  return (
    <section id="watchers" className="border-b bg-muted/10">
      <div className="mx-auto w-full max-w-6xl px-6 py-24">
        <div className="mb-12 max-w-3xl">
          <Badge variant="outline" className="mb-4 rounded-full">
            Watchers
          </Badge>
          <h2 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">
            Every tool, captured the way it wants to be captured.
          </h2>
          <p className="mt-5 text-lg text-muted-foreground">
            Hooks where the tool has a hook API. File watchers where it writes
            to disk. MCP where the agent initiates. One-shot imports where
            there&apos;s no live access. All paths converge on the same daemon:
            dedup → capture-profile pipeline → store. Zero tokens in the chat
            window.
          </p>
        </div>

        <div className="overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-5 py-3 font-medium">Tool</th>
                <th className="px-5 py-3 font-medium">Capture mechanism</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {WATCHER_ROWS.map((row) => (
                <tr
                  key={row.tool}
                  className="border-t first:border-t-0 hover:bg-muted/20"
                >
                  <td className="px-5 py-4 font-medium">{row.tool}</td>
                  <td className="px-5 py-4 text-muted-foreground">
                    {row.mechanism}
                  </td>
                  <td className="px-5 py-4">
                    <Badge
                      variant={row.status === "Shipped" ? "default" : "secondary"}
                      className="rounded-full"
                    >
                      {row.status}
                    </Badge>
                  </td>
                  <td className="px-5 py-4 text-muted-foreground">
                    {row.notes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-6 text-sm text-muted-foreground">
          Manage them uniformly:{" "}
          <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
            memgentic watchers install --tool claude_code
          </code>
          ,{" "}
          <code className="rounded bg-muted px-2 py-1 font-mono text-xs">
            memgentic watchers status
          </code>
          .
        </p>
      </div>
    </section>
  );
}

function ComparisonSection() {
  return (
    <section id="compare" className="border-b">
      <div className="mx-auto w-full max-w-6xl px-6 py-24">
        <div className="mb-12 max-w-3xl">
          <Badge variant="outline" className="mb-4 rounded-full">
            How Memgentic compares
          </Badge>
          <h2 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">
            Different bets. Matter-of-fact comparison.
          </h2>
          <p className="mt-5 text-lg text-muted-foreground">
            The AI-memory space is young. Each project makes different
            architectural bets and is the right choice for a specific shape of
            user. This table shows ours next to the two common alternatives —
            generic labels where an upstream claim isn&apos;t verified.
          </p>
        </div>

        <div className="overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-5 py-3 font-medium">Capability</th>
                <th className="px-5 py-3 font-medium">Memgentic</th>
                <th className="px-5 py-3 font-medium">
                  Typical single-tool memory
                </th>
                <th className="px-5 py-3 font-medium">
                  Verbatim local-first memory
                </th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON_ROWS.map((row) => (
                <tr
                  key={row.capability}
                  className="border-t first:border-t-0 hover:bg-muted/20"
                >
                  <td className="px-5 py-4 font-medium">{row.capability}</td>
                  <td className="px-5 py-4 text-muted-foreground">
                    {row.memgentic}
                  </td>
                  <td className="px-5 py-4 text-muted-foreground">
                    {row.singleTool}
                  </td>
                  <td className="px-5 py-4 text-muted-foreground">
                    {row.verbatimLocal}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-6 text-xs text-muted-foreground">
          Detailed, named-project comparison (with upstream-verified rows for
          claude-mem and MemPalace) lives in the repo README.
        </p>
      </div>
    </section>
  );
}

function WhySection() {
  return (
    <section id="why" className="border-b bg-muted/10">
      <div className="mx-auto w-full max-w-6xl px-6 py-24">
        <div className="mb-12 max-w-3xl">
          <Badge variant="outline" className="mb-4 rounded-full">
            Why Memgentic
          </Badge>
          <h2 className="font-heading text-3xl font-semibold tracking-tight sm:text-4xl">
            Multi-tool. Team-ready. Dashboard-first.
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          <WhyCard
            title="Multi-tool by default"
            body={
              <>
                <p>
                  Nine AI tools captured automatically through the mechanism
                  each one prefers — hooks, file watchers, MCP, or one-shot
                  imports. Nothing for you to wire up by hand, and no tool is
                  asked to change how it works.
                </p>
                <p className="mt-3">
                  Your Claude Code session and your Cursor session share the
                  same memory. Your ChatGPT export joins the same graph.
                </p>
              </>
            }
          />
          <WhyCard
            title="Team-ready architecture"
            body={
              <>
                <p>
                  Persona already carries a{" "}
                  <code className="rounded bg-muted px-1 font-mono text-xs">
                    workspace_inherit
                  </code>{" "}
                  flag. Chronograph&apos;s entities and triples carry a{" "}
                  <code className="rounded bg-muted px-1 font-mono text-xs">
                    workspace_id
                  </code>{" "}
                  column today, ready for the Phase C auth + workspaces +
                  RBAC milestone.
                </p>
                <p className="mt-3">
                  The goal: a shared team brain where skills, personas, and
                  validated triples move with the team — not a per-seat silo.
                </p>
              </>
            }
          />
          <WhyCard
            title="A real dashboard"
            body={
              <>
                <p>
                  Next.js 16 + React 19 + shadcn/ui. Pinned row, memory grid,
                  collections sidebar, command palette, activity feed, skills
                  editor, watchers console, Chronograph graph viz and
                  validation queue.
                </p>
                <p className="mt-3">
                  You curate the memory the same way you curate the code —
                  with a UI, not a config file.
                </p>
              </>
            }
          />
        </div>
      </div>
    </section>
  );
}

function WhyCard({
  title,
  body,
}: {
  title: string;
  body: React.ReactNode;
}) {
  return (
    <article className="rounded-2xl border bg-card p-6">
      <h3 className="font-heading text-xl font-semibold">{title}</h3>
      <div className="mt-3 space-y-3 text-sm text-muted-foreground">{body}</div>
    </article>
  );
}

function Footer() {
  return (
    <footer className="bg-background">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-10 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div>
          Apache 2.0 · Local-first · Source on{" "}
          <Link
            href="https://github.com/Chariton-kyp/memgentic"
            className="underline hover:text-foreground"
          >
            GitHub
          </Link>
        </div>
        <div className="flex gap-4">
          <Link href="/login" className="hover:text-foreground">
            Open dashboard
          </Link>
          <Link
            href="https://github.com/Chariton-kyp/memgentic/blob/main/README.md"
            className="hover:text-foreground"
          >
            Documentation
          </Link>
        </div>
      </div>
    </footer>
  );
}
