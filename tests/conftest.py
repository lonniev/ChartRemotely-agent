"""Shared fixtures."""

import pytest

from chartremotely import recent


@pytest.fixture(autouse=True)
def _private_recent(tmp_path, monkeypatch):
    """No test writes the real ~/.config/chartremotely/recent.json."""
    monkeypatch.setattr(recent, "PATH", tmp_path / "recent.json")
