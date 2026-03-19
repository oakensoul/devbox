"""Shared utility functions for devbox."""

from __future__ import annotations


def shell_escape(value: str) -> str:
    """Wrap a value in single quotes, escaping embedded single quotes."""
    return "'" + value.replace("'", "'\"'\"'") + "'"
