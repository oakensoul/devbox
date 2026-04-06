# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""sshd configuration for devbox users."""

from __future__ import annotations

import re
import subprocess

from devbox.exceptions import SshdError

_SSH_GROUP = "com.apple.access_ssh"
_DX_USERNAME_RE = re.compile(r"^dx-[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_username(username: str) -> None:
    """Ensure username is a valid dx- prefixed devbox username."""
    if not _DX_USERNAME_RE.match(username):
        raise SshdError(
            f"Invalid devbox username: {username!r}. "
            "Must be dx- followed by a valid kebab-case name."
        )


def _run(cmd: list[str], error_msg: str) -> subprocess.CompletedProcess[str]:
    """Run a command, raising SshdError on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise SshdError(f"{error_msg}: command not found") from None
    except subprocess.TimeoutExpired:
        raise SshdError(f"{error_msg}: timed out") from None
    return result


def is_remote_login_enabled() -> bool:
    """Check if Remote Login (sshd) is enabled on macOS."""
    result = _run(
        ["sudo", "systemsetup", "-getremotelogin"],
        "Failed to check Remote Login status",
    )
    return "on" in result.stdout.lower()


def is_user_in_ssh_group(username: str) -> bool:
    """Check if a user is in the SSH access group."""
    _validate_username(username)
    result = _run(
        ["dseditgroup", "-o", "checkmember", "-m", username, _SSH_GROUP],
        f"Failed to check SSH group membership for {username}",
    )
    return result.returncode == 0


def add_user_to_ssh_group(username: str) -> None:
    """Add a user to the macOS SSH access group.

    This allows the user to connect via SSH when Remote Login is restricted
    to specific users/groups (macOS Ventura+).

    Raises :exc:`SshdError` on failure.
    """
    _validate_username(username)
    if is_user_in_ssh_group(username):
        return  # already a member

    result = _run(
        ["sudo", "dseditgroup", "-o", "edit", "-a", username, "-t", "user", _SSH_GROUP],
        f"Failed to add {username} to SSH access group",
    )
    if result.returncode != 0:
        raise SshdError(
            f"Failed to add {username} to SSH access group (exit code {result.returncode})"
        )


def remove_user_from_ssh_group(username: str) -> None:
    """Remove a user from the macOS SSH access group.

    Idempotent — does not raise if the user is not in the group.
    """
    _validate_username(username)
    if not is_user_in_ssh_group(username):
        return

    result = _run(
        ["sudo", "dseditgroup", "-o", "edit", "-d", username, "-t", "user", _SSH_GROUP],
        f"Failed to remove {username} from SSH access group",
    )
    if result.returncode != 0:
        raise SshdError(
            f"Failed to remove {username} from SSH access group (exit code {result.returncode})"
        )


def ensure_ssh_access(username: str) -> None:
    """Ensure a devbox user can SSH to localhost.

    Checks that Remote Login is enabled and adds the user to the SSH access
    group if needed. Raises :exc:`SshdError` if Remote Login is disabled.
    """
    _validate_username(username)
    if not is_remote_login_enabled():
        raise SshdError(
            "Remote Login (sshd) is not enabled. "
            "Enable it in System Settings → General → Sharing → Remote Login"
        )

    add_user_to_ssh_group(username)
