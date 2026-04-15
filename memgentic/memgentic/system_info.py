"""System resource detection -- GPU, RAM, and Ollama model management."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()


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
            # Linux/macOS
            import os

            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
            return RamInfo(
                total_mb=total // (1024 * 1024),
                available_mb=avail // (1024 * 1024),
            )
    except Exception:
        pass
    return RamInfo(total_mb=0, available_mb=0)


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
