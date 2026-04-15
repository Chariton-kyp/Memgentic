"""Memgentic processing layer — embeddings, summarization, and ingestion pipeline."""

from memgentic.processing.embedder import Embedder
from memgentic.processing.pipeline import IngestionPipeline

__all__ = ["Embedder", "IngestionPipeline"]
