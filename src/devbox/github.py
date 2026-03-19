"""GitHub API — SSH key lifecycle (add/remove)."""

from __future__ import annotations


def add_ssh_key(title: str, public_key: str, github_account: str) -> str:
    """Upload an SSH public key to GitHub. Returns the key ID as a string."""
    raise NotImplementedError


def remove_ssh_key(key_id: str, github_account: str) -> None:
    """Remove an SSH key from GitHub by key ID string."""
    raise NotImplementedError
