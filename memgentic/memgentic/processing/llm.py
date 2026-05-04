"""LLM client — multi-provider via LangChain-core with graceful fallback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

from memgentic.config import MemgenticSettings

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = structlog.get_logger()


class LLMClient:
    """Provider-agnostic LLM client.

    Tries Gemini first (cheapest), then logs a warning if no provider is available.
    All methods gracefully return empty/None when no LLM is configured.
    """

    def __init__(self, settings: MemgenticSettings) -> None:
        self._settings = settings
        self._model = self._create_model()

    @property
    def available(self) -> bool:
        """Whether an LLM provider is configured and usable."""
        return self._model is not None

    def _create_model(self) -> BaseChatModel | None:
        """Create the best available LLM model.

        Priority order:
        1. Gemini Flash Lite via API (if GOOGLE_API_KEY set)
        2. Gemma 4 via local Ollama (if available, no API key needed)
        3. None (falls back to heuristics)
        """
        if not self._settings.enable_llm_processing:
            logger.info("llm.disabled", msg="LLM processing disabled in config")
            return None

        # Priority 1: Gemini API (cheapest cloud option: $0.075/1M tokens)
        if self._settings.google_api_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI

                model = ChatGoogleGenerativeAI(
                    model=self._settings.summarization_model,
                    google_api_key=self._settings.google_api_key,
                )
                logger.info(
                    "llm.initialized",
                    provider="google",
                    model=self._settings.summarization_model,
                )
                return model
            except Exception as e:
                logger.warning("llm.google_init_failed", error=str(e))

        # Priority 2: Local LLM via Ollama (Gemma 4, no API key needed)
        if self._settings.enable_local_llm:
            model = self._try_ollama_llm()
            if model:
                return model

        logger.info("llm.no_provider", msg="No LLM available -- using heuristics only")
        return None

    def _try_ollama_llm(self) -> BaseChatModel | None:
        """Try to connect to a local LLM via Ollama."""
        try:
            from langchain_ollama import ChatOllama

            kwargs: dict = {
                "model": self._settings.local_llm_model,
                "base_url": self._settings.ollama_url,
                "temperature": 0,
                # KV cache size — keep VRAM bounded. The default 4096 from Ollama
                # blows past 6 GiB of VRAM for a 5-8B Q8 model + activations and
                # triggers cudaMalloc OOM on consumer GPUs. Memgentic prompts
                # cap at ~1500 tokens so 2048 is plenty.
                "num_ctx": self._settings.ollama_num_ctx,
                # Max tokens to generate — structured outputs need ≤ 200; the old
                # 2048 default kept the runner alive for the entire pad even when
                # the JSON closed in 50 tokens.
                "num_predict": self._settings.ollama_num_predict,
            }
            if self._settings.ollama_num_threads > 0:
                kwargs["num_thread"] = self._settings.ollama_num_threads

            model = ChatOllama(**kwargs)
            logger.info(
                "llm.initialized",
                provider="ollama",
                model=self._settings.local_llm_model,
            )
            return model
        except ImportError:
            logger.debug("llm.ollama_not_installed", msg="langchain-ollama not installed")
        except Exception as e:
            logger.debug("llm.ollama_failed", error=str(e))
        return None

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Strip <think>...</think> tags from reasoning model output."""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    async def generate(self, prompt: str) -> str:
        """Generate text from prompt. Returns empty string if unavailable."""
        if not self._model:
            return ""
        try:
            response = await self._model.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return self._strip_thinking(str(content))
        except Exception as e:
            logger.warning("llm.generate_failed", error=str(e))
            return ""

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel | None:
        """Generate structured output matching the Pydantic schema.

        Routing:
        - Ollama models: use ``method="json_schema"`` so the request goes through
          Ollama's native JSON-schema format. The default (``"function_calling"``)
          assumes the model declares tool-calling support; small open models
          (gemma3:1b, gemma4:e2b/e4b, qwen2.5 < 7B) don't, and the langchain
          path falls into a 60-120 sec retry / shape-error loop that we observed
          on this machine. ``json_schema`` maps directly to Ollama's
          ``options.format`` JSON-schema and produces valid output in ~1 sec.
        - Cloud models (Gemini, Anthropic, etc.): keep the langchain default
          since their providers expose proper tool-calling.

        Returns None if LLM unavailable or generation fails.
        """
        if not self._model:
            return None
        try:
            method_kwargs: dict = {}
            # ChatOllama lives under langchain_ollama; detect by class module.
            if type(self._model).__module__.startswith("langchain_ollama"):
                method_kwargs["method"] = "json_schema"
            structured = self._model.with_structured_output(schema, **method_kwargs)
            result = await structured.ainvoke(prompt)
            if isinstance(result, BaseModel):
                return result
            return None
        except Exception as e:
            logger.warning("llm.structured_failed", error=str(e), schema=schema.__name__)
            return None
