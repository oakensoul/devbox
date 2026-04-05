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

LOGIN_NOTICE = ""

LOADOUT_NOTICE = LOGIN_NOTICE  # backward-compat alias


def generate_zshrc_local(name: str) -> str:  # noqa: D103 — primary name
    """Return .zshrc.local content for a devbox user.

    Includes the environment source line, heartbeat hook, and dotfiles
    divergence notice.  Written to .zshrc.local so it survives loadout builds.
    """
    return (
        f"# .zshrc.local for devbox {name}\n\n"
        f"{ENV_SOURCE_LINE}\n\n"
        f"{HEARTBEAT_HOOK}\n\n"
        f"{LOGIN_NOTICE}\n"
    )


generate_zshrc = generate_zshrc_local  # alias used by tests


def write_zshrc(home_dir: Path, name: str, username: str) -> None:
    """Write .zshrc.local and .zshenv to *home_dir*.

    .zshenv sets up PATH and environment variables for the per-devbox
    Homebrew installation at ``~/.homebrew``.
    .zshrc.local adds devbox-specific hooks that survive loadout builds.
    """
    zshenv_path = home_dir / ".zshenv"
    zshenv_path.write_text(
        "# devbox: per-devbox Homebrew environment\n"
        'export HOMEBREW_PREFIX="$HOME/.homebrew"\n'
        'export HOMEBREW_CELLAR="$HOME/.homebrew/Cellar"\n'
        'export HOMEBREW_REPOSITORY="$HOME/.homebrew"\n'
        'export PATH="$HOME/.homebrew/bin:$HOME/.homebrew/sbin:$PATH"\n'
        'export MANPATH="$HOME/.homebrew/share/man${MANPATH+:$MANPATH}:"\n'
        'export INFOPATH="$HOME/.homebrew/share/info:${INFOPATH:-}"\n'
        'fpath=("$HOME/.homebrew/share/zsh/site-functions" $^fpath(-/N))\n'
        "\n"
        "# devbox: SSH agent — ensure the key is loaded for git/ssh operations\n"
        'if [[ -z "$SSH_AUTH_SOCK" ]]; then\n'
        '    eval "$(ssh-agent -s)" >/dev/null 2>&1\n'
        "fi\n"
        'ssh-add -q $(awk \'/IdentityFile/{print $2}\' ~/.ssh/config) 2>/dev/null\n',
        encoding="utf-8",
    )
    os.chmod(zshenv_path, 0o644)
    chown_path(zshenv_path, username)

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
