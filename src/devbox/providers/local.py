# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Local macOS provider.

Delegates to the platform modules via :mod:`devbox.core` orchestration.
This provider is the integration point for local macOS devbox environments;
a future provider (e.g., ECS/EC2) would implement the same interface with
different backend calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from devbox import github, iterm2, macos, onepassword, ssh, sshd
from devbox.core import write_env_file
from devbox.naming import DX_PREFIX
from devbox.presets import Preset
from devbox.providers.base import Provider

logger = logging.getLogger(__name__)


class LocalProvider(Provider):
    """Provisions devboxes as local macOS user accounts."""

    def provision(self, name: str, preset: dict[str, Any]) -> dict[str, Any]:
        """Provision a new local macOS devbox.

        Note: For full orchestration with compensation stack and registry
        management, use :func:`devbox.core.create_devbox` instead. This
        method provides the raw platform operations without rollback logic.
        """
        preset_obj = Preset.model_validate(preset)

        username = macos.create_user(name)
        home_dir = Path(f"/Users/{username}")

        public_key = ssh.copy_keypair(home_dir)
        ssh.populate_authorized_keys(home_dir, target_user=username)

        key_title = f"devbox:{name}"
        github_key_id = github.add_ssh_key(key_title, public_key, preset_obj.github_account)

        if preset_obj.env_vars:
            resolved = onepassword.resolve_env_vars(preset_obj.env_vars)
            write_env_file(home_dir, resolved, target_user=username)

        sshd.ensure_ssh_access(username)
        iterm2.create_profile(name, preset_obj)

        return {
            "username": username,
            "home_dir": str(home_dir),
            "github_key_id": github_key_id,
        }

    def destroy(self, name: str, registry_entry: dict[str, Any]) -> None:
        """Destroy an existing local macOS devbox.

        Each step is best-effort — failures are logged but don't block
        remaining cleanup.
        """
        username = f"{DX_PREFIX}{name}"

        github_key_id = registry_entry.get("github_key_id")
        github_account = registry_entry.get("github_account")
        if github_key_id and github_account:
            try:
                github.remove_ssh_key(str(github_key_id), github_account)
            except Exception as exc:
                logger.warning("Failed to remove GitHub key: %s", exc)

        try:
            sshd.remove_user_from_ssh_group(username)
        except Exception as exc:
            logger.warning("Failed to remove from SSH group: %s", exc)

        try:
            macos.delete_user(name)
        except Exception as exc:
            logger.warning("Failed to delete macOS user: %s", exc)

        try:
            iterm2.remove_profile(name)
        except Exception as exc:
            logger.warning("Failed to remove iTerm2 profile: %s", exc)
