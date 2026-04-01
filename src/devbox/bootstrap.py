# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Bootstrap devbox user environments — nvm, pyenv, brew extras, npm/pip globals."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from devbox.exceptions import BootstrapError
from devbox.presets import Preset

logger = logging.getLogger(__name__)

_NVM_INSTALL_URL = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh"
_PYENV_INSTALLER_URL = "https://pyenv.run"

_TOOL_TIMEOUT = 300  # seconds — generous for node/python builds
_BREW_TIMEOUT = 120

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
    if not shutil.which("loadout"):
        raise BootstrapError("loadout CLI not found — install it or remove loadout_orgs from preset")

    orgs_args = " ".join(f"--orgs={shlex.quote(org)}" for org in preset.loadout_orgs)
    user_arg = f"--user={shlex.quote(preset.github_account)}"

    ssh_base = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-i", str(Path.home() / ".ssh" / preset.ssh_key),
        f"{username}@localhost",
    ]
    gh_account = preset.github_account

    # Pre-clone dotfiles repos via SSH so loadout skips the HTTPS clone
    # (private repos require auth that HTTPS won't have).
    for repo in ["dotfiles", "dotfiles-private"]:
        _run_checked(
            [*ssh_base,
             f"test -d ~/.{repo} || git clone git@github.com:{gh_account}/{repo}.git ~/.{repo}"],
            error_prefix=f"clone {repo}",
            timeout=120,
        )

    _run_checked(
        [*ssh_base, f"/opt/homebrew/bin/loadout init {user_arg} {orgs_args}"],
        error_prefix="loadout init",
        timeout=600,
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


def install_brew_extras(packages: list[str]) -> None:
    """Install extra Homebrew packages (as the current/parent user, NOT sudo).

    Raises :exc:`BootstrapError` on failure.
    """
    if not packages:
        return

    _run_checked(
        ["brew", "install", *packages],
        error_prefix="brew install",
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
        ("nvm/node", lambda: install_nvm(home_dir, preset.node_version, username)),
        ("pyenv/python", lambda: install_pyenv(home_dir, preset.python_version, username)),
        ("brew extras", lambda: install_brew_extras(preset.brew_extras)),
        ("npm globals", lambda: install_npm_globals(home_dir, preset.npm_globals, username)),
        ("pip globals", lambda: install_pip_globals(home_dir, preset.pip_globals, username)),
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
