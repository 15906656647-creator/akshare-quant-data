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
