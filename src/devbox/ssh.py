# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""SSH key generation and authorized_keys management."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import requests

from devbox.exceptions import SSHError
from devbox.naming import GITHUB_ACCOUNT_RE

_SSH_KEY_PREFIX_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519)\s")
_DX_USERNAME_RE = re.compile(r"^dx-[a-z0-9]+(-[a-z0-9]+)*$")
_CONFIG_PATH = Path.home() / ".devbox" / "config.json"


def copy_keypair(home_dir: Path, ssh_key: str = "id_ed25519") -> str:
    """Copy an SSH keypair from the parent user's ~/.ssh into the devbox home.

    Copies both the private key and ``.pub`` file, sets correct permissions,
    and returns the public key string.
    """
    if ".." in ssh_key or "/" in ssh_key:
        raise SSHError(f"Invalid ssh_key name: {ssh_key!r}")

    parent_ssh = Path.home() / ".ssh"
    src_private = parent_ssh / ssh_key
    src_public = parent_ssh / f"{ssh_key}.pub"

    if not src_private.exists():
        raise SSHError(f"SSH private key not found: {src_private}")
    if not src_public.exists():
        raise SSHError(f"SSH public key not found: {src_public}")

    ssh_dir = home_dir / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    import shutil

    dst_private = ssh_dir / ssh_key
    dst_public = ssh_dir / f"{ssh_key}.pub"

    shutil.copy2(src_private, dst_private)
    os.chmod(dst_private, 0o600)

    shutil.copy2(src_public, dst_public)
    os.chmod(dst_public, 0o644)

    # Write an ssh config so git uses the right key.
    # StrictHostKeyChecking=accept-new accepts GitHub's key on first use
    # without prompting, while still detecting changed keys thereafter.
    ssh_config = ssh_dir / "config"
    ssh_config.write_text(
        f"Host github.com\n"
        f"  IdentityFile ~/.ssh/{ssh_key}\n"
        f"  IdentitiesOnly yes\n"
        f"  StrictHostKeyChecking accept-new\n",
        encoding="utf-8",
    )
    os.chmod(ssh_config, 0o600)

    # Pre-populate known_hosts with GitHub's host keys so git clone
    # doesn't fail on first use in an SSH-only environment.
    try:
        result = subprocess.run(
            ["ssh-keyscan", "-t", "ed25519,rsa,ecdsa", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            known_hosts = ssh_dir / "known_hosts"
            known_hosts.write_text(result.stdout, encoding="utf-8")
            os.chmod(known_hosts, 0o600)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # non-fatal — user can accept manually

    return src_public.read_text(encoding="utf-8").strip()


def _get_parent_github_user() -> str:
    """Read the parent GitHub username from config."""
    if not _CONFIG_PATH.exists():
        raise SSHError(
            f"Config file not found: {_CONFIG_PATH}. "
            "Run `devbox setup` or create it with: "
            '{"parent_github_user": "your-github-username"}'
        )

    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SSHError(f"Failed to read config: {exc}") from exc

    username: str | None = data.get("parent_github_user")
    if not username:
        raise SSHError(f"parent_github_user not set in config. Add it to {_CONFIG_PATH}")
    return username


def _validate_ssh_keys(content: str) -> list[str]:
    """Validate that content looks like SSH public keys. Returns valid lines."""
    valid_keys: list[str] = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if _SSH_KEY_PREFIX_RE.match(line):
            valid_keys.append(line)
    return valid_keys


def chown_path(path: Path, username: str) -> None:
    """Change ownership of path to the given user via sudo chown -R.

    Raises :exc:`SSHError` if the username is invalid or chown fails.
    """
    if not _DX_USERNAME_RE.match(username):
        raise SSHError(f"Invalid target user for chown: {username!r}")
    try:
        result = subprocess.run(
            ["sudo", "chown", "-R", f"{username}:staff", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise SSHError("chown command not found") from None
    except subprocess.TimeoutExpired:
        raise SSHError("chown timed out") from None
    if result.returncode != 0:
        raise SSHError(
            f"Failed to set ownership on {path} to {username} (exit code {result.returncode})"
        )


def populate_authorized_keys(
    home_dir: Path,
    github_user: str | None = None,
    target_user: str | None = None,
    timeout: int = 10,
) -> int:
    """Populate authorized_keys from the parent user's GitHub public keys.

    Fetches keys from ``https://github.com/<user>.keys`` and writes them to
    ``<home_dir>/.ssh/authorized_keys``. If ``target_user`` is provided,
    chowns the ``.ssh`` directory to that user for sshd StrictModes.

    Returns the number of keys written.
    """
    if github_user is None:
        github_user = _get_parent_github_user()

    if not GITHUB_ACCOUNT_RE.match(github_user) or len(github_user) > 39:
        raise SSHError(f"Invalid GitHub username: {github_user!r}")

    url = f"https://github.com/{github_user}.keys"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SSHError(f"Failed to fetch SSH keys from GitHub: {exc}") from exc

    keys = _validate_ssh_keys(response.text)
    if not keys:
        raise SSHError(f"No valid SSH public keys found for GitHub user {github_user!r}")

    ssh_dir = home_dir / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    auth_keys_path = ssh_dir / "authorized_keys"
    auth_keys_path.write_text("\n".join(keys) + "\n", encoding="utf-8")
    os.chmod(auth_keys_path, 0o600)

    if target_user is not None:
        chown_path(ssh_dir, target_user)

    return len(keys)


_CONFIG_LOCAL_PATH = Path.home() / ".ssh" / "config.local"
_MARKER_START = "# devbox:{name} start\n"
_MARKER_END = "# devbox:{name} end\n"


def add_ssh_config_entry(name: str, ssh_key: str) -> None:
    """Add an SSH config entry for the devbox to ~/.ssh/config.local."""
    username = f"dx-{name}"
    start = _MARKER_START.format(name=name)
    end = _MARKER_END.format(name=name)

    entry = (
        f"{start}"
        f"Host {username}\n"
        f"    HostName localhost\n"
        f"    User {username}\n"
        f"    IdentityFile ~/.ssh/{ssh_key}\n"
        f"    IdentitiesOnly yes\n"
        f"{end}"
    )

    content = ""
    if _CONFIG_LOCAL_PATH.exists():
        content = _CONFIG_LOCAL_PATH.read_text(encoding="utf-8")

    # Already present — replace it
    if start in content:
        import re as _re
        pattern = _re.escape(start) + r".*?" + _re.escape(end)
        content = _re.sub(pattern, entry, content, flags=_re.DOTALL)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += entry

    _CONFIG_LOCAL_PATH.write_text(content, encoding="utf-8")


def remove_ssh_config_entry(name: str) -> None:
    """Remove the SSH config entry for the devbox from ~/.ssh/config.local."""
    if not _CONFIG_LOCAL_PATH.exists():
        return

    start = _MARKER_START.format(name=name)
    end = _MARKER_END.format(name=name)
    content = _CONFIG_LOCAL_PATH.read_text(encoding="utf-8")

    if start not in content:
        return

    import re as _re
    pattern = _re.escape(start) + r".*?" + _re.escape(end)
    content = _re.sub(pattern, "", content, flags=_re.DOTALL)
    # Clean up extra blank lines
    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")

    _CONFIG_LOCAL_PATH.write_text(content, encoding="utf-8")
