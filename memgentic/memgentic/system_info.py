"""System resource detection -- GPU, RAM, and Ollama model management."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum

import httpx
import structlog

logger = structlog.get_logger()


class Tier(IntEnum):
    """Hardware-driven deployment tier.

    Drives the default (embedding, LLM, storage) pick shipped by `memgentic
    setup` and surfaced as advice in `memgentic doctor`. Values mirror the
    dogfooding benchmark table in `dogfooding/SESSION-2026-04-17.md`.
    """

    MINIMUM = 0  # 4 GB RAM, any 2-core CPU, no GPU — English-only models
    BALANCED = 1  # 8 GB RAM, 4-core CPU, no GPU — multilingual + 1B LLM
    QUALITY = 2  # 16 GB RAM, 6-core CPU, no GPU / iGPU — Qwen3-0.6B
    POWER = 3  # 32 GB RAM, 8-core CPU, >=8 GB VRAM GPU — Gemma e2b LLM
    WORKSTATION = 4  # 64 GB RAM, 12-core CPU, >=12 GB VRAM — Gemma e4b LLM


@dataclass
class TierRecommendation:
    """Model + dimension pick for a given hardware profile."""

    tier: Tier
    label: str
    reason: str
    embedding_model: str
    embedding_dimensions: int
    local_llm_model: str
    multilingual: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class GpuInfo:
    """GPU hardware information."""

    name: str
    vram_total_mb: int
    vram_used_mb: int
    vram_free_mb: int
    utilization_pct: int

    @property
    def vram_total_gb(self) -> float:
        return self.vram_total_mb / 1024

    @property
    def vram_free_gb(self) -> float:
        return self.vram_free_mb / 1024


@dataclass
class RamInfo:
    """System RAM information."""

    total_mb: int
    available_mb: int

    @property
    def total_gb(self) -> float:
        return self.total_mb / 1024

    @property
    def available_gb(self) -> float:
        return self.available_mb / 1024


@dataclass
class LoadedModel:
    """An Ollama model currently loaded in memory."""

    name: str
    size_bytes: int
    vram_bytes: int
    expires_at: str

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024**3)

    @property
    def vram_gb(self) -> float:
        return self.vram_bytes / (1024**3)

    @property
    def on_gpu(self) -> bool:
        return self.vram_bytes > 0


def detect_gpu() -> GpuInfo | None:
    """Detect NVIDIA GPU via nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split(",")
        if len(parts) < 5:
            return None
        return GpuInfo(
            name=parts[0].strip(),
            vram_total_mb=int(parts[1].strip()),
            vram_used_mb=int(parts[2].strip()),
            vram_free_mb=int(parts[3].strip()),
            utilization_pct=int(parts[4].strip()),
        )
    except Exception:
        return None


def detect_ram() -> RamInfo:
    """Detect system RAM (cross-platform)."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                [
                    "wmic",
                    "OS",
                    "get",
                    "TotalVisibleMemorySize,FreePhysicalMemory",
                    "/format:csv",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split(",")
                if len(parts) >= 3 and parts[1].strip().isdigit():
                    free_kb = int(parts[1].strip())
                    total_kb = int(parts[2].strip())
                    return RamInfo(
                        total_mb=total_kb // 1024,
                        available_mb=free_kb // 1024,
                    )
        else:
            # Linux/macOS — os.sysconf is POSIX-only, hence the ignore.
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")  # type: ignore[attr-defined]
            avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")  # type: ignore[attr-defined]
            return RamInfo(
                total_mb=total // (1024 * 1024),
                available_mb=avail // (1024 * 1024),
            )
    except Exception:
        pass
    return RamInfo(total_mb=0, available_mb=0)


def detect_cpu_cores() -> int:
    """Return the number of logical CPU cores (0 if unknown)."""
    return os.cpu_count() or 0


def recommend_tier(
    gpu: GpuInfo | None,
    ram: RamInfo,
    cpu_cores: int,
    *,
    multilingual: bool = True,
) -> TierRecommendation:
    """Pick a deployment tier from detected hardware.

    Logic — in order of preference:
    - >=12 GB VRAM + >=32 GB RAM => WORKSTATION (Qwen3-0.6B embed + Gemma e4b LLM)
    - >=8 GB VRAM  + >=16 GB RAM => POWER       (Qwen3-0.6B embed + Gemma e2b LLM)
    - no GPU required, >=16 GB RAM => QUALITY   (Qwen3-0.6B embed + Gemma 1B LLM)
    - no GPU required,  >=8 GB RAM => BALANCED  (embeddinggemma:300m + Gemma 1B LLM)
    - no GPU required,  >=4 GB RAM => MINIMUM   (granite-embed:30m  + Gemma 270m LLM)

    When `multilingual=True`, anything below BALANCED (i.e. MINIMUM with
    English-only embedders) is accepted but a note is attached explaining
    the quality trade-off. When `multilingual=False`, MINIMUM is recommended
    freely because granite/all-minilm work fine for English.
    """
    ram_gb = ram.total_gb
    vram_gb = gpu.vram_total_gb if gpu else 0.0
    notes: list[str] = []

    if ram_gb == 0:
        # Couldn't detect — assume 8 GB as a safe middle ground.
        notes.append("RAM auto-detect failed; assuming 8 GB (BALANCED tier).")
        ram_gb = 8.0

    # --- Tier 4: workstation ---
    # Thresholds are slightly below the nominal marketing GB so real devices
    # report them correctly (e.g. a "12 GB" RTX 4080 reports 11.99 GB; a
    # "64 GB" desktop reports 63.7 GB after kernel + ramdisk reservations).
    if vram_gb >= 11 and ram_gb >= 30 and cpu_cores >= 8:
        return TierRecommendation(
            tier=Tier.WORKSTATION,
            label="Tier 4 — Workstation",
            reason=f">={vram_gb:.0f} GB VRAM + {ram_gb:.0f} GB RAM + {cpu_cores} cores",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
            local_llm_model="gemma4:e4b",
            multilingual=True,
            notes=notes,
        )

    # --- Tier 3: power ---
    if vram_gb >= 7 and ram_gb >= 15:
        return TierRecommendation(
            tier=Tier.POWER,
            label="Tier 3 — Power user",
            reason=f"{vram_gb:.0f} GB VRAM + {ram_gb:.0f} GB RAM",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
            local_llm_model="gemma4:e2b",
            multilingual=True,
            notes=notes,
        )

    # --- Tier 2: quality (CPU-dominant) ---
    if ram_gb >= 15:
        return TierRecommendation(
            tier=Tier.QUALITY,
            label="Tier 2 — Quality (CPU-friendly, multilingual)",
            reason=f"{ram_gb:.0f} GB RAM"
            + (f", {vram_gb:.0f} GB VRAM (optional)" if gpu else ", no GPU"),
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
            local_llm_model="gemma3:1b",
            multilingual=True,
            notes=notes,
        )

    # --- Tier 1: balanced (CPU-only, multilingual) ---
    if ram_gb >= 7:
        return TierRecommendation(
            tier=Tier.BALANCED,
            label="Tier 1 — Balanced (CPU, multilingual)",
            reason=f"{ram_gb:.0f} GB RAM, no GPU",
            embedding_model="embeddinggemma:300m",
            embedding_dimensions=768,
            local_llm_model="gemma3:1b",
            multilingual=True,
            notes=notes,
        )

    # --- Tier 0: minimum (CPU, English only) ---
    if multilingual:
        notes.append(
            "Multilingual requested but RAM < 8 GB — falling back to the "
            "English-only MINIMUM tier. Search over Greek/other-language "
            "memories will still work but with reduced recall quality."
        )
    return TierRecommendation(
        tier=Tier.MINIMUM,
        label="Tier 0 — Minimum (English-only, small footprint)",
        reason=f"{ram_gb:.0f} GB RAM, no GPU",
        embedding_model="granite-embedding:30m",
        embedding_dimensions=384,
        local_llm_model="gemma3:270m",
        multilingual=False,
        notes=notes,
    )


async def get_loaded_models(ollama_url: str) -> list[LoadedModel]:
    """Get currently loaded Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{ollama_url}/api/ps")
            data = r.json()
            return [
                LoadedModel(
                    name=m.get("name", "unknown"),
                    size_bytes=m.get("size", 0),
                    vram_bytes=m.get("size_vram", 0),
                    expires_at=m.get("expires_at", ""),
                )
                for m in data.get("models", [])
            ]
    except Exception:
        return []


async def unload_model(ollama_url: str, model_name: str) -> bool:
    """Unload a model from Ollama memory."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{ollama_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
            )
            return r.status_code == 200
    except Exception:
        return False


async def load_model_with_options(
    ollama_url: str,
    model_name: str,
    num_gpu: int | None = None,
) -> bool:
    """Load a model into Ollama with specific GPU layer count.

    Args:
        ollama_url: Ollama server URL.
        model_name: Model to load.
        num_gpu: Number of GPU layers. 0=CPU only, None=auto, 999=all GPU.
    """
    try:
        body: dict = {"model": model_name, "keep_alive": "10m"}
        if num_gpu is not None:
            body["options"] = {"num_gpu": num_gpu}
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{ollama_url}/api/generate", json=body)
            return r.status_code == 200
    except Exception:
        return False


def recommend_model_placement(
    model_size_gb: float,
    gpu: GpuInfo | None,
    ram: RamInfo,
) -> str:
    """Recommend where to place a model based on available resources.

    Returns: 'gpu', 'ram', or 'too_large'
    """
    if gpu and gpu.vram_free_gb >= model_size_gb * 1.2:
        return "gpu"
    if ram.available_gb >= model_size_gb * 1.5:
        return "ram"
    return "too_large"
