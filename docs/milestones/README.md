# Milestone Plans

Detailed implementation plans for each milestone. See `docs/ROADMAP.md` for the overview.

## Milestones

| Doc | Milestone | Status |
|-----|-----------|--------|
| [M01-bootstrap.md](M01-bootstrap.md) | Bootstrap & Verify | Next up |
| [M02-production-core.md](M02-production-core.md) | Production Core | Planned |
| [M03-rest-api.md](M03-rest-api.md) | REST API | Planned |
| [M04-multi-source.md](M04-multi-source.md) | Multi-Source Adapters | Planned |
| [M05-intelligence.md](M05-intelligence.md) | Intelligence Layer | Planned |
| [M06-dashboard.md](M06-dashboard.md) | Web Dashboard | Planned |
| [M07-browser-extension.md](M07-browser-extension.md) | Browser Extension | Planned |
| [M08-cloud.md](M08-cloud.md) | Cloud Infrastructure | Planned |
| [M09-billing-launch.md](M09-billing-launch.md) | Billing & Launch | Planned |
| [M10-team-enterprise.md](M10-team-enterprise.md) | Team & Enterprise | Planned |
| [M11-ecosystem.md](M11-ecosystem.md) | Ecosystem & Growth | Planned |

## How to Use These Plans

Each milestone doc is structured for agent execution:

1. **Read the milestone doc** — understand the goal and exit criteria
2. **Implement each phase** — follow tasks, create/modify listed files
3. **Check acceptance criteria** — every phase has checkboxes
4. **Run tests + lint** — verify nothing is broken
5. **Commit** — atomic commit per phase

## Execution Order

```
M1 → M2 → M3 → M4 (parallel) → M5 (parallel) → M6 → M7 → M8 → M9 → M10 → M11
```

After M2, tracks M3/M4/M5 can run in parallel.
After M3, tracks M6/M7/M8 can run in parallel.
