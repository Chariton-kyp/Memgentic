# Changelog

## [1.1.0](https://github.com/Chariton-kyp/Memgentic/compare/v1.0.0...v1.1.0) (2026-06-28)


### Features

* bge-m3 selectable + user-wide .env + re-embed rebuild + fix updated_at migration ([#162](https://github.com/Chariton-kyp/Memgentic/issues/162)) ([7dfde08](https://github.com/Chariton-kyp/Memgentic/commit/7dfde088c700732973fce6743edd3b49f17ed649))

## [1.0.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.11.0...v1.0.0) (2026-06-28)


### ⚠ BREAKING CHANGES

* the default embedding model (qwen3-embedding:4b), embedding dimensions (1024) and vector backend (qdrant) changed. Existing installs must run a Qdrant server, `ollama pull qwen3-embedding:4b`, and `memgentic re-embed` (which also restores any historically orphaned vectors). See docs/recommended-setup.md.

### Features

* memory-quality overhaul (recall, scope, self-cleaning, reranker, 4b@1024+Qdrant) ([#157](https://github.com/Chariton-kyp/Memgentic/issues/157)) ([ea23a0d](https://github.com/Chariton-kyp/Memgentic/commit/ea23a0db1ad8ef362d99ed707324542dcd25ef5f))

## [0.11.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.10.0...v0.11.0) (2026-06-12)


### Features

* **guard:** C# support (using + PackageReference), forbidden-path check, severity-aware exits ([#144](https://github.com/Chariton-kyp/Memgentic/issues/144)) ([8819226](https://github.com/Chariton-kyp/Memgentic/commit/881922652c327c0a6e4f9b5f4865c15d2bbf35e1))
* **guard:** C# support, forbidden-path check, severity-aware exits ([8819226](https://github.com/Chariton-kyp/Memgentic/commit/881922652c327c0a6e4f9b5f4865c15d2bbf35e1))
* **guard:** first-run UX — guard init, install-hook, Windows-safe output, docs ([#146](https://github.com/Chariton-kyp/Memgentic/issues/146)) ([710e936](https://github.com/Chariton-kyp/Memgentic/commit/710e93677820615efc2785405524920ab664d3a0))
* **guard:** LLM-assisted rule discovery — guard suggest ([intelligence], Ollama-ready) ([#145](https://github.com/Chariton-kyp/Memgentic/issues/145)) ([2b9e49f](https://github.com/Chariton-kyp/Memgentic/commit/2b9e49fb0d5dfbf957a43f5326d85de078e2e0ed))

## [0.10.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.9.0...v0.10.0) (2026-06-11)


### Features

* **guard:** daily-flow integration — decisions.yaml, pre-commit hook, MCP self-check ([#140](https://github.com/Chariton-kyp/Memgentic/issues/140)) ([e798c54](https://github.com/Chariton-kyp/Memgentic/commit/e798c5430a06654761b32fd08e83edf0d1f04639))
* **guard:** daily-flow integration — decisions.yaml, pre-commit hook, MCP self-check tool ([e798c54](https://github.com/Chariton-kyp/Memgentic/commit/e798c5430a06654761b32fd08e83edf0d1f04639))
* project-filter foundation + auto-dream pipeline (local baseline) ([#141](https://github.com/Chariton-kyp/Memgentic/issues/141)) ([592e484](https://github.com/Chariton-kyp/Memgentic/commit/592e484242163c37cf50b7c4ad2cbc7056826195))

## [0.9.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.8.0...v0.9.0) (2026-06-10)


### Features

* **adapters:** discover AI-tool sessions inside WSL distros from Windows ([#119](https://github.com/Chariton-kyp/Memgentic/issues/119)) ([ed52542](https://github.com/Chariton-kyp/Memgentic/commit/ed5254225730ca035afd8c376fe884b330e65312))
* **guard:** deterministic guard walking skeleton (CLI + 3 AST-scoped checks) ([#136](https://github.com/Chariton-kyp/Memgentic/issues/136)) ([71f6472](https://github.com/Chariton-kyp/Memgentic/commit/71f647215dc5d19e45b7798100ca06f63f3b2a06))
* **llm:** add OpenAI-compatible provider tier (LM Studio / vLLM / llama-server) ([#123](https://github.com/Chariton-kyp/Memgentic/issues/123)) ([ea8f014](https://github.com/Chariton-kyp/Memgentic/commit/ea8f01483bb8eac22ae3cc726f3262ec5db2c497))


### Bug Fixes

* **adapters:** codex_cli now reads ``~/.codex/sessions/.../rollout-*.jsonl`` ([98644ee](https://github.com/Chariton-kyp/Memgentic/commit/98644eee8f391f42833c976395c376bc170500ec))
* **adapters:** codex_cli now reads ~/.codex/sessions/.../rollout-*.jsonl ([#118](https://github.com/Chariton-kyp/Memgentic/issues/118)) ([98644ee](https://github.com/Chariton-kyp/Memgentic/commit/98644eee8f391f42833c976395c376bc170500ec))
* **adapters:** repair Gemini / Codex / Copilot / Antigravity capture for current on-disk formats ([#116](https://github.com/Chariton-kyp/Memgentic/issues/116)) ([029a899](https://github.com/Chariton-kyp/Memgentic/commit/029a899120f19fcbd4be75cd58f4ab4090ead594))
* **cli:** wire LLMClient + persisted capture profile into daemon/import/remember ([#121](https://github.com/Chariton-kyp/Memgentic/issues/121)) ([8252598](https://github.com/Chariton-kyp/Memgentic/commit/8252598530bd713267bf4718ed99c49795b235e2))
* **llm:** use Ollama json_schema + bound num_ctx/num_predict ([#122](https://github.com/Chariton-kyp/Memgentic/issues/122)) ([151c0db](https://github.com/Chariton-kyp/Memgentic/commit/151c0db7bbe92cfad1f87bd27af4956a03b628db))
* **llm:** use Ollama json_schema + bound num_ctx/num_predict (no more silent retry-loops) ([151c0db](https://github.com/Chariton-kyp/Memgentic/commit/151c0db7bbe92cfad1f87bd27af4956a03b628db))
* **quality:** filter Gemini tool-response dumps + cap chunk size at 50 KB ([#120](https://github.com/Chariton-kyp/Memgentic/issues/120)) ([dc14731](https://github.com/Chariton-kyp/Memgentic/commit/dc147314d773f93bff40bae6c83313956a5c43f2))

## [0.8.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.7.0...v0.8.0) (2026-05-03)


### Features

* retrieval wins (R@5 +6.7pp) + cross-tool continuation ([#110](https://github.com/Chariton-kyp/Memgentic/issues/110)) ([2fb1011](https://github.com/Chariton-kyp/Memgentic/commit/2fb1011afb0923a73b54d3f9ce3c1b661f24966a))

## [0.7.0](https://github.com/Chariton-kyp/Memgentic/compare/v0.6.0...v0.7.0) (2026-04-22)


### Features

* **briefing:** add Recall Tiers (T0–T4) progressive context loader ([#69](https://github.com/Chariton-kyp/Memgentic/issues/69)) ([08df67d](https://github.com/Chariton-kyp/Memgentic/commit/08df67dd903ed0b0f900ed450c6d72bbe71e471a))
* **daemon:** add Watchers umbrella for cross-tool automatic capture ([#70](https://github.com/Chariton-kyp/Memgentic/issues/70)) ([f56d68d](https://github.com/Chariton-kyp/Memgentic/commit/f56d68d89c2e184943cc242e9888970ea1efdab3))
* **graph:** add Chronograph (bitemporal entity-relationship graph) ([#67](https://github.com/Chariton-kyp/Memgentic/issues/67)) ([eba0fd3](https://github.com/Chariton-kyp/Memgentic/commit/eba0fd3290da159ec2b87121c15f15fa22c5bc74))
* **mcp:** expand tool surface to 27 (+dedupe/overview/refresh/watchers_status) ([#72](https://github.com/Chariton-kyp/Memgentic/issues/72)) ([d117f5e](https://github.com/Chariton-kyp/Memgentic/commit/d117f5eb30b2ac59766b1d7e26f653172921905c))
* **persona:** add structured persona with LLM bootstrap and dashboard editor ([#63](https://github.com/Chariton-kyp/Memgentic/issues/63)) ([207ce28](https://github.com/Chariton-kyp/Memgentic/commit/207ce28c6c1d025c35bb8f2da7a3bef5978e4ade))
* **pipeline:** add capture profiles (raw / enriched / dual) ([#65](https://github.com/Chariton-kyp/Memgentic/issues/65)) ([6668e7c](https://github.com/Chariton-kyp/Memgentic/commit/6668e7cf4856235bb9cc931d6eb5f11ad0f96b36))


### Bug Fixes

* **ci:** unblock Release Please, Scorecard, and Dependabot Rust updates ([#86](https://github.com/Chariton-kyp/Memgentic/issues/86)) ([e2aaed9](https://github.com/Chariton-kyp/Memgentic/commit/e2aaed9c0a38468f52eb9a5ff6f79a7b8c9fce3e))
