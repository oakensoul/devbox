"""Core devbox operations — importable by AIDA plugin."""

from __future__ import annotations

from typing import Any


def create_devbox(name: str, preset: str) -> dict[str, Any]:
    """Create a new devbox from the given preset. Returns the registry entry."""
    raise NotImplementedError


def list_devboxes() -> list[dict[str, Any]]:
    """Return all registered devboxes."""
    raise NotImplementedError


def nuke_devbox(name: str) -> None:
    """Destroy a devbox and clean up all resources."""
    raise NotImplementedError


def rebuild_devbox(name: str) -> None:
    """Tear down and recreate a devbox with the same preset."""
    raise NotImplementedError
