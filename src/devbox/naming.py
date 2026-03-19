"""Kebab-case name validation for devbox names."""

from __future__ import annotations

import re

_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# GitHub username: alphanumeric, hyphens allowed (not leading/trailing).
GITHUB_ACCOUNT_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$")

# macOS username prefix for devbox users.
DX_PREFIX = "dx-"


def validate_name(name: str) -> str:
    """Validate a devbox name is valid kebab-case.

    A valid name matches ``[a-z0-9]+(-[a-z0-9]+)*``:
    - Lowercase letters and digits only (no uppercase, no underscores)
    - Segments separated by single hyphens
    - No leading or trailing hyphens, no consecutive hyphens
    - Must not be empty

    Returns the name if valid, raises :exc:`ValueError` if not.
    """
    if not name:
        raise ValueError("Devbox name must not be empty.")

    if not _KEBAB_RE.match(name):
        raise ValueError(
            f"Invalid devbox name {name!r}. "
            "Names must be lowercase kebab-case (e.g. 'my-devbox', 'f1-experiment'): "
            "only lowercase letters, digits, and single hyphens between segments are allowed; "
            "no leading/trailing hyphens, consecutive hyphens, uppercase letters, "
            "underscores, spaces, or special characters."
        )

    return name
