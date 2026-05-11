"""TC-LLM-003, TC-LLM-004, TC-LLM-005 — retry_with_backoff + CircuitBreaker tests."""

from __future__ import annotations

import pytest

from autoedit.llm.retry import (
    CircuitBreaker,
    CircuitOpenError,
    LLMBadRequestError,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# TC-LLM-003 — retry on transient failures
# ---------------------------------------------------------------------------


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_after_two_failures(self) -> None:
        """Two transient failures followed by success → returns result, 3 total calls."""
        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                exc = Exception("transient error")
                exc.status_code = 503  # type: ignore[attr-defined]
                raise exc
            return "ok"

        cb = CircuitBreaker(failure_threshold=10, recovery_sec=0.0)
        result = await retry_with_backoff(
            flaky,
            max_attempts=3,
            base_delay_sec=0.0,  # no actual sleeping in tests
            circuit_breaker=cb,
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_exhausting_attempts(self) -> None:
        """All attempts fail → original exception is re-raised."""
        async def always_fail() -> None:
            exc = Exception("persistent error")
            exc.status_code = 503  # type: ignore[attr-defined]
            raise exc

        cb = CircuitBreaker(failure_threshold=10, recovery_sec=0.0)
        with pytest.raises(Exception, match="persistent error"):
            await retry_with_backoff(
                always_fail,
                max_attempts=3,
                base_delay_sec=0.0,
                circuit_breaker=cb,
            )

    @pytest.mark.asyncio
    async def test_no_retry_on_bad_request(self) -> None:
        """TC-LLM-004: LLMBadRequestError must not be retried (raised on first attempt)."""
        call_count = 0

        async def bad_request() -> None:
            nonlocal call_count
            call_count += 1
            raise LLMBadRequestError("invalid model")

        cb = CircuitBreaker(failure_threshold=10, recovery_sec=0.0)
        with pytest.raises(LLMBadRequestError):
            await retry_with_backoff(
                bad_request,
                max_attempts=3,
                base_delay_sec=0.0,
                circuit_breaker=cb,
            )
        assert call_count == 1, f"Expected 1 attempt for LLMBadRequestError, got {call_count}"


# ---------------------------------------------------------------------------
# TC-LLM-005 — circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_circuit_starts_closed(self) -> None:
        """A new CircuitBreaker must be in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=3, recovery_sec=60.0)
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.allow_request() is True

    def test_circuit_opens_after_threshold(self) -> None:
        """After `failure_threshold` failures the circuit must be OPEN."""
        cb = CircuitBreaker(failure_threshold=3, recovery_sec=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

    def test_circuit_resets_on_success(self) -> None:
        """Recording a success after failures resets to CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_sec=60.0)
        for _ in range(2):
            cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    @pytest.mark.asyncio
    async def test_circuit_open_raises_without_network_call(self) -> None:
        """TC-LLM-005: open circuit rejects call before any awaitable is created."""
        cb = CircuitBreaker(failure_threshold=1, recovery_sec=9999.0)
        cb.record_failure()  # open it immediately

        calls = 0

        async def should_not_be_called() -> str:
            nonlocal calls
            calls += 1
            return "never"

        with pytest.raises(CircuitOpenError):
            await retry_with_backoff(should_not_be_called, circuit_breaker=cb)

        assert calls == 0, "Circuit should block before calling the coroutine"
