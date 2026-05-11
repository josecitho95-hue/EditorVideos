"""LLM pricing — OpenRouter model costs (USD per 1M tokens).

Prices sourced from https://openrouter.ai/models (2025-05).
Update periodically as prices change.
"""

from __future__ import annotations


class UnknownModelError(Exception):
    """Raised when a model ID has no entry in the price table."""


# Format: {model_id: {"in": $/1M input tokens, "out": $/1M output tokens}}
PRICE_TABLE: dict[str, dict[str, float]] = {
    # --- DeepSeek ---
    "deepseek/deepseek-chat-v3": {"in": 0.27, "out": 1.10},
    "deepseek/deepseek-chat": {"in": 0.27, "out": 1.10},
    "deepseek/deepseek-r1": {"in": 0.55, "out": 2.19},
    "deepseek/deepseek-r1-distill-qwen-32b": {"in": 0.14, "out": 0.55},
    # --- Google Gemini ---
    "google/gemini-2.5-flash": {"in": 0.15, "out": 0.60},
    "google/gemini-2.5-flash-preview": {"in": 0.15, "out": 0.60},
    "google/gemini-2.0-flash-001": {"in": 0.10, "out": 0.40},
    "google/gemini-flash-1.5": {"in": 0.075, "out": 0.30},
    "google/gemini-pro-1.5": {"in": 1.25, "out": 5.00},
    # --- Anthropic Claude ---
    "anthropic/claude-haiku-3-5": {"in": 0.80, "out": 4.00},
    "anthropic/claude-sonnet-4-5": {"in": 3.00, "out": 15.00},
    "anthropic/claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "anthropic/claude-opus-4": {"in": 15.00, "out": 75.00},
    "anthropic/claude-opus-4-5": {"in": 15.00, "out": 75.00},
    # --- OpenAI ---
    "openai/gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "openai/gpt-4o": {"in": 5.00, "out": 15.00},
    "openai/o1-mini": {"in": 3.00, "out": 12.00},
    # --- Mistral ---
    "mistralai/mistral-7b-instruct": {"in": 0.07, "out": 0.07},
    "mistralai/mixtral-8x7b-instruct": {"in": 0.27, "out": 0.27},
    "mistralai/mistral-large": {"in": 3.00, "out": 9.00},
    # --- Meta ---
    "meta-llama/llama-3.3-70b-instruct": {"in": 0.12, "out": 0.30},
    "meta-llama/llama-3.1-8b-instruct": {"in": 0.05, "out": 0.08},
}


def estimate(model: str, in_tokens: int, out_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts.

    Args:
        model: OpenRouter model identifier (e.g. "deepseek/deepseek-chat-v3").
        in_tokens: Number of input (prompt) tokens.
        out_tokens: Number of output (completion) tokens.

    Returns:
        Estimated cost in USD (float).

    Raises:
        UnknownModelError: If *model* has no entry in PRICE_TABLE.
    """
    if model not in PRICE_TABLE:
        raise UnknownModelError(
            f"No pricing data for model '{model}'. "
            f"Add it to PRICE_TABLE in autoedit/llm/pricing.py. "
            f"Known models: {sorted(PRICE_TABLE)}"
        )
    prices = PRICE_TABLE[model]
    return (in_tokens * prices["in"] + out_tokens * prices["out"]) / 1_000_000


def estimate_safe(
    model: str,
    in_tokens: int,
    out_tokens: int,
    fallback: float = 0.0,
) -> float:
    """Like :func:`estimate` but returns *fallback* for unknown models instead of raising."""
    try:
        return estimate(model, in_tokens, out_tokens)
    except UnknownModelError:
        return fallback
