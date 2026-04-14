# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Core devbox operations — importable by AIDA plugin."""

from __future__ import annotations

import contextlib
import getpass
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from devbox import iterm2, macos, onepassword, ssh, sshd, sudoers
from devbox.auth import inject_auth
from devbox.bootstrap import bootstrap_user
from devbox.exceptions import DevboxError
from devbox.health import format_last_seen, get_health, read_heartbeat
from devbox.naming import DX_PREFIX, validate_name
from devbox.presets import load_preset
from devbox.registry import (
    DevboxStatus,
    RegistryEntry,
    add_entry,
    find_entry,
    load_registry,
    remove_entry,
    update_entry,
)
from devbox.utils import shell_escape
from devbox.zshrc import write_zshrc

logger = logging.getLogger(__name__)


def write_env_file(
    home_dir: Path, resolved_env: dict[str, str], target_user: str | None = None
) -> None:
    """Write resolved env vars to .devbox-env with mode 0600.

    If *target_user* is provided, chowns the file to that user so the
    devbox account can read it when .zshrc sources it.
    """
    env_path = home_dir / ".devbox-env"
    lines = [f"export {key}={shell_escape(value)}" for key, value in resolved_env.items()]
    fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    if target_user is not None:
        ssh.chown_path(env_path, target_user)


class _CompensationStack:
    """Track undo operations for rollback on failure."""

    def __init__(self) -> None:
        self._actions: list[tuple[str, Callable[[], object]]] = []

    def push(self, description: str, undo_fn: Callable[[], object]) -> None:
        """Register an undo operation."""
        self._actions.append((description, undo_fn))

    def rollback(self) -> list[str]:
        """Execute all undo operations in reverse order.

        Returns list of any errors encountered during rollback.
        Each undo is idempotent; failures are logged but don't block remaining undos.
        """
        errors: list[str] = []
        for description, undo_fn in reversed(self._actions):
            try:
                undo_fn()
                logger.info("Rollback: %s — OK", description)
            except Exception as exc:
                msg = f"Rollback failed: {description} — {exc}"
                logger.warning(msg)
                errors.append(msg)
        self._actions.clear()
        return errors


def preflight_devbox(
    name: str,
    preset: str,
    registry_path: Path | None = None,
    presets_dir: Path | None = None,
) -> None:
    """Run preflight checks and warm up sudo before create.

    Called outside the spinner so interactive prompts (sudo password) are visible.
    Raises :exc:`DevboxError` on failure.
    """
    validate_name(name)
    preset_obj = load_preset(preset, presets_dir)

    existing = find_entry(name, registry_path)
    if existing is not None:
        raise DevboxError(f"Devbox {name!r} already exists (status: {existing.status})")

    if not sshd.is_remote_login_enabled():
        raise DevboxError(
            "Remote Login (sshd) is not enabled. "
            "Enable it in System Settings → General → Sharing → Remote Login"
        )

    # Warm up 1Password session before the spinner starts, so the
    # password/biometric prompt is visible to the user.
    has_op_refs = any(v.startswith("op://") for v in (preset_obj.env_vars or {}).values())
    if has_op_refs:
        with contextlib.suppress(FileNotFoundError, subprocess.TimeoutExpired):
            subprocess.run(
                ["op", "whoami"],  # noqa: S607
                capture_output=True,
                timeout=30,
            )

    result = subprocess.run(["sudo", "-v"], timeout=60)  # noqa: S607
    if result.returncode != 0:
        raise DevboxError("sudo authentication failed")


def create_devbox(
    name: str,
    preset: str,
    registry_path: Path | None = None,
    presets_dir: Path | None = None,
    dry_run: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create a new devbox from the given preset.

    Orchestrates: validation → macOS user → SSH keys →
    env file → sshd access → iTerm2 profile → registry entry.

    On failure at any step, the compensation stack rolls back all
    completed steps in reverse order.

    When *dry_run* is True, validates inputs and reports the actions
    that would be taken without executing any side effects.

    Returns the registry entry as a dict.
    """
    validate_name(name)
    preset_obj = load_preset(preset, presets_dir)

    if dry_run:
        username = f"{DX_PREFIX}{name}"
        actions: list[str] = [
            f"Would create registry entry for {name!r}",
            f"Would create macOS user {username}",
            f"Would copy SSH key {preset_obj.ssh_key!r} to /Users/{username}/.ssh/",
            "Would populate authorized_keys from parent GitHub account",
            f"Would resolve {len(preset_obj.env_vars)} environment variables",
            "Would install per-devbox Homebrew and bootstrap tools (nvm, pyenv, brew extras)",
            "Would write .zshrc with heartbeat hook",
            f"Would ensure SSH access for {username}",
            f"Would create iTerm2 profile devbox::{name}",
        ]
        for action in actions:
            logger.info(action)
        return {
            "name": name,
            "preset": preset,
            "status": "dry-run",
            "actions": actions,
        }

    def step(msg: str) -> None:
        if on_step is not None:
            on_step(msg)
        logger.info(msg)

    compensation = _CompensationStack()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    step("Creating registry entry")
    entry = RegistryEntry(name=name, preset=preset, created=today)
    add_entry(entry, registry_path)
    compensation.push("remove registry entry", partial(_safe_remove_entry, name, registry_path))

    try:
        step("Creating macOS user")
        username = macos.create_user(name)
        compensation.push(f"delete macOS user {username}", partial(macos.delete_user, name))

        step("Configuring sudoers for devbox user")
        sudoers.add_user(username)
        compensation.push(
            f"remove sudoers rule for {username}",
            partial(sudoers.remove_user, username),
        )

        home_dir = Path(f"/Users/{username}")

        # Temporarily take ownership of the home dir itself (not recursive —
        # the dir is freshly created and nearly empty) so Python file ops
        # can create subdirectories. The finally block restores ownership
        # of only the specific paths we write, leaving ~/Developer untouched.
        calling_user = getpass.getuser()
        _sudo_chown(home_dir, calling_user, recursive=False)
        try:
            step("Copying SSH keypair")
            ssh.copy_keypair(home_dir, preset_obj.ssh_key)

            step("Populating authorized_keys from GitHub")
            ssh.populate_authorized_keys(home_dir, target_user=username)

            step("Resolving environment variables")
            if preset_obj.env_vars:
                resolved = onepassword.resolve_env_vars(preset_obj.env_vars)
                write_env_file(home_dir, resolved, target_user=username)

            step("Injecting auth credentials")
            try:
                inject_auth(home_dir, preset_obj, username)
            except DevboxError as exc:
                logger.warning("Auth injection failed (non-fatal): %s", exc)

            step("Writing .zshrc")
            try:
                write_zshrc(home_dir, name, username)
            except DevboxError as exc:
                logger.warning("zshrc write failed (non-fatal): %s", exc)
        finally:
            # Restore ownership on the home dir and only the paths we wrote.
            # Never chown -R the home dir — ~/Developer may contain large repos.
            _sudo_chown(home_dir, username, recursive=False)
            for subpath in [".ssh", ".aws", ".devbox-env", ".zshenv", ".zshrc.local", ".homebrew"]:
                p = home_dir / subpath
                if p.exists():
                    _sudo_chown(p, username)

        step("Bootstrapping dev tools (this may take several minutes)")
        warnings = bootstrap_user(home_dir, preset_obj, username)
        for w in warnings:
            logger.warning("Bootstrap: %s", w)

        step("Configuring SSH access")
        sshd.ensure_ssh_access(username)
        compensation.push(
            f"remove {username} from SSH group",
            partial(sshd.remove_user_from_ssh_group, username),
        )

        step("Creating iTerm2 profile")
        iterm2.create_profile(name, preset_obj)
        compensation.push("remove iTerm2 profile", partial(iterm2.remove_profile, name))

        step("Adding SSH config entry")
        ssh.add_ssh_config_entry(name, preset_obj.ssh_key)
        compensation.push("remove SSH config entry", partial(ssh.remove_ssh_config_entry, name))

        # Run loadout via SSH now that the devbox is accessible
        if preset_obj.loadout_orgs:
            step("Running loadout (this may take several minutes)")
            try:
                from devbox.bootstrap import run_loadout

                run_loadout(home_dir, preset_obj, username)
            except Exception as exc:
                logger.warning("Loadout failed (non-fatal): %s", exc)

        # Create ~/Developer and clone repos. Always runs so ~/Developer
        # exists even when no repos are configured.
        # Pause between phases to spread out GitHub SSH connections.
        time.sleep(5)
        step("Setting up Developer directory")
        try:
            from devbox.bootstrap import clone_repos

            clone_repos(home_dir, preset_obj, username)
        except Exception as exc:
            logger.warning("Repo setup failed (non-fatal): %s", exc)

        step("Finalizing")
        update_entry(name, registry_path, status=DevboxStatus.READY)

    except Exception:
        compensation.rollback()
        raise

    updated = find_entry(name, registry_path)
    return updated.model_dump() if updated else entry.model_dump()


def list_devboxes(
    registry_path: Path | None = None, *, check_ssh: bool = False
) -> list[dict[str, Any]]:
    """Return all registered devboxes with health status.

    When *check_ssh* is ``True``, each ready devbox is also probed via
    SSH and marked ``"unreachable"`` if the probe fails.

    Reads heartbeat files and computes health for each entry.
    Does not modify the registry — use :func:`sync_heartbeats` to persist
    heartbeat data if desired.
    """
    registry = load_registry(registry_path)
    results: list[dict[str, Any]] = []

    for entry in registry.devboxes:
        heartbeat = read_heartbeat(entry.name)

        last_seen_dt = heartbeat or (
            datetime.fromisoformat(entry.last_seen) if entry.last_seen else None
        )
        should_check = check_ssh and entry.status == DevboxStatus.READY
        health = get_health(entry.name, last_seen_dt, check_ssh_flag=should_check)

        results.append(
            {
                "name": entry.name,
                "preset": entry.preset,
                "created": entry.created,
                "last_seen": format_last_seen(last_seen_dt),
                "status": health if entry.status == DevboxStatus.READY else entry.status.value,
            }
        )

    return results


def sync_heartbeats(registry_path: Path | None = None) -> None:
    """Update registry last_seen fields from heartbeat files.

    Separated from :func:`list_devboxes` so that listing is read-only.
    """
    registry = load_registry(registry_path)
    for entry in registry.devboxes:
        heartbeat = read_heartbeat(entry.name)
        if heartbeat is not None:
            with contextlib.suppress(DevboxError):
                update_entry(entry.name, registry_path, last_seen=heartbeat.isoformat())


def nuke_devbox(
    name: str,
    registry_path: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Destroy a devbox and clean up all resources.

    Steps: mark nuking → remove SSH group → delete macOS user →
    remove iTerm2 profile → remove registry entry.

    Returns a list of non-fatal cleanup errors (empty on full success).
    If critical cleanup steps fail, the registry entry is kept in 'nuking'
    state so the user can retry.

    When *dry_run* is True, validates inputs and reports the cleanup
    steps that would be taken without executing any side effects.
    """
    validate_name(name)
    entry = find_entry(name, registry_path)
    if entry is None:
        raise DevboxError(f"Devbox {name!r} not found in registry")

    if dry_run:
        username = f"{DX_PREFIX}{name}"
        actions: list[str] = [
            f"Would mark devbox {name!r} as nuking",
            f"Would remove {username} from SSH access group",
            f"Would delete macOS user {username} and home directory",
            f"Would remove iTerm2 profile devbox::{name}",
            f"Would remove registry entry for {name!r}",
        ]
        for action in actions:
            logger.info(action)
        return actions

    # Mark as nuking
    update_entry(name, registry_path, status=DevboxStatus.NUKING)

    errors: list[str] = []
    critical_failure = False

    # Remove sudoers rule for this devbox user
    username = f"{DX_PREFIX}{name}"
    try:
        sudoers.remove_user(username)
    except Exception as exc:
        errors.append(f"Sudoers removal: {exc}")
        logger.warning("Failed to remove sudoers rule: %s", exc)

    # Remove from SSH access group
    try:
        sshd.remove_user_from_ssh_group(username)
    except Exception as exc:
        errors.append(f"SSH group removal: {exc}")
        logger.warning("Failed to remove from SSH group: %s", exc)

    # Delete macOS user + home directory
    try:
        macos.delete_user(name)
    except Exception as exc:
        errors.append(f"macOS user deletion: {exc}")
        logger.warning("Failed to delete macOS user: %s", exc)
        critical_failure = True

    # Remove iTerm2 profile
    try:
        iterm2.remove_profile(name)
    except Exception as exc:
        errors.append(f"iTerm2 profile removal: {exc}")
        logger.warning("Failed to remove iTerm2 profile: %s", exc)

    # Remove SSH config entry
    try:
        ssh.remove_ssh_config_entry(name)
    except Exception as exc:
        errors.append(f"SSH config removal: {exc}")
        logger.warning("Failed to remove SSH config entry: %s", exc)

    # Only remove registry entry if no critical failures occurred.
    # If the macOS user couldn't be deleted, keep the entry in 'nuking'
    # state so the user can retry or manually clean up.
    if critical_failure:
        logger.warning(
            "Devbox %r nuke had critical failures — registry entry kept in 'nuking' state. "
            "Resolve the issues and retry `devbox nuke %s`.",
            name,
            name,
        )
    else:
        remove_entry(name, registry_path)

    return errors


def rebuild_devbox(
    name: str,
    registry_path: Path | None = None,
    presets_dir: Path | None = None,
) -> dict[str, Any]:
    """Tear down and recreate a devbox with the same preset.

    Returns the new registry entry as a dict.
    """
    validate_name(name)
    entry = find_entry(name, registry_path)
    if entry is None:
        raise DevboxError(f"Devbox {name!r} not found in registry")

    preset_name = entry.preset
    nuke_devbox(name, registry_path)

    # If nuke had critical failures (entry still in registry), abort rebuild
    remaining = find_entry(name, registry_path)
    if remaining is not None:
        raise DevboxError(
            f"Cannot rebuild {name!r}: nuke failed to fully clean up "
            f"(status: {remaining.status}). Resolve the issues and retry."
        )

    return create_devbox(name, preset_name, registry_path, presets_dir)


def refresh_devbox(
    name: str,
    *,
    with_globals: bool = False,
    registry_path: Path | None = None,
    presets_dir: Path | None = None,
) -> dict[str, Any]:
    """Push current dotfiles/config to an existing devbox without destroying state.

    Runs ``loadout update --skip-brew --skip-globals`` over SSH, then
    installs the preset's ``brew_extras`` as the devbox user. The loadout
    Brewfile is never re-run here — it's a 30+ minute compile at the
    non-standard ``~/.homebrew`` prefix, so if it needs to change, rebuild
    the devbox instead. ``with_globals`` additionally reinstalls the
    preset's ``npm_globals`` and ``pip_globals``.

    Refuses to refresh devboxes that are not in ``READY`` state (e.g.
    ``CREATING`` / ``NUKING``) to avoid racing in-flight bootstrap.

    Returns the registry entry as a dict.
    """
    validate_name(name)
    entry = find_entry(name, registry_path)
    if entry is None:
        raise DevboxError(f"Devbox {name!r} not found in registry")

    # Status check is best-effort: there's no registry lock, so a concurrent
    # nuke/rebuild could race. SSH will fail cleanly in that case.
    if entry.status != DevboxStatus.READY:
        raise DevboxError(
            f"Devbox {name!r} is not ready to refresh (status: {entry.status.value}). "
            f"Wait for it to finish, or use 'devbox list' to check."
        )

    preset_obj = load_preset(entry.preset, presets_dir)
    username = f"{DX_PREFIX}{name}"
    home_dir = Path(f"/Users/{username}")

    from devbox.bootstrap import (
        build_ssh_base,
        install_brew_extras,
        install_npm_globals,
        install_pip_globals,
        refresh_dotfiles,
    )

    if not preset_obj.loadout_orgs and (preset_obj.brew_extras or with_globals):
        logger.warning(
            "Preset %r has no loadout_orgs; loadout update is a no-op, "
            "but preset brew_extras/globals will still be installed",
            entry.preset,
        )

    refresh_dotfiles(home_dir, preset_obj, username)

    # Run install steps via SSH as the devbox user — avoids host sudo so
    # refresh works in non-interactive shells.
    ssh_base = build_ssh_base(preset_obj, username)

    if preset_obj.brew_extras:
        install_brew_extras(home_dir, preset_obj.brew_extras, username, ssh_base=ssh_base)

    if with_globals:
        if preset_obj.npm_globals:
            install_npm_globals(home_dir, preset_obj.npm_globals, username, ssh_base=ssh_base)
        if preset_obj.pip_globals:
            install_pip_globals(home_dir, preset_obj.pip_globals, username, ssh_base=ssh_base)

    return entry.model_dump()


_SAFE_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sudo_chown(path: Path, user: str, *, recursive: bool = True) -> None:
    """Chown *path* to *user*:staff via sudo.

    Pass ``recursive=False`` to chown only the path itself, not its contents.
    """
    if not _SAFE_USERNAME_RE.match(user) or len(user) > 64:
        raise DevboxError(f"Invalid username for chown: {user!r}")
    cmd = ["sudo", "chown"]
    if recursive:
        cmd.append("-R")
    cmd.extend([f"{user}:staff", str(path)])
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise DevboxError(f"Failed to chown {path} to {user}: {result.stderr.strip()}")


def _safe_remove_entry(name: str, registry_path: Path | None) -> None:
    """Remove registry entry, ignoring errors (for compensation)."""
    with contextlib.suppress(DevboxError):
        remove_entry(name, registry_path)
