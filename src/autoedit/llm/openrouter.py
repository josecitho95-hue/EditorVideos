"""OpenRouter client — async, with retry, circuit breaker, and cost tracking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from loguru import logger

from autoedit.llm.pricing import estimate_safe
from autoedit.llm.retry import CircuitBreaker, retry_with_backoff
from autoedit.settings import settings


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float = 0.0


class OpenRouterClient:
    """Async OpenAI-compatible client pointing to OpenRouter.

    Features:
    * Lazy ``AsyncOpenAI`` initialisation — safe to import at module level.
    * Per-instance circuit breaker (5 failures → 60 s recovery).
    * Exponential back-off with jitter on 429/5xx errors.
    * Automatic cost estimation via :mod:`autoedit.llm.pricing`.
    """

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_sec=60.0)

    def _ensure_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.OPENROUTER_API_KEY:
                raise RuntimeError(
                    "OPENROUTER_API_KEY is not set. "
                    "Add it to your .env file or environment."
                )
            self._client = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://github.com/josemiguel/autoedit-ai",
                    "X-Title": "AutoEdit AI",
                },
                timeout=120.0,
            )
        return self._client

    async def _do_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
        response_format: dict[str, object] | None,
    ) -> LLMResponse:
        """Single (non-retried) chat completion call — called by :meth:`chat`."""
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage

        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0
        cost_usd = estimate_safe(model, prompt_tokens, completion_tokens)

        if cost_usd:
            logger.debug(
                f"[OpenRouter] {model} — {prompt_tokens}in/{completion_tokens}out tokens "
                f"≈ ${cost_usd:.5f}"
            )

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model or model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
        max_attempts: int = 3,
    ) -> LLMResponse:
        """Send a chat completion with automatic retry and circuit breaker.

        Args:
            model: OpenRouter model identifier.
            messages: Chat messages in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Optional output token cap.
            response_format: Optional ``{"type": "json_object"}`` etc.
            max_attempts: Total attempts before giving up (default 3).

        Returns:
            :class:`LLMResponse` with content, token counts, and estimated cost.
        """
        return await retry_with_backoff(
            lambda: self._do_chat(
                model, messages, temperature, max_tokens, response_format
            ),
            max_attempts=max_attempts,
            base_delay_sec=1.0,
            max_delay_sec=30.0,
            circuit_breaker=self._circuit_breaker,
        )

    async def ping(self, model: str = "deepseek/deepseek-chat-v3") -> LLMResponse:
        """Minimal connectivity check — sends a 'say pong' request."""
        return await self.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'pong' and nothing else."},
            ],
            temperature=0.0,
            max_tokens=10,
        )


# Module-level singleton — import and call directly
openrouter = OpenRouterClient()
