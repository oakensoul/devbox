# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Sudoers configuration for passwordless devbox operations."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from devbox.exceptions import SudoersError

SUDOERS_PATH = Path("/etc/sudoers.d/devbox")

_DX_USERNAME_RE = re.compile(r"^dx-[a-z0-9]+(-[a-z0-9]+)*$")

SUDOERS_HEADER = """\
# Managed by devbox — do not edit manually
%admin ALL=(root) NOPASSWD: /usr/bin/dscl . -create /Users/dx-*
%admin ALL=(root) NOPASSWD: /usr/bin/dscl . -delete /Users/dx-*
%admin ALL=(root) NOPASSWD: /usr/sbin/createhomedir -u dx-*
%admin ALL=(root) NOPASSWD: /bin/rm -rf /Users/dx-*
%admin ALL=(root) NOPASSWD: /usr/sbin/dseditgroup -o edit -a dx-* -t user com.apple.access_ssh
%admin ALL=(root) NOPASSWD: /usr/sbin/dseditgroup -o edit -d dx-* -t user com.apple.access_ssh
%admin ALL=(root) NOPASSWD: /usr/sbin/dseditgroup -o checkmember -m dx-* com.apple.access_ssh
%admin ALL=(root) NOPASSWD: /usr/sbin/systemsetup -getremotelogin
%admin ALL=(root) NOPASSWD: /usr/bin/chown -R dx-*\\:staff /Users/dx-*
%admin ALL=(root) NOPASSWD: /usr/bin/chown -R *\\:staff /Users/dx-*
%admin ALL=(root) NOPASSWD: /bin/mkdir -p /Users/dx-*
%admin ALL=(root) NOPASSWD: /usr/bin/pwpolicy -u dx-* -disableuser
"""

_RUNAS_LINE_FMT = "%admin ALL=({username}) NOPASSWD: ALL\n"


def _runas_line(username: str) -> str:
    """Build a per-user runas sudoers line."""
    if not _DX_USERNAME_RE.match(username):
        raise SudoersError(f"Invalid devbox username for sudoers: {username!r}")
    return _RUNAS_LINE_FMT.format(username=username)


def _read_sudoers(path: Path | None = None) -> str:
    """Read the current sudoers file, returning empty string if missing."""
    target = path or SUDOERS_PATH
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_sudoers(content: str, path: Path | None = None) -> None:
    """Validate and write sudoers content atomically via visudo + sudo tee."""
    target = path or SUDOERS_PATH

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="devbox-sudoers-")
        try:
            os.write(tmp_fd, content.encode())
        finally:
            os.close(tmp_fd)
    except OSError as exc:
        raise SudoersError(f"Failed to write temp sudoers file: {exc}") from None

    try:
        try:
            result = subprocess.run(
                ["visudo", "-c", "-f", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise SudoersError("visudo not found") from None
        except subprocess.TimeoutExpired:
            raise SudoersError("visudo timed out") from None

        if result.returncode != 0:
            raise SudoersError(
                f"visudo validation failed (exit code {result.returncode}): {result.stderr.strip()}"
            )

        try:
            result = subprocess.run(
                ["sudo", "tee", str(target)],
                input=content,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise SudoersError("sudo or tee not found") from None
        except subprocess.TimeoutExpired:
            raise SudoersError("timed out writing sudoers file") from None

        if result.returncode != 0:
            raise SudoersError(
                f"Failed to write sudoers file (exit code {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        try:
            result = subprocess.run(
                ["sudo", "chmod", "0440", str(target)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise SudoersError("sudo or chmod not found") from None
        except subprocess.TimeoutExpired:
            raise SudoersError("timed out setting permissions") from None

        if result.returncode != 0:
            raise SudoersError(
                f"Failed to set permissions on sudoers file "
                f"(exit code {result.returncode}): {result.stderr.strip()}"
            )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def is_configured(path: Path | None = None) -> bool:
    """Check if the sudoers file exists and contains the base rules."""
    content = _read_sudoers(path)
    return content.startswith(SUDOERS_HEADER)


def validate() -> None:
    """Raise SudoersError if the sudoers file is not correctly configured."""
    if not is_configured():
        raise SudoersError(
            f"Sudoers file {SUDOERS_PATH} is not configured.\n"
            "Run `devbox sudoers install` to set it up."
        )


def install(path: Path | None = None) -> None:
    """Write the base sudoers file with correct permissions."""
    _write_sudoers(SUDOERS_HEADER, path)


def add_user(username: str, path: Path | None = None) -> None:
    """Add a per-devbox runas rule so admin can run commands as this user."""
    line = _runas_line(username)
    content = _read_sudoers(path)

    if not content.startswith(SUDOERS_HEADER):
        content = SUDOERS_HEADER

    if line in content:
        return  # already present

    content += line
    _write_sudoers(content, path)


def remove_user(username: str, path: Path | None = None) -> None:
    """Remove the per-devbox runas rule for this user."""
    line = _runas_line(username)
    content = _read_sudoers(path)

    if line not in content:
        return  # nothing to remove

    content = content.replace(line, "")
    _write_sudoers(content, path)
