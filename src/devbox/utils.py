# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Shared utility functions for devbox."""

from __future__ import annotations


def shell_escape(value: str) -> str:
    """Wrap a value in single quotes, escaping embedded single quotes."""
    return "'" + value.replace("'", "'\"'\"'") + "'"
