"""Tests for the shared retry policy.

The case that motivated this module gets an explicit test: a MOPS 502 must be
retryable, because treating it as terminal is what silently dropped seven
symbol-years in the TPEx action capture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from retry_policy import (  # noqa: E402
    MOPS_HTML,
    OFFICIAL_JSON,
    RetryPolicy,
    RetryPolicyError,
    headers_of,
    status_of,
)


class TestRetryability:
    @pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
    def test_transient_statuses_are_retryable(self, status):
        assert OFFICIAL_JSON.is_retryable(status)

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422])
    def test_client_errors_are_not_retryable(self, status):
        assert not OFFICIAL_JSON.is_retryable(status)

    def test_transport_failure_with_no_response_is_retryable(self):
        assert OFFICIAL_JSON.is_retryable(None)

    def test_mops_502_is_retryable(self):
        # The exact failure that dropped seven TPEx symbol-years.
        assert MOPS_HTML.is_retryable(502)
        assert MOPS_HTML.should_retry(attempt=1, status=502)


class TestShouldRetry:
    def test_stops_at_the_attempt_ceiling(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(attempt=2, status=502)
        assert not policy.should_retry(attempt=3, status=502)

    def test_never_retries_a_non_retryable_status(self):
        assert not RetryPolicy(max_attempts=5).should_retry(attempt=1, status=404)

    def test_attempt_must_be_one_based(self):
        with pytest.raises(RetryPolicyError):
            OFFICIAL_JSON.should_retry(attempt=0, status=500)


class TestBackoff:
    def test_delay_grows_exponentially(self):
        policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=30.0)
        assert policy.delay_for(attempt=1) == 1.0
        assert policy.delay_for(attempt=2) == 2.0
        assert policy.delay_for(attempt=3) == 4.0

    def test_delay_is_capped(self):
        policy = RetryPolicy(base_delay_seconds=2.0, max_delay_seconds=5.0, max_attempts=10)
        assert policy.delay_for(attempt=9) == 5.0

    def test_retry_after_header_wins_when_offered(self):
        assert OFFICIAL_JSON.delay_for(attempt=1, headers={"Retry-After": "7"}) == 7.0

    def test_retry_after_is_still_capped(self):
        policy = RetryPolicy(max_delay_seconds=10.0)
        assert policy.delay_for(attempt=1, headers={"Retry-After": "600"}) == 10.0

    def test_non_numeric_retry_after_falls_back_to_backoff(self):
        value = OFFICIAL_JSON.delay_for(attempt=2, headers={"Retry-After": "Wed, 21 Oct"})
        assert value == 2.0

    def test_header_lookup_is_case_insensitive(self):
        assert OFFICIAL_JSON.delay_for(attempt=1, headers={"retry-after": "3"}) == 3.0

    def test_retry_after_can_be_disabled(self):
        policy = RetryPolicy(respect_retry_after=False, base_delay_seconds=1.0)
        assert policy.delay_for(attempt=1, headers={"Retry-After": "60"}) == 1.0


class TestPolicyValidation:
    @pytest.mark.parametrize("attempts", [0, 11, -1])
    def test_attempt_bounds_are_enforced(self, attempts):
        with pytest.raises(RetryPolicyError):
            RetryPolicy(max_attempts=attempts)

    def test_max_delay_below_base_is_rejected(self):
        with pytest.raises(RetryPolicyError):
            RetryPolicy(base_delay_seconds=10.0, max_delay_seconds=1.0)

    def test_negative_base_delay_is_rejected(self):
        with pytest.raises(RetryPolicyError):
            RetryPolicy(base_delay_seconds=-1.0)


class TestExceptionHelpers:
    class _Response:
        status_code = 502
        headers = {"Retry-After": "4"}

    class _Error(Exception):
        response = None

    def test_status_and_headers_are_extracted(self):
        error = self._Error()
        error.response = self._Response()
        assert status_of(error) == 502
        assert headers_of(error)["Retry-After"] == "4"

    def test_missing_response_yields_none(self):
        assert status_of(self._Error()) is None
        assert headers_of(self._Error()) is None


class TestPublisherProfiles:
    def test_mops_is_more_patient_than_the_json_endpoints(self):
        assert MOPS_HTML.max_attempts > OFFICIAL_JSON.max_attempts
        assert MOPS_HTML.max_delay_seconds > OFFICIAL_JSON.max_delay_seconds
