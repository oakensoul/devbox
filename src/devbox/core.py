"""Core devbox operations — importable by AIDA plugin."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from devbox import github, iterm2, macos, onepassword, ssh, sshd
from devbox.exceptions import DevboxError
from devbox.naming import validate_name
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

logger = logging.getLogger(__name__)

_ATROPHY_DAYS = 30
_DX_PREFIX = "dx-"


def _write_env_file(
    home_dir: Path, resolved_env: dict[str, str], target_user: str | None = None
) -> None:
    """Write resolved env vars to .devbox-env with mode 0600.

    If *target_user* is provided, chowns the file to that user so the
    devbox account can read it when .zshrc sources it.
    """
    env_path = home_dir / ".devbox-env"
    lines = [f"export {key}={_shell_escape(value)}" for key, value in resolved_env.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, 0o600)
    if target_user is not None:
        ssh.chown_path(env_path, target_user)


def _shell_escape(value: str) -> str:
    """Wrap a value in single quotes, escaping embedded single quotes."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _read_heartbeat(name: str) -> datetime | None:
    """Read the heartbeat timestamp for a devbox user."""
    heartbeat_path = Path(f"/Users/{_DX_PREFIX}{name}/.devbox_heartbeat")
    if not heartbeat_path.exists():
        return None
    try:
        text = heartbeat_path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (OSError, ValueError):
        return None


def _health_status(last_seen: datetime | None) -> str:
    """Determine health status from last_seen timestamp."""
    if last_seen is None:
        return "unknown"
    now = datetime.now(UTC)
    # Ensure last_seen is tz-aware for comparison
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    age = now - last_seen
    if age > timedelta(days=_ATROPHY_DAYS):
        return "atrophied"
    return "healthy"


def _format_last_seen(last_seen: datetime | None) -> str:
    """Format last_seen as a human-readable relative time."""
    if last_seen is None:
        return "never"
    now = datetime.now(UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    delta = now - last_seen
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = delta.seconds // 60
    if minutes > 0:
        return f"{minutes}m ago"
    return "just now"


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
) -> dict[str, Any]:
    """Create a new devbox from the given preset.

    Orchestrates: validation → macOS user → SSH keys → GitHub key →
    env file → sshd access → iTerm2 profile → registry entry.

    On failure at any step, the compensation stack rolls back all
    completed steps in reverse order.

    Returns the registry entry as a dict.
    """
    validate_name(name)
    preset_obj = load_preset(preset, presets_dir)

    # Check for existing devbox
    existing = find_entry(name, registry_path)
    if existing is not None:
        raise DevboxError(f"Devbox {name!r} already exists (status: {existing.status})")

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
        github_key_id = github.add_ssh_key(
            key_title, public_key, preset_obj.github_account
        )
        compensation.push(
            "remove GitHub SSH key",
            partial(github.remove_ssh_key, github_key_id, preset_obj.github_account),
        )
        update_entry(name, registry_path, github_key_id=github_key_id)

        # Step 6: Resolve and write env vars
        if preset_obj.env_vars:
            resolved = onepassword.resolve_env_vars(preset_obj.env_vars)
            _write_env_file(home_dir, resolved, target_user=username)

        # TODO(milestone-5): Bootstrap user (nvm, pyenv, brew extras, pip/npm globals)
        # TODO(milestone-5): Inject Claude Code auth from parent user

        # Step 7: Ensure SSH access
        sshd.ensure_ssh_access(username)
        compensation.push(
            f"remove {username} from SSH group",
            partial(sshd.remove_user_from_ssh_group, username),
        )

        # Step 8: Create iTerm2 profile
        iterm2.create_profile(name, preset_obj)
        compensation.push("remove iTerm2 profile", partial(iterm2.remove_profile, name))

        # Step 9: Mark ready
        update_entry(name, registry_path, status=DevboxStatus.READY)

    except Exception:
        compensation.rollback()
        raise

    updated = find_entry(name, registry_path)
    return updated.model_dump() if updated else entry.model_dump()


def list_devboxes(registry_path: Path | None = None) -> list[dict[str, Any]]:
    """Return all registered devboxes with health status.

    Reads heartbeat files and computes health for each entry.
    Does not modify the registry — use :func:`sync_heartbeats` to persist
    heartbeat data if desired.
    """
    registry = load_registry(registry_path)
    results: list[dict[str, Any]] = []

    for entry in registry.devboxes:
        heartbeat = _read_heartbeat(entry.name)

        last_seen_dt = heartbeat or (
            datetime.fromisoformat(entry.last_seen) if entry.last_seen else None
        )
        health = _health_status(last_seen_dt)

        results.append({
            "name": entry.name,
            "preset": entry.preset,
            "created": entry.created,
            "last_seen": _format_last_seen(last_seen_dt),
            "status": health if entry.status == DevboxStatus.READY else entry.status.value,
        })

    return results


def sync_heartbeats(registry_path: Path | None = None) -> None:
    """Update registry last_seen fields from heartbeat files.

    Separated from :func:`list_devboxes` so that listing is read-only.
    """
    registry = load_registry(registry_path)
    for entry in registry.devboxes:
        heartbeat = _read_heartbeat(entry.name)
        if heartbeat is not None:
            with contextlib.suppress(DevboxError):
                update_entry(entry.name, registry_path, last_seen=heartbeat.isoformat())


def nuke_devbox(
    name: str,
    registry_path: Path | None = None,
) -> list[str]:
    """Destroy a devbox and clean up all resources.

    Steps: mark nuking → remove GitHub key → remove SSH group →
    delete macOS user → remove iTerm2 profile → remove registry entry.

    Returns a list of non-fatal cleanup errors (empty on full success).
    If critical cleanup steps fail, the registry entry is kept in 'nuking'
    state so the user can retry.
    """
    validate_name(name)
    entry = find_entry(name, registry_path)
    if entry is None:
        raise DevboxError(f"Devbox {name!r} not found in registry")

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
    username = f"{_DX_PREFIX}{name}"
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
    return create_devbox(name, preset_name, registry_path, presets_dir)


def _safe_remove_entry(name: str, registry_path: Path | None) -> None:
    """Remove registry entry, ignoring errors (for compensation)."""
    with contextlib.suppress(DevboxError):
        remove_entry(name, registry_path)
