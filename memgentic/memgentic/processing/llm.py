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
        # Identifies which provider produced ``self._model``. Used by
        # ``generate_structured`` to pick a compatible structured-output method
        # (function_calling for hosted OpenAI / Gemini, json_schema for local).
        self._provider_kind: str | None = None
        self._model = self._create_model()

    @property
    def available(self) -> bool:
        """Whether an LLM provider is configured and usable."""
        return self._model is not None

    def _create_model(self) -> BaseChatModel | None:
        """Create the best available LLM model.

        Priority order:
        1. Gemini Flash Lite via API (if GOOGLE_API_KEY set) — cheapest cloud
        2. OpenAI-compatible endpoint (LM Studio / vLLM / llama.cpp llama-server)
           — when ``openai_compat_base_url`` is set. Use this for model
           architectures Ollama doesn't support yet (e.g. Unsloth gemma4 GGUFs).
        3. Local Ollama (default fallback for laptop / single-node)
        4. None (falls back to heuristics)
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
                self._provider_kind = "google"
                return model
            except Exception as e:
                logger.warning("llm.google_init_failed", error=str(e))

        # Priority 2: OpenAI-compatible endpoint (opt-in via env)
        if self._settings.openai_compat_base_url:
            model = self._try_openai_compat_llm()
            if model:
                return model

        # Priority 3: Local LLM via Ollama (no API key needed)
        if self._settings.enable_local_llm:
            model = self._try_ollama_llm()
            if model:
                return model

        logger.info("llm.no_provider", msg="No LLM available -- using heuristics only")
        return None

    def _try_openai_compat_llm(self) -> BaseChatModel | None:
        """Try to connect to an OpenAI-compatible chat-completions endpoint.

        Covers LM Studio, vLLM, llama.cpp's ``llama-server``, OpenRouter, etc.
        The base_url should include the ``/v1`` suffix where the upstream
        expects it (most servers do).
        """
        try:
            from langchain_openai import ChatOpenAI

            kwargs: dict = {
                "model": self._settings.openai_compat_model,
                "base_url": self._settings.openai_compat_base_url,
                "api_key": self._settings.openai_compat_api_key,
                "temperature": 0,
                # ``max_tokens`` here is the OpenAI-style equivalent of
                # Ollama's ``num_predict``. Reuse the same budget — both are
                # caps on completion length.
                "max_tokens": self._settings.ollama_num_predict,
            }
            model = ChatOpenAI(**kwargs)
            logger.info(
                "llm.initialized",
                provider="openai_compat",
                base_url=self._settings.openai_compat_base_url,
                model=self._settings.openai_compat_model,
            )
            self._provider_kind = "openai_compat"
            return model
        except ImportError:
            logger.debug(
                "llm.openai_compat_not_installed",
                msg="langchain-openai not installed (pip install 'memgentic[intelligence]')",
            )
        except Exception as e:
            logger.warning("llm.openai_compat_init_failed", error=str(e))
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
            self._provider_kind = "ollama"
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

        Routing by ``_provider_kind``:
        - ``ollama`` and ``openai_compat``: use ``method="json_schema"``. Ollama
          maps it to ``options.format``; OpenAI-compatible servers (LM Studio,
          vLLM, llama.cpp llama-server) map it to ``response_format`` — both
          produce schema-validated JSON without requiring tool-calling. The
          langchain default (``function_calling``) assumes the model declares
          tool support; small open models (gemma3:1b, gemma4:e2b/e4b, qwen2.5
          < 7B) don't, and the langchain path falls into a 60-120 sec
          retry / shape-error loop that we observed on this machine.
        - ``google`` (Gemini): keep langchain default — Gemini exposes proper
          function calling and tool-call structured output is well-tested.

        Returns None if LLM unavailable or generation fails.
        """
        if not self._model:
            return None
        try:
            method_kwargs: dict = {}
            if self._provider_kind in ("ollama", "openai_compat"):
                method_kwargs["method"] = "json_schema"
            structured = self._model.with_structured_output(schema, **method_kwargs)
            result = await structured.ainvoke(prompt)
            if isinstance(result, BaseModel):
                return result
            return None
        except Exception as e:
            logger.warning("llm.structured_failed", error=str(e), schema=schema.__name__)
            return None

    async def generate_structured_with_usage(
        self, prompt: str, schema: type[BaseModel]
    ) -> tuple[BaseModel | None, dict[str, int]]:
        """Same as ``generate_structured`` but additionally returns token usage.

        Uses langchain's ``include_raw=True`` so we can read
        ``AIMessage.usage_metadata`` from the underlying provider response.
        Falls back to the standard structured call when the provider rejects
        ``include_raw`` — in that case usage is reported as zeros so the
        caller can still trust the parsed result.

        Returns ``(parsed, {"input_tokens": int, "output_tokens": int})``.
        Tokens are 0 when the provider doesn't expose ``usage_metadata`` (most
        Ollama / OpenAI-compat servers).
        """
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        if not self._model:
            return None, usage
        method_kwargs: dict = {}
        if self._provider_kind in ("ollama", "openai_compat"):
            method_kwargs["method"] = "json_schema"
        try:
            try:
                structured = self._model.with_structured_output(
                    schema, include_raw=True, **method_kwargs
                )
                result = await structured.ainvoke(prompt)
                if isinstance(result, dict):
                    parsed_obj = result.get("parsed")
                    parsed = parsed_obj if isinstance(parsed_obj, BaseModel) else None
                    raw = result.get("raw")
                    um = getattr(raw, "usage_metadata", None) if raw is not None else None
                    if um:
                        usage["input_tokens"] = int(um.get("input_tokens", 0) or 0)
                        usage["output_tokens"] = int(um.get("output_tokens", 0) or 0)
                    return parsed, usage
                if isinstance(result, BaseModel):
                    return result, usage
                return None, usage
            except TypeError:
                # Provider rejected ``include_raw=True`` — fall back to the
                # legacy path. We lose token counts but keep correctness.
                structured = self._model.with_structured_output(schema, **method_kwargs)
                result = await structured.ainvoke(prompt)
                parsed = result if isinstance(result, BaseModel) else None
                return parsed, usage
        except Exception as e:
            logger.warning(
                "llm.structured_with_usage_failed",
                error=str(e),
                schema=schema.__name__,
            )
            return None, usage
