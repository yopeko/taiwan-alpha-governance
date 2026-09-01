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


# Skips that have nothing to do with whether the data is here. Everything else
# becomes a failure under `--strict-env`, so this list is the whole exemption
# surface and it is meant to stay short.
ENVIRONMENT_INDEPENDENT_SKIPS = (
    # A parametrised case for a script that does not take the flag being tested.
    "takes no --interval",
    # Deliberate: the assertion is made by the presence test just above it.
    "covered by the presence test above",
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Make `--strict-env` mean what its help text says.

    The flag promised that skips become failures "so the operator can confirm
    nothing is silently skipping". It only ever covered the two fixtures in
    this file. Thirty-eight `pytest.skip` calls elsewhere went straight past
    it -- including every one that fires when an archive or the warehouse is
    missing, which is exactly the set it was written for.

    A guard that covers two of forty cases is worse than no guard, because it
    is believed. The hook is here rather than at those call sites for the same
    reason: a rule enforced in one place cannot be forgotten in the next file.

    On a machine with the data, a skip under this flag means something went
    unchecked. That is a failure, and the message says which one.
    """

    outcome = yield
    report = outcome.get_result()

    if not item.config.getoption("--strict-env"):
        return
    if not report.skipped or hasattr(report, "wasxfail"):
        return

    reason = ""
    if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        reason = str(report.longrepr[2])
    if any(allowed in reason for allowed in ENVIRONMENT_INDEPENDENT_SKIPS):
        return

    report.outcome = "failed"
    report.longrepr = (
        f"--strict-env: this test skipped instead of running, and its reason "
        f"is not one of the environment-independent cases in "
        f"tests/conftest.py. On a machine that has the data, a skip here means "
        f"something went unchecked.\n\nreason: {reason}"
    )
