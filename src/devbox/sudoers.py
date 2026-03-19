"""Sudoers configuration for passwordless devbox operations."""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

from devbox.exceptions import SudoersError

SUDOERS_PATH = Path("/etc/sudoers.d/devbox")

SUDOERS_CONTENT = """\
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
%admin ALL=(root) NOPASSWD: /usr/bin/pwpolicy -u dx-* -disableuser
"""


def is_configured(path: Path | None = None) -> bool:
    """Check if the sudoers file exists and contains the expected content."""
    target = path or SUDOERS_PATH
    try:
        return target.read_text() == SUDOERS_CONTENT
    except OSError:
        return False


def validate() -> None:
    """Raise SudoersError if the sudoers file is not correctly configured."""
    if not is_configured():
        raise SudoersError(
            f"Sudoers file {SUDOERS_PATH} is not configured.\n"
            "Run `devbox sudoers install` or manually create it with:\n"
            f"  sudo tee {SUDOERS_PATH} <<'EOF'\n"
            f"{SUDOERS_CONTENT}EOF\n"
            f"  sudo chmod 0440 {SUDOERS_PATH}"
        )


def install(path: Path | None = None) -> None:
    """Write the sudoers file with correct permissions.

    Writes to a temporary file first, validates with ``visudo -c``,
    then copies to the final location and sets mode 0440.

    Raises :exc:`SudoersError` on failure.
    """
    target = path or SUDOERS_PATH

    # Write content to a temporary file for validation
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="devbox-sudoers-")
        try:
            os.write(tmp_fd, SUDOERS_CONTENT.encode())
        finally:
            os.close(tmp_fd)
    except OSError as exc:
        raise SudoersError(f"Failed to write temp sudoers file: {exc}") from None

    try:
        # Validate with visudo before installing
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
                f"visudo validation failed (exit code {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        # Copy validated file to the target via sudo tee
        try:
            result = subprocess.run(
                ["sudo", "tee", str(target)],
                input=SUDOERS_CONTENT,
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

        # Set permissions to 0440
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
        # Always clean up the temp file
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
