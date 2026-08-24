"""Every request kind in a capture must go through the shared retry policy.

`scripts/lib/retry_policy.py` was written because the TPEx action capture
retried its listing request and not its per-announcement detail requests:
seven MOPS 502s became silent gaps, and since resume keys on the listing
observation, no re-run would ever have gone back for them.

The module landed. The call site did not change. Centralising a decision only
helps if something checks that each request kind actually takes that path, so
that check is here rather than in a comment.

Two layers, because either alone is weak: the helper's own behaviour, and an
AST guard that the capture routes its requests through it. The AST is read
rather than pattern-matched so a request moved into a differently named
closure still has to satisfy the rule.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from retry_policy import (  # noqa: E402
    MOPS_HTML,
    RetryPolicy,
    request_with_retry,
)

TPEX_ACTIONS = REPO / "scripts" / "m3" / "capture_tpex_actions.py"
REQUEST_METHODS = {"post", "get"}


class Boom(Exception):
    """Stands in for requests.RequestException without importing requests."""

    def __init__(self, status: int | None = None) -> None:
        super().__init__(f"status={status}")
        self.response = type("R", (), {"status_code": status, "headers": {}})()


class TestRequestWithRetry:
    def test_returns_the_result_and_the_attempt_count(self):
        result, attempts = request_with_retry(MOPS_HTML, lambda attempt: "ok")
        assert (result, attempts) == ("ok", 1)

    def test_retries_a_transient_status_until_it_succeeds(self):
        seen: list[int] = []
        slept: list[float] = []

        def send(attempt: int) -> str:
            seen.append(attempt)
            if attempt < 3:
                raise Boom(502)
            return "ok"

        result, attempts = request_with_retry(
            MOPS_HTML, send, retry_on=Boom, sleep=slept.append
        )
        assert result == "ok"
        assert attempts == 3
        assert seen == [1, 2, 3]
        # One wait per retry, never one after the attempt that succeeded.
        assert len(slept) == 2

    def test_reraises_once_the_ceiling_is_reached(self):
        policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.0, max_delay_seconds=0.0)
        seen: list[int] = []

        def send(attempt: int) -> str:
            seen.append(attempt)
            raise Boom(502)

        with pytest.raises(Boom):
            request_with_retry(policy, send, retry_on=Boom, sleep=lambda _: None)
        assert seen == [1, 2, 3]

    def test_does_not_retry_a_status_that_repeating_cannot_fix(self):
        seen: list[int] = []

        def send(attempt: int) -> str:
            seen.append(attempt)
            raise Boom(404)

        with pytest.raises(Boom):
            request_with_retry(MOPS_HTML, send, retry_on=Boom, sleep=lambda _: None)
        assert seen == [1], "a 404 was repeated; the request itself is wrong"

    def test_an_unexpected_exception_type_is_not_retried_or_swallowed(self):
        """The caller names what is transient. Everything else is a defect."""

        def send(attempt: int) -> str:
            raise ValueError("parser defect")

        with pytest.raises(ValueError):
            request_with_retry(MOPS_HTML, send, retry_on=Boom, sleep=lambda _: None)


def retry_wrapped_functions(tree: ast.Module) -> set[str]:
    """Names passed to `request_with_retry` as the thing it should run."""

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "request_with_retry":
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Name):
            names.add(node.args[1].id)
    return names


def function_spans(tree: ast.Module, names: set[str]) -> list[tuple[int, int]]:
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]


def request_call_lines(tree: ast.Module) -> list[tuple[int, str]]:
    """HTTP calls, told apart from `dict.get` by carrying a `timeout`.

    Discriminating on the argument rather than on the receiver's name means
    renaming the session variable cannot hide a request from this test.
    """

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in REQUEST_METHODS:
            continue
        if not any(k.arg == "timeout" for k in node.keywords):
            continue
        found.append((node.lineno, node.func.attr))
    return found


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(TPEX_ACTIONS.read_text(encoding="utf-8"))


class TestTpexActionCallSites:
    """The capture this backfill is about to run 4,500 times."""

    def test_the_capture_still_makes_requests(self, tree):
        """Guards the guard: no request sites would make the rule vacuous."""

        assert request_call_lines(tree), "found no HTTP calls; this test proves nothing"

    def test_both_request_kinds_are_wrapped(self, tree):
        """Listing and detail. The detail one is the whole reason this exists."""

        assert len(retry_wrapped_functions(tree)) >= 2, (
            "fewer than two request kinds go through the retry helper; "
            "the 2026-08 defect was exactly one kind being left out"
        )

    def test_every_request_is_inside_a_retried_function(self, tree):
        spans = function_spans(tree, retry_wrapped_functions(tree))
        assert spans, "nothing is passed to request_with_retry"
        unguarded = [
            (line, attr)
            for line, attr in request_call_lines(tree)
            if not any(lo <= line <= hi for lo, hi in spans)
        ]
        assert not unguarded, (
            f"request(s) outside any retried function: {unguarded}. "
            "A request kind with no retry becomes a silent gap that resume "
            "will skip, because resume keys on the listing observation."
        )

    def test_the_retry_ceiling_is_not_capped_below_the_publisher_policy(self, tree):
        """A call site that quietly lowers the policy is not using the policy."""

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) != "add_argument":
                continue
            flags = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if "--retry-limit" not in flags:
                continue
            for keyword in node.keywords:
                if keyword.arg != "default":
                    continue
                assert not isinstance(keyword.value, ast.Constant), (
                    "--retry-limit defaults to a literal; it should defer to "
                    "the publisher policy so the two cannot drift apart"
                )
                return
        pytest.fail("no --retry-limit default found to check")
