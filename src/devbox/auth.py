# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Authentication injection for devbox environments."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from devbox.exceptions import AuthError
from devbox.onepassword import get_secret
from devbox.presets import Preset
from devbox.ssh import chown_path
from devbox.utils import shell_escape

logger = logging.getLogger(__name__)

_ENV_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_AWS_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")
_AWS_ACCESS_KEY_RE = re.compile(r"^[A-Z0-9]{16,128}$")
_AWS_SECRET_KEY_RE = re.compile(r"^[A-Za-z0-9/+=]{16,128}$")


def _validate_aws_values(region: str, access_key: str, secret_key: str) -> None:
    """Validate AWS credential values against expected patterns.

    Raises :exc:`AuthError` if any value is malformed.
    """
    if not _AWS_REGION_RE.match(region):
        raise AuthError(f"Invalid AWS region format: {region!r}")
    if not _AWS_ACCESS_KEY_RE.match(access_key):
        raise AuthError("Invalid AWS access key format")
    if not _AWS_SECRET_KEY_RE.match(secret_key):
        raise AuthError("Invalid AWS secret key format")


def _write_env_export(env_path: Path, key: str, value: str) -> None:
    """Append an ``export KEY=VALUE`` line to *env_path*.

    Validates that *key* is a legal shell variable name.
    Raises :exc:`AuthError` if the key is invalid.
    """
    if not _ENV_KEY_RE.match(key):
        raise AuthError(f"Invalid environment variable name: {key!r}")
    line = f"export {key}={shell_escape(value)}\n"
    fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)


def inject_aws_auth(home_dir: Path, preset: Preset, username: str) -> None:
    """Resolve AWS credentials from 1Password and write ~/.aws config files.

    Uses ``preset.aws_profile`` to construct the 1Password references.
    Creates ``~/.aws/config`` and ``~/.aws/credentials`` with proper
    permissions (0700 dir, 0600 files), chowned to the devbox user.

    Only applies when ``preset.provider == "aws"``.
    Raises :exc:`AuthError` on failure.
    """
    if preset.provider != "aws":
        msg = f"inject_aws_auth requires provider 'aws', got {preset.provider!r}"
        raise AuthError(msg)

    if not preset.aws_profile:
        raise AuthError("preset.aws_profile is required for AWS auth injection")

    profile = preset.aws_profile

    try:
        access_key = get_secret(f"op://Development/{profile}/access-key-id")
        secret_key = get_secret(f"op://Development/{profile}/secret-access-key")
        region = get_secret(f"op://Development/{profile}/region")
    except Exception as exc:
        raise AuthError(f"Failed to resolve AWS credentials: {exc}") from exc

    _validate_aws_values(region, access_key, secret_key)

    aws_dir = home_dir / ".aws"

    try:
        aws_dir.mkdir(mode=0o700, exist_ok=True)

        config_path = aws_dir / "config"
        config_content = f"[profile default]\nregion = {region}\noutput = json\n"
        fd = os.open(
            str(config_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(config_content)

        credentials_path = aws_dir / "credentials"
        credentials_content = (
            f"[default]\naws_access_key_id = {access_key}\naws_secret_access_key = {secret_key}\n"
        )
        fd = os.open(
            str(credentials_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(credentials_content)

        chown_path(aws_dir, username)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Failed to write AWS credentials: {exc}") from exc


def inject_auth(home_dir: Path, preset: Preset, username: str) -> None:
    """Dispatch auth injection based on preset provider.

    - ``"local"``: no-op (user runs ``claude /login`` after first SSH)
    - ``"aws"``: injects AWS credentials

    Raises :exc:`AuthError` on failure.
    """
    if preset.provider == "local":
        return  # Claude Code auth handled via `claude /login` over SSH
    elif preset.provider == "aws":
        inject_aws_auth(home_dir, preset, username)
    else:
        raise AuthError(f"Unknown provider: {preset.provider!r}")
