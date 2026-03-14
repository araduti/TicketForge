"""
TicketForge — Pluggable LLM provider interface

Supports multiple LLM backends:
  - Ollama (local, self-hosted — default)
  - OpenAI-compatible APIs (OpenAI, Azure OpenAI, Anthropic via proxy, vLLM, LiteLLM, etc.)
"""
from __future__ import annotations

import abc
from typing import Any

import httpx
import structlog

from config import Settings

log = structlog.get_logger(__name__)


class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers."""

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request and return the assistant's content string."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close underlying HTTP connections."""

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Model identifier being used."""


class OllamaProvider(LLMProvider):
    """LLM provider using a local Ollama instance."""

    def __init__(self, settings: Settings) -> None:
        self._model = settings.ollama_model
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_timeout),
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model


class OpenAIProvider(LLMProvider):
    """
    LLM provider using the OpenAI-compatible chat completions API.

    Works with:
      - OpenAI (api.openai.com)
      - Azure OpenAI (via deployment endpoint)
      - vLLM / LiteLLM / LocalAI / any OpenAI-compatible server
    """

    def __init__(self, settings: Settings) -> None:
        self._model = settings.openai_model
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.openai_api_key:
            headers["Authorization"] = f"Bearer {settings.openai_api_key}"
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(settings.ollama_timeout),
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Factory: create the appropriate LLM provider based on configuration."""
    provider = settings.llm_provider.lower()
    if provider == "openai":
        log.info(
            "llm_provider.init",
            provider="openai",
            model=settings.openai_model,
            base_url=settings.openai_base_url,
        )
        return OpenAIProvider(settings)

    # Default: Ollama
    log.info(
        "llm_provider.init",
        provider="ollama",
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
    )
    return OllamaProvider(settings)
