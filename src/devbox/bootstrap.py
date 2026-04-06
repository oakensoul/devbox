# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Bootstrap devbox user environments — homebrew, nvm, pyenv, brew extras, npm/pip globals."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from devbox.exceptions import BootstrapError
from devbox.presets import Preset

logger = logging.getLogger(__name__)

_HOMEBREW_REPO = "https://github.com/Homebrew/brew"
_NVM_INSTALL_URL = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh"
_PYENV_INSTALLER_URL = "https://pyenv.run"
_CLAUDE_CODE_INSTALL_URL = "https://claude.ai/install.sh"

_TOOL_TIMEOUT = 300  # seconds — generous for node/python builds
_BREW_TIMEOUT = 300  # compiles from source on non-standard prefix

_DX_USERNAME_RE = re.compile(r"^dx-[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_username(username: str) -> None:
    """Raise :exc:`BootstrapError` if *username* doesn't match the devbox naming convention."""
    if not _DX_USERNAME_RE.match(username):
        raise BootstrapError(f"Invalid devbox username: {username!r}")


def run_loadout(home_dir: Path, preset: Preset, username: str) -> None:
    """Run loadout init as the devbox user to set up dotfiles and config.

    Skips if no loadout_orgs are configured in the preset.
    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    if not preset.loadout_orgs:
        return

    import shutil

    loadout_bin = shutil.which("loadout")
    if not loadout_bin:
        raise BootstrapError(
            "loadout CLI not found — install it or remove loadout_orgs from preset"
        )

    ssh_base = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        str(Path.home() / ".ssh" / preset.ssh_key),
        f"{username}@localhost",
    ]

    # Clone dotfiles repos via SSH (private repos need SSH auth).
    acct = preset.github_account
    for repo in ["dotfiles", "dotfiles-private"]:
        clone_cmd = f"test -d ~/.{repo} || git clone git@github.com:{acct}/{repo}.git ~/.{repo}"
        _run_checked(
            [*ssh_base, clone_cmd],
            error_prefix=f"clone {repo}",
            timeout=120,
        )

    # Save loadout config so `build` knows the user and orgs.
    orgs_toml = ", ".join(f'"{org}"' for org in preset.loadout_orgs)
    config_content = f'user = "{preset.github_account}"\norgs = [{orgs_toml}]\n'
    _run_checked(
        [
            *ssh_base,
            "mkdir -p ~/.dotfiles && cat > ~/.dotfiles/.loadout.toml "
            f"<< 'LOADOUT_EOF'\n{config_content}LOADOUT_EOF",
        ],
        error_prefix="write loadout config",
        timeout=10,
    )

    # Allow the devbox user to run git in directories owned by other users
    # (e.g. /opt/homebrew and its taps are owned by the parent account).
    # Set system-wide so loadout rebuilding ~/.gitconfig can't wipe it.
    _run_checked(
        ["sudo", "git", "config", "--system", "--replace-all", "safe.directory", "*"],
        error_prefix="git safe.directory",
        timeout=10,
    )

    # Loadout's .zshrc (from dotfiles) may contain a bare
    #   eval "$(/opt/homebrew/bin/brew shellenv)"
    # inside a `if [[ -d /opt/homebrew ]]; then` block.  That overrides our
    # per-devbox HOMEBREW_PREFIX when loadout spawns sub-shells.  Patch it
    # BEFORE running loadout so that sub-shells don't clobber the env, then
    # patch again AFTER in case loadout re-pulled the dotfiles.
    q_home = shlex.quote(str(home_dir))
    sed_pattern = (
        "s|^if \\\\[\\\\[ -d /opt/homebrew \\\\]\\\\];|"
        'if [[ -z "$HOMEBREW_PREFIX" ]] \\&\\& '
        "[[ -d /opt/homebrew ]];|"
    )
    sed_cmd = f"[ -f ~/.zshrc ] && sed -i '' '{sed_pattern}' ~/.zshrc || true"
    _run_checked(
        [*ssh_base, sed_cmd],
        error_prefix="patch .zshrc brew guard (pre-loadout)",
        timeout=10,
    )

    # Run loadout update to pull dotfiles and apply full config
    # (build + SSH config + Claude config + brew bundle).
    # Use the host's loadout binary path — the devbox user may not have
    # loadout installed in their own Homebrew yet.
    #
    # Explicitly set HOMEBREW_PREFIX and PATH so loadout's brew steps use the
    # per-devbox Homebrew at ~/.homebrew instead of /opt/homebrew.
    _run_checked(
        [
            *ssh_base,
            f"export HOMEBREW_PREFIX={q_home}/.homebrew "
            f"HOMEBREW_CELLAR={q_home}/.homebrew/Cellar "
            f"HOMEBREW_REPOSITORY={q_home}/.homebrew "
            f"PATH={q_home}/.homebrew/bin:{q_home}/.homebrew/sbin:$PATH "
            f"&& {shlex.quote(loadout_bin)} update",
        ],
        error_prefix="loadout update",
        timeout=600,
    )

    # Re-apply the guard — loadout may have re-pulled dotfiles, resetting it.
    _run_checked(
        [*ssh_base, sed_cmd],
        error_prefix="patch .zshrc brew guard (post-loadout)",
        timeout=10,
    )


def install_nvm(home_dir: Path, node_version: str, username: str) -> None:
    """Install nvm and a Node.js version into the devbox user's home.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    nvm_dir = home_dir / ".nvm"
    q_home = shlex.quote(str(home_dir))
    q_nvm = shlex.quote(str(nvm_dir))
    q_node = shlex.quote(node_version)

    # Install nvm via its install script
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export NVM_DIR={q_nvm} "
            f"&& curl --proto =https -fsSL {shlex.quote(_NVM_INSTALL_URL)} | bash",
        ],
        error_prefix="nvm install",
        timeout=_TOOL_TIMEOUT,
    )

    # Install the requested Node.js version
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export NVM_DIR={q_nvm} "
            f"&& . {q_nvm}/nvm.sh && nvm install {q_node}",
        ],
        error_prefix=f"node {node_version} install",
        timeout=_TOOL_TIMEOUT,
    )


def install_pyenv(home_dir: Path, python_version: str, username: str) -> None:
    """Install pyenv and a Python version into the devbox user's home.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    pyenv_root = home_dir / ".pyenv"
    q_home = shlex.quote(str(home_dir))
    q_pyenv_root = shlex.quote(str(pyenv_root))
    q_python = shlex.quote(python_version)

    # Install pyenv via pyenv-installer
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export PYENV_ROOT={q_pyenv_root} "
            f"&& curl --proto =https -fsSL {shlex.quote(_PYENV_INSTALLER_URL)} | bash",
        ],
        error_prefix="pyenv install",
        timeout=_TOOL_TIMEOUT,
    )

    # Install the requested Python version
    pyenv_bin = pyenv_root / "bin" / "pyenv"
    q_pyenv_bin = shlex.quote(str(pyenv_bin))
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export PYENV_ROOT={q_pyenv_root} "
            f"&& {q_pyenv_bin} install {q_python} "
            f"&& {q_pyenv_bin} global {q_python}",
        ],
        error_prefix=f"python {python_version} install",
        timeout=_TOOL_TIMEOUT,
    )


def install_homebrew(home_dir: Path, username: str) -> None:
    """Install Homebrew to the devbox user's ``~/.homebrew`` prefix.

    Uses a shallow git clone followed by ``brew update`` to initialise a
    standalone Homebrew installation that is fully owned by the devbox user.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    brew_prefix = home_dir / ".homebrew"
    q_home = shlex.quote(str(home_dir))
    q_prefix = shlex.quote(str(brew_prefix))

    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && git clone --depth=1 {shlex.quote(_HOMEBREW_REPO)} {q_prefix}",
        ],
        error_prefix="homebrew install",
        timeout=_TOOL_TIMEOUT,
    )

    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && {q_prefix}/bin/brew update --force --quiet",
        ],
        error_prefix="homebrew update",
        timeout=_TOOL_TIMEOUT,
    )


def install_brew_extras(home_dir: Path, packages: list[str], username: str) -> None:
    """Install extra Homebrew packages into the devbox user's per-devbox Homebrew.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    if not packages:
        return

    brew_bin = home_dir / ".homebrew" / "bin" / "brew"
    q_home = shlex.quote(str(home_dir))
    q_brew = shlex.quote(str(brew_bin))
    q_packages = " ".join(shlex.quote(p) for p in packages)
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && {q_brew} install {q_packages}",
        ],
        error_prefix="brew extras install",
        timeout=_BREW_TIMEOUT,
    )


def install_npm_globals(
    home_dir: Path,
    packages: list[str],
    username: str,
) -> None:
    """Install global npm packages as the devbox user.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    if not packages:
        return

    nvm_dir = home_dir / ".nvm"
    q_home = shlex.quote(str(home_dir))
    q_nvm = shlex.quote(str(nvm_dir))
    q_packages = " ".join(shlex.quote(p) for p in packages)
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export NVM_DIR={q_nvm} "
            f"&& . {q_nvm}/nvm.sh && npm install -g {q_packages}",
        ],
        error_prefix="npm globals install",
        timeout=_TOOL_TIMEOUT,
    )


def install_pip_globals(
    home_dir: Path,
    packages: list[str],
    username: str,
) -> None:
    """Install global pip packages as the devbox user.

    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    if not packages:
        return

    pyenv_root = home_dir / ".pyenv"
    pyenv_bin = pyenv_root / "bin" / "pyenv"
    q_home = shlex.quote(str(home_dir))
    q_pyenv_root = shlex.quote(str(pyenv_root))
    q_pyenv_bin = shlex.quote(str(pyenv_bin))
    q_packages = " ".join(shlex.quote(p) for p in packages)
    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} && export PYENV_ROOT={q_pyenv_root} "
            f'&& eval "$({q_pyenv_bin} init -)" '
            f"&& pip install {q_packages}",
        ],
        error_prefix="pip globals install",
        timeout=_TOOL_TIMEOUT,
    )


def install_claude_code(home_dir: Path, username: str) -> None:
    """Install Claude Code via Anthropic's native installer.

    Installs to ``~/.local/bin/claude`` as the devbox user.
    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    q_home = shlex.quote(str(home_dir))

    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} "
            f"&& curl --proto =https -fsSL {shlex.quote(_CLAUDE_CODE_INSTALL_URL)} | bash",
        ],
        error_prefix="claude code install",
        timeout=_TOOL_TIMEOUT,
    )


def setup_gh_auth(home_dir: Path, username: str) -> None:
    """Configure the GitHub CLI to use SSH for git operations.

    Sets ``git_protocol`` to ``ssh`` so ``gh`` uses the devbox SSH key for
    git operations.  API authentication is handled automatically by the
    ``GITHUB_TOKEN`` environment variable from ``~/.devbox-env``.
    Skips silently if ``gh`` is not installed.
    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    q_home = shlex.quote(str(home_dir))
    brew_bin = home_dir / ".homebrew" / "bin"
    q_brew_bin = shlex.quote(str(brew_bin))

    _run_checked(
        [
            "sudo",
            "-u",
            username,
            "bash",
            "-c",
            f"export HOME={q_home} "
            f"&& export PATH={q_brew_bin}:$PATH "
            "&& command -v gh >/dev/null 2>&1 "
            "&& gh config set git_protocol ssh --host github.com "
            "|| true",
        ],
        error_prefix="gh config",
        timeout=30,
    )


def clone_repos(home_dir: Path, preset: Preset, username: str) -> None:
    """Create ~/Developer and clone preset repos as the devbox user.

    Skips repos that are already cloned. Skips entirely if preset.repos is empty.
    Raises :exc:`BootstrapError` on failure.
    """
    _validate_username(username)
    if not preset.repos:
        return

    ssh_base = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        str(Path.home() / ".ssh" / preset.ssh_key),
        f"{username}@localhost",
    ]

    _run_checked(
        [*ssh_base, "mkdir -p ~/Developer"],
        error_prefix="create Developer dir",
        timeout=10,
    )

    failed: list[str] = []
    for i, repo in enumerate(preset.repos):
        if i > 0:
            time.sleep(2)  # avoid GitHub SSH rate limiting on bulk clones
        _, repo_name = repo.split("/", 1)
        dest = f"~/Developer/{shlex.quote(repo_name)}"
        try:
            _run_checked(
                [
                    *ssh_base,
                    f"test -d {dest} || git clone git@github.com:{shlex.quote(repo)}.git {dest}",
                ],
                error_prefix=f"clone {repo}",
                timeout=120,
            )
        except BootstrapError:
            failed.append(repo)

    # Retry failed clones up to 2 times, with a longer delay before each attempt.
    for attempt in range(1, 3):
        if not failed:
            break
        logger.warning("Retrying %d failed clone(s) (attempt %d/2)", len(failed), attempt)
        time.sleep(10 * attempt)
        still_failed: list[str] = []
        for repo in failed:
            _, repo_name = repo.split("/", 1)
            dest = f"~/Developer/{shlex.quote(repo_name)}"
            try:
                _run_checked(
                    [
                        *ssh_base,
                        f"test -d {dest} || git clone "
                        f"git@github.com:{shlex.quote(repo)}.git {dest}",
                    ],
                    error_prefix=f"clone {repo}",
                    timeout=120,
                )
            except BootstrapError:
                still_failed.append(repo)
            else:
                time.sleep(2)
        failed = still_failed

    if failed:
        raise BootstrapError(f"Failed to clone after 2 retries: {', '.join(failed)}")


def bootstrap_user(
    home_dir: Path,
    preset: Preset,
    username: str,
) -> list[str]:
    """Run all bootstrap steps for a devbox user.

    Each step is try/except — failures produce warnings but do not block
    subsequent steps.  Returns a list of warning strings (empty on full success).
    """
    _validate_username(username)
    warnings: list[str] = []

    steps: list[tuple[str, Callable[[], None]]] = [
        ("homebrew", lambda: install_homebrew(home_dir, username)),
        ("nvm/node", lambda: install_nvm(home_dir, preset.node_version, username)),
        ("pyenv/python", lambda: install_pyenv(home_dir, preset.python_version, username)),
        ("brew extras", lambda: install_brew_extras(home_dir, preset.brew_extras, username)),
        ("npm globals", lambda: install_npm_globals(home_dir, preset.npm_globals, username)),
        ("pip globals", lambda: install_pip_globals(home_dir, preset.pip_globals, username)),
        ("claude code", lambda: install_claude_code(home_dir, username)),
        ("gh auth", lambda: setup_gh_auth(home_dir, username)),
    ]

    for label, step_fn in steps:
        try:
            step_fn()
        except BootstrapError as exc:
            msg = f"{label}: {exc}"
            logger.warning("Bootstrap step failed — %s", msg)
            warnings.append(msg)

    return warnings


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _run_checked(
    cmd: list[str],
    *,
    error_prefix: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and raise :exc:`BootstrapError` on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BootstrapError(f"{error_prefix}: command not found — {exc}") from None
    except subprocess.TimeoutExpired:
        raise BootstrapError(f"{error_prefix}: timed out after {timeout}s") from None

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-500:]
        raise BootstrapError(
            f"{error_prefix}: exit code {result.returncode}"
            + (f" — {stderr_tail}" if stderr_tail else "")
        )

    return result
