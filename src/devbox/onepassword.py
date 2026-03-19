"""1Password CLI (op) wrapper."""

from __future__ import annotations

import subprocess

from devbox.exceptions import OnePasswordError


def get_secret(reference: str, timeout: int = 10) -> str:
    """Resolve a single op:// reference via `op read`. Returns the secret value.

    Raises OnePasswordError on failure.
    """
    try:
        result = subprocess.run(
            ["op", "read", reference],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise OnePasswordError("1Password CLI (op) is not installed") from None
    except subprocess.TimeoutExpired:
        raise OnePasswordError(
            "1Password CLI timed out — is the vault locked?"
        ) from None

    if result.returncode != 0:
        raise OnePasswordError(result.stderr.strip())

    return result.stdout.strip()


def resolve_env_vars(env_vars: dict[str, str]) -> dict[str, str]:
    """Take a dict of env vars, resolve any op:// values via get_secret.

    Non-op:// values are passed through unchanged.
    Returns a new dict with all values resolved.
    Raises OnePasswordError if any op:// reference fails.
    """
    resolved: dict[str, str] = {}
    for key, value in env_vars.items():
        if value.startswith("op://"):
            resolved[key] = get_secret(value)
        else:
            resolved[key] = value
    return resolved
