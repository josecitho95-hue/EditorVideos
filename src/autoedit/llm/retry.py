"""LLM retry utilities — exponential backoff with jitter and circuit breaker."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from loguru import logger

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN (too many recent failures)."""


class LLMBadRequestError(Exception):
    """Raised for non-retriable 4xx errors (bad prompt, invalid model, quota exceeded permanently)."""


class CircuitBreaker:
    """Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.

    * CLOSED   — requests flow normally.
    * OPEN     — requests are rejected immediately for *recovery_sec* seconds.
    * HALF_OPEN — one probe request is allowed; success resets to CLOSED,
                  failure returns to OPEN.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_sec: float = 60.0,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery_sec = recovery_sec
        self._failures = 0
        self._state = self.CLOSED
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        """Current state (re-evaluates OPEN → HALF_OPEN after recovery window)."""
        if self._state == self.OPEN:
            elapsed = time.monotonic() - (self._opened_at or 0.0)
            if elapsed >= self._recovery_sec:
                self._state = self.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """Return True if a new request should be allowed through."""
        s = self.state
        return s in (self.CLOSED, self.HALF_OPEN)

    def record_success(self) -> None:
        """Reset failure count and move to CLOSED."""
        self._failures = 0
        self._state = self.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        """Increment failure count and open the circuit if threshold reached."""
        self._failures += 1
        if self._state == self.HALF_OPEN or self._failures >= self._threshold:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                f"[CircuitBreaker] OPEN after {self._failures} failures — "
                f"pausing for {self._recovery_sec:.0f}s."
            )


# Module-level default breaker (shared by the openrouter singleton)
_default_breaker = CircuitBreaker(failure_threshold=5, recovery_sec=60.0)


# HTTP status codes that are safe to retry (server-side / rate-limit errors)
_RETRIABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


async def retry_with_backoff(
    coro_fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 30.0,
    jitter: bool = True,
    circuit_breaker: CircuitBreaker | None = None,
) -> T:
    """Retry an async coroutine with exponential backoff and optional circuit breaker.

    Args:
        coro_fn: Zero-argument callable that returns an awaitable. Called fresh on
                 each attempt (lambdas work fine: ``lambda: client.chat(...)``).
        max_attempts: Total number of tries including the first.
        base_delay_sec: Delay before the *second* attempt, doubles each retry.
        max_delay_sec: Hard upper bound on inter-attempt delay.
        jitter: When True adds ±25 % random noise to avoid thundering-herd.
        circuit_breaker: Optional :class:`CircuitBreaker` instance. Defaults to
                         the module-level ``_default_breaker``.

    Returns:
        Return value of *coro_fn* on success.

    Raises:
        CircuitOpenError: Circuit is open — request rejected without attempting.
        LLMBadRequestError: Non-retriable 4xx error.
        Exception: Last exception after all attempts are exhausted.
    """
    cb = circuit_breaker if circuit_breaker is not None else _default_breaker

    if not cb.allow_request():
        raise CircuitOpenError(
            "LLM circuit breaker is OPEN — request rejected. "
            f"Retry after ~{cb._recovery_sec:.0f}s."
        )

    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = await coro_fn()
            cb.record_success()
            return result

        except LLMBadRequestError:
            cb.record_failure()
            raise  # never retry 4xx

        except Exception as exc:
            last_exc = exc

            # Classify by HTTP status code if available
            status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            if status is not None:
                try:
                    status_int = int(status)
                except (TypeError, ValueError):
                    status_int = 0

                if status_int and status_int not in _RETRIABLE_STATUS_CODES:
                    cb.record_failure()
                    raise LLMBadRequestError(
                        f"Non-retriable HTTP {status_int}: {exc}"
                    ) from exc

            if attempt == max_attempts:
                break  # exhaust → fall through to raise

            delay = min(base_delay_sec * (2 ** (attempt - 1)), max_delay_sec)
            if jitter:
                delay *= random.uniform(0.75, 1.25)

            logger.warning(
                f"[retry] Attempt {attempt}/{max_attempts} failed "
                f"({type(exc).__name__}: {exc}). Retrying in {delay:.1f}s…"
            )
            await asyncio.sleep(delay)

    cb.record_failure()
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_with_backoff: exhausted attempts with no exception captured")
