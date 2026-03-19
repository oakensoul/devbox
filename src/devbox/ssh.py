"""SSH key generation and authorized_keys management."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import requests

from devbox.exceptions import SSHError

_SSH_KEY_PREFIX_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519)\s")
_CONFIG_PATH = Path.home() / ".devbox" / "config.json"


def generate_keypair(home_dir: Path) -> str:
    """Generate an ed25519 keypair for a devbox user.

    Creates ``<home_dir>/.ssh/id_ed25519`` and ``id_ed25519.pub`` with correct
    permissions. Returns the public key string.
    """
    ssh_dir = home_dir / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    key_path = ssh_dir / "id_ed25519"
    if key_path.exists():
        raise SSHError(f"SSH key already exists: {key_path}")

    try:
        subprocess.run(
            [
                "ssh-keygen", "-t", "ed25519",
                "-f", str(key_path),
                "-N", "",  # no passphrase
                "-C", f"devbox-{home_dir.name}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise SSHError("ssh-keygen is not available") from None
    except subprocess.TimeoutExpired:
        raise SSHError("ssh-keygen timed out") from None

    if not key_path.exists():
        raise SSHError("ssh-keygen did not produce a key file")

    os.chmod(key_path, 0o600)
    pub_path = key_path.with_suffix(".pub")
    if pub_path.exists():
        os.chmod(pub_path, 0o644)

    return pub_path.read_text(encoding="utf-8").strip()


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
        raise SSHError(
            "parent_github_user not set in config. "
            f"Add it to {_CONFIG_PATH}"
        )
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


def populate_authorized_keys(
    home_dir: Path,
    github_user: str | None = None,
    timeout: int = 10,
) -> int:
    """Populate authorized_keys from the parent user's GitHub public keys.

    Fetches keys from ``https://github.com/<user>.keys`` and writes them to
    ``<home_dir>/.ssh/authorized_keys``.

    Returns the number of keys written.
    """
    if github_user is None:
        github_user = _get_parent_github_user()

    url = f"https://github.com/{github_user}.keys"
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SSHError(f"Failed to fetch SSH keys from GitHub: {exc}") from exc

    keys = _validate_ssh_keys(response.text)
    if not keys:
        raise SSHError(
            f"No valid SSH public keys found for GitHub user {github_user!r}"
        )

    ssh_dir = home_dir / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(ssh_dir, 0o700)

    auth_keys_path = ssh_dir / "authorized_keys"
    auth_keys_path.write_text("\n".join(keys) + "\n", encoding="utf-8")
    os.chmod(auth_keys_path, 0o600)

    return len(keys)
