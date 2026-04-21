#!/usr/bin/env bash
# Download benchmark datasets into ./benchmarks/datasets/.
#
# This script is NEVER invoked by CI — a full benchmark run would
# exceed PR feedback latency and some of the datasets are large.
# Maintainers run it manually (or inside the Docker image) before a
# Phase 2 benchmark session.
#
# Re-runs are idempotent: files that already exist on disk are left
# alone. To force a re-download, remove the file first.
#
# Upstream URLs below point at each project's public repository.
# Check each project's licence before redistribution — we deliberately
# do NOT commit the downloaded data back into the Memgentic repo.

set -euo pipefail

# Absolute path to this script's directory so the script works from any CWD.
DATASETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

download() {
    local url="$1"
    local dest="$2"

    if [ -f "$dest" ]; then
        echo "[skip]     $dest (already present)"
        return 0
    fi

    echo "[download] $url"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 "$url" -o "$dest"
    elif command -v wget >/dev/null 2>&1; then
        wget --tries=3 "$url" -O "$dest"
    else
        echo "error: neither curl nor wget is installed" >&2
        return 1
    fi
}

# --- LongMemEval -----------------------------------------------------
# Upstream: https://github.com/xiaowu0162/LongMemEval
# Releases carry the actual JSON files. Pin a specific release tag in
# the URL below once Phase 2 picks one — keep the placeholder until then.
LONGMEMEVAL_BASE="https://github.com/xiaowu0162/LongMemEval/releases/latest/download"
download "${LONGMEMEVAL_BASE}/longmemeval_s.json"      "${DATASETS_DIR}/longmemeval_s.json"      || true
download "${LONGMEMEVAL_BASE}/longmemeval_m.json"      "${DATASETS_DIR}/longmemeval_m.json"      || true
download "${LONGMEMEVAL_BASE}/longmemeval_oracle.json" "${DATASETS_DIR}/longmemeval_oracle.json" || true

# --- LoCoMo ----------------------------------------------------------
# Upstream: https://github.com/snap-research/locomo
# (Published under Salesforce AI Research; URL may move after Phase 2
# picks a pinned release tag.)
download \
    "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json" \
    "${DATASETS_DIR}/locomo10.json" || true

# --- ConvoMem --------------------------------------------------------
# Upstream: https://github.com/salesforce/convomem (pending)
download \
    "https://raw.githubusercontent.com/salesforce/convomem/main/convomem.json" \
    "${DATASETS_DIR}/convomem.json" || true

# --- MemBench --------------------------------------------------------
# Upstream: https://github.com/yikun-li/MemBench
download \
    "https://raw.githubusercontent.com/yikun-li/MemBench/main/data/membench.jsonl" \
    "${DATASETS_DIR}/membench.jsonl" || true

echo "done. Inspect $DATASETS_DIR and verify checksums listed in README.md."
