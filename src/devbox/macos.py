"""macOS user management via dscl."""

from __future__ import annotations

import contextlib
import subprocess

from devbox.exceptions import MacOSUserError
from devbox.naming import DX_PREFIX, validate_name

_UID_MIN = 600
_UID_MAX = 699


def _macos_username(name: str) -> str:
    """Return the macOS username for a devbox name."""
    return f"{DX_PREFIX}{name}"


def _get_used_uids() -> set[int]:
    """Query dscl for all UIDs currently in use."""
    try:
        result = subprocess.run(
            ["dscl", ".", "-list", "/Users", "UniqueID"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise MacOSUserError("dscl is not available on this system") from None
    except subprocess.TimeoutExpired:
        raise MacOSUserError("dscl timed out while listing users") from None

    if result.returncode != 0:
        raise MacOSUserError(
            f"Failed to list users (exit code {result.returncode})"
        )

    uids: set[int] = set()
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                uids.add(int(parts[-1]))
            except ValueError:
                continue
    return uids


def _next_uid() -> int:
    """Find the next available UID in the 600-699 range."""
    used = _get_used_uids()
    for uid in range(_UID_MIN, _UID_MAX + 1):
        if uid not in used:
            return uid
    raise MacOSUserError(
        f"No available UIDs in range {_UID_MIN}-{_UID_MAX}. "
        "Run `devbox nuke` on unused devboxes to reclaim UIDs."
    )


def _run_dscl(args: list[str]) -> None:
    """Run a dscl command via sudo, raising MacOSUserError on failure."""
    cmd = ["sudo", "dscl", ".", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise MacOSUserError("sudo or dscl not found") from None
    except subprocess.TimeoutExpired:
        raise MacOSUserError(f"dscl timed out: {' '.join(args)}") from None
    if result.returncode != 0:
        raise MacOSUserError(
            f"dscl failed (exit code {result.returncode}): {' '.join(args)}"
        )


def _run_cmd(cmd: list[str], error_msg: str) -> None:
    """Run a command via sudo, raising MacOSUserError on failure."""
    try:
        result = subprocess.run(
            ["sudo", *cmd], capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise MacOSUserError(f"{error_msg}: command not found") from None
    except subprocess.TimeoutExpired:
        raise MacOSUserError(f"{error_msg}: timed out") from None
    if result.returncode != 0:
        raise MacOSUserError(
            f"{error_msg} (exit code {result.returncode})"
        )


def _validate_home_dir(home_dir: str) -> None:
    """Defense-in-depth: ensure home_dir is a safe path before sudo rm -rf."""
    if not home_dir.startswith("/Users/dx-"):
        raise MacOSUserError(f"Refusing to operate on path outside /Users/dx-*: {home_dir}")
    if ".." in home_dir:
        raise MacOSUserError(f"Path traversal detected in home directory: {home_dir}")


def _user_exists(username: str) -> bool:
    """Check if a macOS user exists."""
    try:
        result = subprocess.run(
            ["dscl", ".", "-read", f"/Users/{username}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise MacOSUserError("dscl is not available on this system") from None
    except subprocess.TimeoutExpired:
        raise MacOSUserError("dscl timed out checking user existence") from None
    return result.returncode == 0


def create_user(name: str) -> str:
    """Create a macOS user account for the devbox.

    Creates user ``dx-<name>`` with a UID in the 600-699 range, home directory
    at ``/Users/dx-<name>``, and shell ``/bin/zsh``.

    Returns the macOS username (``dx-<name>``).
    Raises :exc:`MacOSUserError` on failure.
    """
    validate_name(name)
    username = _macos_username(name)
    home_dir = f"/Users/{username}"

    if _user_exists(username):
        raise MacOSUserError(f"macOS user {username!r} already exists")

    uid = _next_uid()

    try:
        _run_dscl(["-create", f"/Users/{username}"])
        _run_dscl(["-create", f"/Users/{username}", "UniqueID", str(uid)])
        _run_dscl(["-create", f"/Users/{username}", "PrimaryGroupID", "20"])
        _run_dscl(["-create", f"/Users/{username}", "UserShell", "/bin/zsh"])
        _run_dscl(["-create", f"/Users/{username}", "NFSHomeDirectory", home_dir])
        _run_dscl(["-create", f"/Users/{username}", "RealName", f"Devbox {name}"])
        _run_cmd(
            ["createhomedir", "-u", username],
            f"Failed to create home directory for {username}",
        )
    except MacOSUserError:
        # Roll back partial user creation
        with contextlib.suppress(MacOSUserError):
            _run_dscl(["-delete", f"/Users/{username}"])
        raise

    return username


def delete_user(name: str) -> None:
    """Delete the macOS user account for the devbox.

    Removes user ``dx-<name>`` and their home directory.
    Idempotent — does not raise if the user is already gone.
    """
    validate_name(name)
    username = _macos_username(name)
    home_dir = f"/Users/{username}"

    if not _user_exists(username):
        return

    _run_dscl(["-delete", f"/Users/{username}"])

    _validate_home_dir(home_dir)
    _run_cmd(
        ["rm", "-rf", home_dir],
        f"Failed to remove home directory {home_dir}",
    )
