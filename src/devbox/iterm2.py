"""iTerm2 dynamic profile creation/removal."""

from __future__ import annotations

from typing import Any


def create_profile(name: str, preset: dict[str, Any]) -> None:
    """Create an iTerm2 dynamic profile for the devbox."""
    raise NotImplementedError


def remove_profile(name: str) -> None:
    """Remove the iTerm2 dynamic profile for the devbox."""
    raise NotImplementedError
