"""Bounded model-transport retry policy with cancellable backoff."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable


DEFAULT_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 5.0
MAX_PROVIDER_RETRIES = 1
_TRANSIENT_CODES = frozenset({"429", "500", "502", "503", "transport", "timeout"})


@dataclass(frozen=True)
class ProviderFailure(RuntimeError):
    code: str
    message: str
    retryable: bool = False
    retry_after_s: float | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class RetryDecision:
    action: str
    reason: str
    delay_s: float = 0.0


def _bounded_delay(value: object) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0):
        return DEFAULT_RETRY_DELAY_SECONDS
    return min(float(value), MAX_RETRY_DELAY_SECONDS)


def decide_provider_retry(error: BaseException, retries: int,
                          remaining_s: float) -> RetryDecision:
    """Retry one known transient pre-response failure within the run deadline."""
    if type(retries) is not int or retries < 0:
        raise ValueError("retries must be a non-negative integer")
    code = str(getattr(error, "code", "unknown"))
    retryable = getattr(error, "retryable", False) is True or code in _TRANSIENT_CODES
    if not retryable:
        return RetryDecision("fail", f"provider failure {code} is not retryable")
    if retries >= MAX_PROVIDER_RETRIES:
        return RetryDecision("exhaust", f"provider retry limit reached for {code}")
    delay = _bounded_delay(getattr(error, "retry_after_s", None))
    if remaining_s <= delay:
        return RetryDecision("timeout", "provider retry delay exceeds the run deadline")
    return RetryDecision("retry", f"transient provider failure {code}", delay)


def cancellable_backoff(delay_s: float, cancel_requested: Callable[[], bool],
                        wait: Callable[[float], None], quantum_s: float = 0.1) -> bool:
    """Wait a bounded duration; return False immediately when cancellation is requested."""
    if not isinstance(delay_s, (int, float)) or delay_s < 0:
        raise ValueError("delay_s must be non-negative")
    if not isinstance(quantum_s, (int, float)) or quantum_s <= 0:
        raise ValueError("quantum_s must be positive")
    elapsed = 0.0
    while elapsed < delay_s:
        if cancel_requested():
            return False
        interval = min(float(quantum_s), float(delay_s) - elapsed)
        wait(interval)
        elapsed += interval
    return not cancel_requested()
