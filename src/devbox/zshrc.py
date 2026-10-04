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

ZSHENV_CONTENT = (
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
    "ssh-add -q $(awk '/IdentityFile/{print $2}' ~/.ssh/config"
    ' | sed "s|^~|$HOME|") 2>/dev/null\n'
)

# .zprofile runs after /etc/zprofile (which calls path_helper) for login
# shells. path_helper reads /etc/paths.d/homebrew from the parent user's
# Homebrew install and prepends /opt/homebrew/bin ahead of our PATH,
# shadowing the per-devbox ~/.homebrew binaries. Re-prepend here to put
# ~/.homebrew first again so the devbox's own tools win.
ZPROFILE_CONTENT = (
    "# devbox: re-prepend ~/.homebrew/bin after macOS path_helper runs\n"
    "# (parent /opt/homebrew would otherwise shadow our per-devbox brew).\n"
    'if [ -x "$HOME/.homebrew/bin/brew" ]; then\n'
    '    eval "$($HOME/.homebrew/bin/brew shellenv)"\n'
    "fi\n"
)

LOGIN_NOTICE = ""

# `dev <folder> [claude args...]` — cd into ~/Developer/<folder> and start
# Claude Code with permission prompts skipped. Devbox-only: each devbox is an
# isolated macOS user, which is what makes skipping permissions acceptable.
DEV_FUNCTION = (
    "# devbox dev command\n"
    "dev() {\n"
    '    if [[ -z "$1" ]]; then\n'
    '        print -u2 "usage: dev <folder> [claude options...]"\n'
    '        print -u2 "folders in ~/Developer:"\n'
    "        ls -1 ~/Developer >&2 2>/dev/null\n"
    "        return 1\n"
    "    fi\n"
    '    local dir="$HOME/Developer/$1"\n'
    "    shift\n"
    '    if [[ ! -d "$dir" ]]; then\n'
    '        print -u2 "dev: no such folder: $dir"\n'
    "        return 1\n"
    "    fi\n"
    '    cd "$dir" && claude "$@" --dangerously-skip-permissions\n'
    "}\n"
    "_dev() {\n"
    "    if (( CURRENT == 2 )); then\n"
    '        _path_files -/ -W "$HOME/Developer"\n'
    "    else\n"
    "        _files\n"
    "    fi\n"
    "}\n"
    "(( $+functions[compdef] )) && compdef _dev dev"
)


LOADOUT_NOTICE = LOGIN_NOTICE  # backward-compat alias


def generate_zshrc_local(name: str) -> str:
    """Return .zshrc.local content for a devbox user.

    Includes the environment source line, heartbeat hook, the ``dev`` command, and dotfiles
    divergence notice.  Written to .zshrc.local so it survives loadout builds.
    """
    return (
        f"# .zshrc.local for devbox {name}\n\n"
        f"{ENV_SOURCE_LINE}\n\n"
        f"{HEARTBEAT_HOOK}\n\n"
        f"{DEV_FUNCTION}\n\n"
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
    zshenv_path.write_text(ZSHENV_CONTENT, encoding="utf-8")
    os.chmod(zshenv_path, 0o644)
    chown_path(zshenv_path, username)

    zprofile_path = home_dir / ".zprofile"
    zprofile_path.write_text(ZPROFILE_CONTENT, encoding="utf-8")
    os.chmod(zprofile_path, 0o644)
    chown_path(zprofile_path, username)

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
