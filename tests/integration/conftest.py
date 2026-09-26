"""Explicit workspace profile for isolated synthetic integration checks."""

import pytest

from cosmas_os.config import settings


@pytest.fixture(autouse=True)
def local_workspace_profile(monkeypatch):
    # Application modules retain this singleton. Changing only api.settings in
    # signed-request fixtures leaves their local workflow gates disconnected.
    # Keep the environment and new Settings() defaults unchanged so default-off
    # configuration checks and explicit per-test overrides remain meaningful.
    monkeypatch.setattr(settings, "workspace_enabled", True)
