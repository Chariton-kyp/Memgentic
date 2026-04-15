# === Stage 1: Builder — install dependencies ===
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install Rust toolchain + build tools for native acceleration module.
# build-essential brings libc6-dev (crt*.o, libdl, libc) which maturin/pyo3 need to link.
RUN apt-get update && apt-get install -y --no-install-recommends curl gcc build-essential && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.cargo/bin:${PATH}"
RUN pip install maturin

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock* ./
COPY memgentic/pyproject.toml memgentic/
COPY memgentic/memgentic/ memgentic/memgentic/
COPY memgentic-api/pyproject.toml memgentic-api/
COPY memgentic-api/memgentic_api/ memgentic-api/memgentic_api/

# Install Python dependencies (with intelligence extras for LangChain/LangGraph)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Build and install Rust native acceleration module
COPY memgentic-native/ memgentic-native/
RUN cd memgentic-native && maturin build --release && \
    pip install --target /opt/venv/lib/python3.12/site-packages target/wheels/memgentic_native-*.whl && \
    rm -rf target


# === Stage 2: Runtime — lean production image ===
FROM python:3.12-slim AS runtime

# Copy uv (needed for `uv run` in CMD/entrypoint)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy the virtual environment from builder (includes native module)
COPY --from=builder /opt/venv /opt/venv

# Copy source code
COPY pyproject.toml uv.lock* ./
COPY memgentic/ memgentic/
COPY memgentic-api/ memgentic-api/

# Non-root user for security
RUN addgroup --system --gid 1001 memgentic && \
    adduser --system --uid 1001 --ingroup memgentic memgentic && \
    chown -R memgentic:memgentic /app
USER memgentic

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/api/v1/health')" || exit 1

# Run MCP server by default (override in docker-compose per service)
CMD ["uv", "run", "memgentic", "serve"]
