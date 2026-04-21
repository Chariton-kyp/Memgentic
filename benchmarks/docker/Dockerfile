# syntax=docker/dockerfile:1.7
#
# Reproducible environment for Memgentic benchmark runs.
#
# Phase 1 (this PR) bakes the harness layout + a pinned Memgentic source
# checkout + the embedding-model pull step. It does NOT download any
# dataset at build time — datasets are pulled by `benchmarks/datasets/
# download.sh` either inside the running container or on the host before
# `docker run`. See benchmarks/BENCHMARKS.md §Reproducibility for why.
#
# Build:
#     docker build -t memgentic-bench -f benchmarks/docker/Dockerfile .
#
# Run (Phase 2):
#     docker run --rm \
#         -v $(pwd)/benchmarks/datasets:/app/benchmarks/datasets \
#         -v $(pwd)/benchmarks/results:/app/benchmarks/results \
#         memgentic-bench longmemeval --profile raw

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy

# System deps: curl for download.sh, git for the Memgentic install,
# ca-certificates so HTTPS downloads work, and build-essential for any
# source-built wheels on arm64.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv is the Memgentic package manager and is reproducible across hosts.
RUN pip install --no-cache-dir "uv>=0.4"

WORKDIR /app

# --- Memgentic install -----------------------------------------------
# Install from the local source tree that is mounted in at build time
# (ships with this repo's PR). Pinning the commit is the caller's job:
# `docker build` sees whichever tree is present on disk, which keeps
# the reproducibility story honest when the image is rebuilt on a
# tagged commit.
COPY pyproject.toml uv.lock ./
COPY memgentic ./memgentic
COPY memgentic-api ./memgentic-api
RUN uv sync --no-dev --package memgentic

# --- Benchmark code ---------------------------------------------------
COPY benchmarks ./benchmarks

# Dataset volume mountpoints: kept empty in the image so licensing
# stays clean. Mount a host directory or run the download script
# manually inside the container.
VOLUME ["/app/benchmarks/datasets", "/app/benchmarks/results"]

# --- Ollama model placeholder ----------------------------------------
# The benchmark image talks to an Ollama sidecar at $OLLAMA_HOST. We
# don't bundle Ollama into the Python image so the container stays
# slim. In Phase 2 the docker-compose stack will wire an `ollama`
# service with the Qwen3-Embedding-0.6B model pre-pulled and set
# `OLLAMA_HOST=http://ollama:11434`.
ENV OLLAMA_HOST=http://host.docker.internal:11434 \
    MEMGENTIC_EMBEDDING_MODEL=qwen3-embedding:0.6b \
    MEMGENTIC_EMBEDDING_DIMENSIONS=768 \
    MEMGENTIC_STORAGE_BACKEND=sqlite_vec

ENTRYPOINT ["uv", "run", "python", "-m", "benchmarks.runners.longmemeval_bench"]
CMD ["--help"]
