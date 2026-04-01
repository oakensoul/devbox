# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Zshrc generation and heartbeat hook management for devbox users."""

from __future__ import annotations

import os
from pathlib import Path

from devbox.ssh import chown_path

HEARTBEAT_HOOK = (
    "# devbox heartbeat\n"
    'echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > ~/.devbox_heartbeat\n'
    "chmod 644 ~/.devbox_heartbeat"
)

ENV_SOURCE_LINE = "# devbox environment\n[ -f ~/.devbox-env ] && source ~/.devbox-env"


def generate_zshrc_local(name: str) -> str:
    """Return .zshrc.local content for a devbox user.

    Includes the environment source line and the heartbeat hook.
    Written to .zshrc.local so it survives loadout builds.
    """
    return f"# .zshrc.local for devbox {name}\n\n{ENV_SOURCE_LINE}\n\n{HEARTBEAT_HOOK}\n"


def write_zshrc(home_dir: Path, name: str, username: str) -> None:
    """Write .zshrc.local to *home_dir* with correct permissions and ownership.

    The file is written with mode 0644 and chowned to *username* via
    :func:`devbox.ssh.chown_path`.
    """
    zshrc_path = home_dir / ".zshrc.local"
    zshrc_path.write_text(generate_zshrc_local(name), encoding="utf-8")
    os.chmod(zshrc_path, 0o644)
    chown_path(zshrc_path, username)


def is_hook_installed(home_dir: Path) -> bool:
    """Check whether the heartbeat hook is already present in .zshrc.local."""
    zshrc_path = home_dir / ".zshrc.local"
    if not zshrc_path.exists():
        return False
    content = zshrc_path.read_text(encoding="utf-8")
    return "# devbox heartbeat" in content
