# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Authentication injection for devbox environments."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import NamedTuple

from devbox.exceptions import AuthError
from devbox.onepassword import get_secret
from devbox.presets import AwsSsoProfile, AwsStaticProfile, Preset
from devbox.ssh import chown_path
from devbox.utils import shell_escape

logger = logging.getLogger(__name__)

_ENV_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_AWS_ACCESS_KEY_RE = re.compile(r"^[A-Z0-9]{16,128}$")
_AWS_SECRET_KEY_RE = re.compile(r"^[A-Za-z0-9/+=]{16,128}$")


class AwsRender(NamedTuple):
    """Rendered contents for the two AWS config files plus SSO profile names."""

    config: str
    credentials: str
    sso_profiles: list[str]


def _validate_aws_keys(access_key: str, secret_key: str) -> None:
    """Validate AWS key values against expected patterns.

    Raises :exc:`AuthError` if either value is malformed.
    """
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


def _write_file_0600(path: Path, content: str) -> None:
    # O_NOFOLLOW rejects symlinks so a prior attacker can't redirect the write.
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)


def log_sso_hints(sso_profiles: list[str]) -> None:
    """Log ``aws sso login`` reminders for each SSO profile."""
    for profile_name in sso_profiles:
        logger.info(
            "SSO profile %r requires interactive login: aws sso login --profile %s",
            profile_name,
            profile_name,
        )


def render_aws_files(preset: Preset) -> AwsRender:
    """Build the contents of ``~/.aws/config`` and ``~/.aws/credentials``.

    Resolves ``op://`` references for static profiles via 1Password. Returns
    an :class:`AwsRender` tuple; both text fields are empty strings when
    ``preset.aws`` is unset or the corresponding section has no profiles.

    Raises :exc:`AuthError` on resolution or validation failure.
    """
    if preset.aws is None:
        return AwsRender("", "", [])

    config_parts: list[str] = []
    creds_parts: list[str] = []
    sso_profiles: list[str] = []

    for profile in preset.aws.profiles:
        if isinstance(profile, AwsStaticProfile):
            try:
                access_key = get_secret(profile.access_key_id)
                secret_key = get_secret(profile.secret_access_key)
            except Exception as exc:
                raise AuthError(
                    f"Failed to resolve AWS credentials for profile {profile.name!r}: {exc}"
                ) from exc

            _validate_aws_keys(access_key, secret_key)

            config_parts.append(
                f"[profile {profile.name}]\n"
                f"region = {profile.region}\n"
                f"output = {profile.output}\n"
            )
            creds_parts.append(
                f"[{profile.name}]\n"
                f"aws_access_key_id = {access_key}\n"
                f"aws_secret_access_key = {secret_key}\n"
            )
        elif isinstance(profile, AwsSsoProfile):
            config_parts.append(
                f"[profile {profile.name}]\n"
                f"sso_start_url = {profile.sso_start_url}\n"
                f"sso_region = {profile.sso_region}\n"
                f"sso_account_id = {profile.sso_account_id}\n"
                f"sso_role_name = {profile.sso_role_name}\n"
                f"region = {profile.region}\n"
                f"output = {profile.output}\n"
            )
            sso_profiles.append(profile.name)

    return AwsRender("\n".join(config_parts), "\n".join(creds_parts), sso_profiles)


def inject_aws_auth(home_dir: Path, preset: Preset, username: str) -> list[str]:
    """Write ``~/.aws/config`` and ``~/.aws/credentials`` from the preset's aws block.

    Overwrites both files wholesale. Skips the credentials file if no static
    profiles are present. Creates ``~/.aws`` with 0700 perms and files with
    0600, chowned to the devbox user.

    No-op if ``preset.aws`` is not set. Returns the list of SSO profile names
    (for which the caller should print an ``aws sso login`` hint).

    Raises :exc:`AuthError` on failure.
    """
    if preset.aws is None:
        return []

    rendered = render_aws_files(preset)

    aws_dir = home_dir / ".aws"
    try:
        aws_dir.mkdir(mode=0o700, exist_ok=True)
        # Re-apply perms in case the dir pre-existed with looser bits.
        os.chmod(aws_dir, 0o700)
        _write_file_0600(aws_dir / "config", rendered.config)
        if rendered.credentials:
            _write_file_0600(aws_dir / "credentials", rendered.credentials)
        chown_path(aws_dir, username)
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Failed to write AWS credentials: {exc}") from exc

    return rendered.sso_profiles


def inject_auth(home_dir: Path, preset: Preset, username: str) -> list[str]:
    """Dispatch auth injection based on the preset's provider and aws block.

    AWS profile injection is orthogonal to ``provider``: any preset with an
    ``aws:`` block gets ``~/.aws`` written, regardless of whether the devbox
    itself runs locally or on EC2. Returns the list of SSO profile names
    present (empty when no interactive login is required).

    Raises :exc:`AuthError` on unknown provider or injection failure.
    """
    if preset.provider not in ("local", "aws"):
        raise AuthError(f"Unknown provider: {preset.provider!r}")
    return inject_aws_auth(home_dir, preset, username)
