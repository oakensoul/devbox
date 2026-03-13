"""GitHub API — SSH key lifecycle (add/remove)."""

from __future__ import annotations


def add_ssh_key(title: str, public_key: str) -> int:
    """Upload an SSH public key to GitHub. Returns the key ID."""
    raise NotImplementedError


def remove_ssh_key(key_id: int) -> None:
    """Remove an SSH key from GitHub by ID."""
    raise NotImplementedError
