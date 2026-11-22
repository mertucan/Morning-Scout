"""Shared fixtures. All network access is blocked: tests must never touch the internet."""

from __future__ import annotations

import socket

import pytest

from morning_scout.privacy import redactor


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guard(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network access is not allowed in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture(autouse=True)
def _reset_redactor() -> None:
    redactor.clear()
    yield
    redactor.clear()
