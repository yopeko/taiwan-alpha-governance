"""Single retry policy shared by every capture script.

Retry logic was previously written inline in each capture script, which is how
the TPEx action capture ended up retrying its listing request but not its
per-announcement detail requests: seven MOPS 502s were left as silent gaps,
and because resume was keyed on the listing, a re-run would have skipped them.

Centralising the decision means a capture cannot accidentally omit it for one
of its request kinds.

Deliberately narrow: this decides *whether and how long to wait*, nothing
else. It never swallows an exception and never decides that a failure is
acceptable — that judgement belongs to the caller, which has to record the
outcome as evidence either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Transient at the transport or server layer. A 4xx other than 429 means the
# request itself is wrong, so repeating it unchanged is pointless.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


class RetryPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    """How many attempts a request kind gets, and how long to back off."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_seconds: float = DEFAULT_BASE_DELAY
    max_delay_seconds: float = DEFAULT_MAX_DELAY
    respect_retry_after: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise RetryPolicyError("max_attempts must be from 1 through 10")
        if self.base_delay_seconds < 0:
            raise RetryPolicyError("base_delay_seconds must not be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise RetryPolicyError("max_delay_seconds must not be below base")

    def is_retryable(self, status: int | None) -> bool:
        """A transport failure with no response (status None) is retryable."""

        if status is None:
            return True
        return status in RETRYABLE_STATUS

    def should_retry(self, *, attempt: int, status: int | None) -> bool:
        if attempt < 1:
            raise RetryPolicyError("attempt is 1-based")
        return attempt < self.max_attempts and self.is_retryable(status)

    def delay_for(
        self,
        *,
        attempt: int,
        headers: Mapping[str, str] | None = None,
    ) -> float:
        """Exponential backoff, capped, honouring Retry-After when offered."""

        if attempt < 1:
            raise RetryPolicyError("attempt is 1-based")
        if self.respect_retry_after and headers:
            raw = headers.get("Retry-After") or headers.get("retry-after")
            if raw and str(raw).strip().isdigit():
                return min(float(str(raw).strip()), self.max_delay_seconds)
        return min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)


# Publisher-specific defaults. MOPS returns intermittent 502s under sustained
# per-symbol querying, so it gets more attempts and a longer ceiling.
OFFICIAL_JSON = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=10.0)
MOPS_HTML = RetryPolicy(max_attempts=5, base_delay_seconds=2.0, max_delay_seconds=30.0)


def status_of(exception: BaseException) -> int | None:
    """Extract an HTTP status from a requests exception without importing it."""

    response = getattr(exception, "response", None)
    return getattr(response, "status_code", None) if response is not None else None


def headers_of(exception: BaseException) -> Mapping[str, str] | None:
    response = getattr(exception, "response", None)
    return getattr(response, "headers", None) if response is not None else None
