"""macOS user management via dscl."""

from __future__ import annotations


def create_user(username: str) -> None:
    """Create a macOS user account for the devbox."""
    raise NotImplementedError


def delete_user(username: str) -> None:
    """Delete a macOS user account."""
    raise NotImplementedError
