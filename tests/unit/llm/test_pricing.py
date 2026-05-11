from __future__ import annotations

"""
TC-LLM-001, TC-LLM-002
Tests for LLM token cost estimation.
"""

import pytest

pytestmark: list = []  # skip removed — pricing is now implemented

from autoedit.llm.pricing import PRICE_TABLE, UnknownModelError, estimate


class TestEstimate:
    """TC-LLM-001 — estimate() returns correct cost values."""

    def test_deepseek_v3_estimate_positive(self) -> None:
        result = estimate("deepseek/deepseek-chat-v3", in_tokens=1000, out_tokens=500)
        assert result > 0.0, (
            f"Expected positive cost for deepseek-chat-v3, got {result}"
        )

    def test_deepseek_v3_estimate_reasonable(self) -> None:
        result = estimate("deepseek/deepseek-chat-v3", in_tokens=1000, out_tokens=500)
        assert result < 0.01, (
            f"Cost for 1000 in / 500 out tokens should be < $0.01, got {result:.6f}"
        )

    def test_gemini_flash_estimate(self) -> None:
        result = estimate("google/gemini-2.5-flash", in_tokens=1000, out_tokens=100)
        assert result > 0.0, (
            f"Expected positive cost for gemini-2.5-flash, got {result}"
        )

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(UnknownModelError):
            estimate("modelo/no-existe", in_tokens=100, out_tokens=50)

    def test_zero_tokens_returns_zero(self) -> None:
        result = estimate("deepseek/deepseek-chat-v3", in_tokens=0, out_tokens=0)
        assert result == 0.0, f"Expected 0.0 for zero tokens, got {result}"


class TestPriceTable:
    """TC-LLM-002 — PRICE_TABLE contains all required models."""

    REQUIRED_MODELS = [
        "deepseek/deepseek-chat-v3",
        "google/gemini-2.5-flash",
        "anthropic/claude-sonnet-4-6",
    ]

    def test_price_table_has_required_models(self) -> None:
        for model in self.REQUIRED_MODELS:
            assert model in PRICE_TABLE, (
                f"Model {model!r} missing from PRICE_TABLE"
            )

    @pytest.mark.parametrize(
        "model",
        [
            "deepseek/deepseek-chat-v3",
            "google/gemini-2.5-flash",
            "anthropic/claude-sonnet-4-6",
        ],
    )
    def test_each_required_model_has_in_and_out_price(self, model: str) -> None:
        entry = PRICE_TABLE[model]
        assert "in" in entry or "input" in entry, (
            f"Model {model!r} entry missing input price key"
        )
        assert "out" in entry or "output" in entry, (
            f"Model {model!r} entry missing output price key"
        )
