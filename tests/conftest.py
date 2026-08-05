"""Global offline guard for the default test suite."""
from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    """Fail every unmocked outbound socket attempt."""

    def blocked(*args, **kwargs):
        raise AssertionError("Real network access is forbidden during pytest")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture(autouse=True)
def stage14_child_env(monkeypatch):
    """Keep subprocess CLI tests from nesting Stage 14 status logging.

    Stage 14 wraps standalone commands so production invocations receive a
    status record.  Most repository CLI tests invoke those commands only to
    exercise the underlying stages; treating them as stage14 children avoids
    writing fault-injection logs into the project's real logs directory.
    """
    monkeypatch.setenv("AKSHARE_STAGE14_CHILD", "1")
