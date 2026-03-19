"""Core devbox operations — importable by AIDA plugin."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from devbox import github, iterm2, macos, onepassword, ssh, sshd
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


def create_devbox(
    name: str,
    preset: str,
    registry_path: Path | None = None,
    presets_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a new devbox from the given preset.

    Orchestrates: validation → macOS user → SSH keys → GitHub key →
    env file → sshd access → iTerm2 profile → registry entry.

    On failure at any step, the compensation stack rolls back all
    completed steps in reverse order.

    When *dry_run* is True, validates inputs and reports the actions
    that would be taken without executing any side effects.

    Returns the registry entry as a dict.
    """
    validate_name(name)
    preset_obj = load_preset(preset, presets_dir)

    # Check for existing devbox
    existing = find_entry(name, registry_path)
    if existing is not None:
        raise DevboxError(f"Devbox {name!r} already exists (status: {existing.status})")

    if dry_run:
        username = f"{DX_PREFIX}{name}"
        actions: list[str] = [
            f"Would create registry entry for {name!r}",
            f"Would create macOS user {username}",
            f"Would generate SSH keypair at /Users/{username}/.ssh/",
            "Would populate authorized_keys from parent GitHub account",
            f"Would register SSH key with GitHub account {preset_obj.github_account}",
            f"Would resolve {len(preset_obj.env_vars)} environment variables",
            "Would inject Claude Code auth credentials",
            "Would bootstrap development tools (nvm, pyenv, brew extras)",
            "Would write .zshrc with heartbeat hook",
            f"Would ensure SSH access for {username}",
            f"Would create iTerm2 profile devbox::{name}",
            "Would disable password authentication",
        ]
        for action in actions:
            logger.info(action)
        return {
            "name": name,
            "preset": preset,
            "status": "dry-run",
            "actions": actions,
        }

    compensation = _CompensationStack()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # Step 1: Create registry entry with "creating" status
    entry = RegistryEntry(name=name, preset=preset, created=today)
    add_entry(entry, registry_path)
    compensation.push("remove registry entry", partial(_safe_remove_entry, name, registry_path))

    try:
        # Step 2: Create macOS user
        username = macos.create_user(name)
        compensation.push(f"delete macOS user {username}", partial(macos.delete_user, name))

        home_dir = Path(f"/Users/{username}")

        # Step 3: Generate SSH keypair
        public_key = ssh.generate_keypair(home_dir)
        # No separate undo needed — home dir deletion covers this

        # Step 4: Populate authorized_keys from parent's GitHub
        ssh.populate_authorized_keys(home_dir, target_user=username)

        # Step 5: Register SSH key with GitHub
        key_title = f"devbox:{name}"
        github_key_id = github.add_ssh_key(key_title, public_key, preset_obj.github_account)
        compensation.push(
            "remove GitHub SSH key",
            partial(github.remove_ssh_key, github_key_id, preset_obj.github_account),
        )
        update_entry(name, registry_path, github_key_id=github_key_id)

        # Step 6: Resolve and write env vars
        if preset_obj.env_vars:
            resolved = onepassword.resolve_env_vars(preset_obj.env_vars)
            write_env_file(home_dir, resolved, target_user=username)

        # Step 7: Inject Claude Code auth
        try:
            inject_auth(home_dir, preset_obj, username)
        except DevboxError as exc:
            logger.warning("Auth injection failed (non-fatal): %s", exc)

        # Step 8: Bootstrap user (nvm, pyenv, brew extras, pip/npm globals)
        warnings = bootstrap_user(home_dir, preset_obj, username)
        for w in warnings:
            logger.warning("Bootstrap: %s", w)

        # Step 9: Write .zshrc (heartbeat hook + env sourcing)
        try:
            write_zshrc(home_dir, name, username)
        except DevboxError as exc:
            logger.warning("zshrc write failed (non-fatal): %s", exc)

        # Step 10: Ensure SSH access
        sshd.ensure_ssh_access(username)
        compensation.push(
            f"remove {username} from SSH group",
            partial(sshd.remove_user_from_ssh_group, username),
        )

        # Step 11: Create iTerm2 profile
        iterm2.create_profile(name, preset_obj)
        compensation.push("remove iTerm2 profile", partial(iterm2.remove_profile, name))

        # Step 12: Mark ready
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

    Steps: mark nuking → remove GitHub key → remove SSH group →
    delete macOS user → remove iTerm2 profile → remove registry entry.

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
        ]
        if entry.github_key_id:
            actions.append(f"Would remove GitHub SSH key {entry.github_key_id}")
        actions.extend(
            [
                f"Would remove {username} from SSH access group",
                f"Would delete macOS user {username} and home directory",
                f"Would remove iTerm2 profile devbox::{name}",
                f"Would remove registry entry for {name!r}",
            ]
        )
        for action in actions:
            logger.info(action)
        return actions

    # Mark as nuking
    update_entry(name, registry_path, status=DevboxStatus.NUKING)

    errors: list[str] = []
    critical_failure = False

    # Remove GitHub SSH key
    if entry.github_key_id:
        try:
            preset_obj = load_preset(entry.preset)
            github.remove_ssh_key(entry.github_key_id, preset_obj.github_account)
        except Exception as exc:
            errors.append(f"GitHub key removal: {exc}")
            logger.warning("Failed to remove GitHub key: %s", exc)

    # Remove from SSH access group
    username = f"{DX_PREFIX}{name}"
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


def _safe_remove_entry(name: str, registry_path: Path | None) -> None:
    """Remove registry entry, ignoring errors (for compensation)."""
    with contextlib.suppress(DevboxError):
        remove_entry(name, registry_path)
