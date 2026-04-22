# Benchmark datasets

Memgentic's benchmarks rely on third-party datasets that we do **not**
redistribute from this repository — they are large and their licences
generally require downloading directly from upstream. Use
[`download.sh`](download.sh) to fetch each dataset into this directory;
the script is never invoked automatically by CI.

The table below points at the upstream source and the commit / revision
we test against. Checksums are `TBD` until the Phase 2 benchmark runs
complete; once a run is published, the pinned upstream revision and
file SHA-256 will be written back here so future runs can detect drift.

| Dataset | Upstream | Local path | Pinned rev | SHA-256 |
|---|---|---|---|---|
| LongMemEval | `UCB-LongMemEval` (GitHub) | `longmemeval_s.json`, `longmemeval_m.json`, `longmemeval_oracle.json` | TBD | TBD |
| LoCoMo | `salesforce/locomo` (GitHub) | `locomo10.json` | TBD | TBD |
| ConvoMem | `salesforce/convomem` (GitHub) | `convomem.json` | TBD | TBD |
| MemBench | `yikun-li/MemBench` (GitHub) | `membench.jsonl` | TBD | TBD |

### Cross-Tool Transfer (Memgentic-original)

This benchmark is built by the Memgentic team rather than pulled from
upstream. A 5-row fixture lives at
[`cross_tool_transfer/example.jsonl`](cross_tool_transfer/example.jsonl)
for smoke tests; see
[`cross_tool_transfer/README.md`](cross_tool_transfer/README.md) for
the JSONL schema. The 100-conversation full dataset lands in a
follow-up PR once curation is complete.

### Licensing

Each dataset has its own licence. `download.sh` links to each upstream
repo; check the licence before redistribution. We intentionally do not
copy dataset files into this repo to avoid licence ambiguity.

### Verifying a download

After Phase 2 lands, every dataset file ships with a pinned SHA-256 in
the table above. Recompute with `sha256sum <file>` (Linux / macOS) or
`Get-FileHash <file>` (PowerShell) and compare. If the hashes differ,
report it in the benchmark results — upstream occasionally re-cuts
releases without bumping version numbers.
