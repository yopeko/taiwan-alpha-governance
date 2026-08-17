"""Shared fixtures and environment guards.

The suite spans two environments. Some tests are self-contained and run
anywhere, including a clean CI runner. Others need the Taiwan Core checkout
and its durable archives, which exist only on the operator's machine.

Rather than let those fail on CI and train everyone to ignore red, they skip
with an explicit reason. `--strict-env` turns the skips into failures so the
operator can confirm locally that nothing is silently skipping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TAIWAN_CORE = Path(r"C:\project\tw-sepa-screener")
ARCHIVE_ROOT = TAIWAN_CORE / "data" / "raw_v2"


def pytest_addoption(parser):
    parser.addoption(
        "--strict-env",
        action="store_true",
        default=False,
        help="fail instead of skipping when the local data environment is absent",
    )


@pytest.fixture(scope="session")
def strict_env(request) -> bool:
    return bool(request.config.getoption("--strict-env"))


def require_local_environment(request, what: str) -> None:
    """Skip, or fail under --strict-env, when local data is unavailable."""

    message = f"{what} requires the Taiwan Core checkout and its archives"
    if request.config.getoption("--strict-env"):
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture
def taiwan_core(request) -> Path:
    if not TAIWAN_CORE.is_dir():
        require_local_environment(request, "this test")
    return TAIWAN_CORE


@pytest.fixture
def archive_root(request) -> Path:
    if not ARCHIVE_ROOT.is_dir():
        require_local_environment(request, "this test")
    return ARCHIVE_ROOT


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_local_data: requires the operator's archives"
    )
