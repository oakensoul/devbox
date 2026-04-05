# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Integration tests for devbox — run with pytest -m integration."""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from devbox.iterm2 import create_profile, remove_profile
from devbox.presets import Preset
from devbox.ssh import copy_keypair

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only tests"),
]


# ---------------------------------------------------------------------------
# TestMacOSUser
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.getuid() != 0, reason="Requires root privileges for dscl operations")
class TestMacOSUser:
    """Integration tests for macOS user creation and deletion via dscl."""

    _TEST_NAME = "integration-test"

    @pytest.fixture()
    def cleanup_user(self) -> Iterator[str]:
        """Yield the test name and ensure the user is removed afterwards."""
        from devbox.macos import _user_exists, delete_user
        from devbox.naming import DX_PREFIX

        name = self._TEST_NAME
        username = f"{DX_PREFIX}{name}"

        # Ensure no leftover from a previous run.
        if _user_exists(username):
            delete_user(name)

        yield name

        # Teardown: delete the user if still present.
        if _user_exists(username):
            delete_user(name)

    def test_create_and_delete_user(self, cleanup_user: str) -> None:
        from devbox.macos import _user_exists, create_user, delete_user
        from devbox.naming import DX_PREFIX

        name = cleanup_user
        username = f"{DX_PREFIX}{name}"

        # Create the user and verify it exists.
        result = create_user(name)
        assert result == username
        assert _user_exists(username)

        # Delete the user and verify it is gone.
        delete_user(name)
        assert not _user_exists(username)


# ---------------------------------------------------------------------------
# TestSSHKeypair
# ---------------------------------------------------------------------------


class TestSSHKeypair:
    """Integration tests for SSH keypair generation."""

    @pytest.fixture()
    def home_dir(self, tmp_path: Path) -> Path:
        """Provide a temporary home directory for keypair generation."""
        return tmp_path / "dx-sshtest"

    def test_copy_keypair_creates_files(self, home_dir: Path) -> None:
        home_dir.mkdir(parents=True)
        pub_key = copy_keypair(home_dir)

        ssh_dir = home_dir / ".ssh"
        private_key = ssh_dir / "id_ed25519"
        public_key = ssh_dir / "id_ed25519.pub"

        assert ssh_dir.is_dir()
        assert private_key.is_file()
        assert public_key.is_file()

        # Verify the returned public key matches the file content.
        assert pub_key == public_key.read_text(encoding="utf-8").strip()

        # Verify permissions.
        assert stat.S_IMODE(os.stat(ssh_dir).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(private_key).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(public_key).st_mode) == 0o644


# ---------------------------------------------------------------------------
# TestITermProfile
# ---------------------------------------------------------------------------


class TestITermProfile:
    """Integration tests for iTerm2 dynamic profile management."""

    _TEST_NAME = "integration-test"

    @pytest.fixture()
    def profiles_dir(self, tmp_path: Path) -> Path:
        """Provide a temporary profiles directory."""
        d = tmp_path / "DynamicProfiles"
        d.mkdir()
        return d

    @pytest.fixture()
    def preset(self) -> Preset:
        """Return a minimal Preset for testing."""
        return Preset(
            name=self._TEST_NAME,
            description="integration test preset",
            provider="local",
            github_account="octocat",
        )

    def test_create_and_remove_profile(self, profiles_dir: Path, preset: Preset) -> None:
        name = self._TEST_NAME

        # Create profile and verify the file exists with expected content.
        path = create_profile(name, preset, profiles_dir=profiles_dir)
        assert path.is_file()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "Profiles" in data
        assert data["Profiles"][0]["Name"] == f"devbox::{name}"

        # Remove profile and verify the file is gone.
        remove_profile(name, profiles_dir=profiles_dir)
        assert not path.exists()
