"""Core devbox operations — importable by AIDA plugin."""

from __future__ import annotations


def create_devbox(name: str, preset: str) -> dict:
    """Create a new devbox from the given preset. Returns the registry entry."""
    raise NotImplementedError


def list_devboxes() -> list[dict]:
    """Return all registered devboxes."""
    raise NotImplementedError
