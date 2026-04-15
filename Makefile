.PHONY: dev up up-gpu down build logs test lint fmt serve daemon import search sources pull-models api api-prod backup restore native

# --- Docker (primary deployment) ---

dev:  ## Start full stack (auto-detects NVIDIA GPU)
	@if command -v nvidia-smi > /dev/null 2>&1 && nvidia-smi > /dev/null 2>&1; then \
		echo "GPU detected — starting with NVIDIA acceleration"; \
		docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build; \
	else \
		echo "No GPU detected — starting in CPU mode"; \
		docker compose up -d --build; \
	fi
	@echo ""
	@echo "Memgentic stack starting..."
	@echo "  MCP Server:  http://localhost:8200"
	@echo "  REST API:    http://localhost:8100"
	@echo "  Qdrant:      http://localhost:6333/dashboard"
	@echo "  Ollama:      http://localhost:11434"
	@echo ""
	@echo "First run? Model will auto-pull (~2.5GB). Check: docker compose logs -f ollama-init"

up:  ## Start all containers (CPU mode)
	docker compose up -d --build

up-gpu:  ## Start all containers (GPU mode — requires NVIDIA)
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

down:  ## Stop all containers
	docker compose down

build:  ## Rebuild containers (no cache)
	docker compose build --no-cache

logs:  ## Tail all logs
	docker compose logs -f

logs-memgentic:  ## Tail Memgentic logs only
	docker compose logs -f memgentic memgentic-api

logs-ollama:  ## Tail Ollama logs (useful for model pull progress)
	docker compose logs -f ollama ollama-init

status:  ## Show container status
	docker compose ps

# --- Local development (without Docker) ---

serve:  ## Start MCP server locally (stdio)
	uv run memgentic serve

daemon:  ## Start file watcher daemon locally
	uv run memgentic daemon

import:  ## Import all existing conversations
	uv run memgentic import-existing

search:  ## Search memory: make search Q="your query"
	uv run memgentic search "$(Q)"

sources:  ## Show memory sources and counts
	uv run memgentic sources

# --- Testing & linting ---

test:  ## Run all tests
	uv run pytest memgentic/tests/ -v && uv run pytest memgentic-api/tests/ -v

lint:  ## Run linter
	uv run ruff check memgentic/ memgentic-api/

fmt:  ## Format code
	uv run ruff format memgentic/ memgentic-api/

# --- Setup ---

install:  ## Install all dependencies (Python + native Rust acceleration if available)
	uv sync --dev
	@$(MAKE) native || echo "Note: Rust native acceleration not built (Rust toolchain not found). Pure Python will be used — this is fine."

native:  ## Build and install Rust native acceleration module (optional, requires Rust)
	@command -v cargo > /dev/null 2>&1 || { echo "Rust not installed. Install from https://rustup.rs for native acceleration (optional)."; exit 1; }
	@command -v maturin > /dev/null 2>&1 || pip install maturin > /dev/null 2>&1
	cd memgentic-native && maturin build --release
	pip install memgentic-native/target/wheels/memgentic_native-*.whl --force-reinstall --quiet
	@echo "Native Rust acceleration installed successfully."

pull-models:  ## Pull embedding model (Docker)
	docker compose exec ollama ollama pull qwen3-embedding:4b

pull-models-local:  ## Pull embedding model (local Ollama)
	ollama pull qwen3-embedding:4b

# --- REST API (local) ---

api:  ## Start REST API locally (dev with reload)
	uv run uvicorn memgentic_api.main:app --reload --port 8100

api-prod:  ## Start REST API (production)
	uv run uvicorn memgentic_api.main:app --host 0.0.0.0 --port 8100

# --- Dashboard ---

dashboard:  ## Start dashboard (dev)
	cd dashboard && npm run dev

dashboard-build:  ## Build dashboard for production
	cd dashboard && npm run build

# --- Backup ---

backup:  ## Backup all Memgentic data
	uv run memgentic backup

restore:  ## Restore from backup: make restore FILE=backup.tar.gz
	uv run memgentic restore "$(FILE)"
