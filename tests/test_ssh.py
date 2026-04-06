# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for SSH key generation and authorized_keys."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import SSHError
from devbox.ssh import (
    _get_parent_github_user,
    _validate_ssh_keys,
    copy_keypair,
    populate_authorized_keys,
)


class TestCopyKeypair:
    def _setup_parent_keys(self, mocker: MockerFixture, tmp_path: Path) -> Path:
        """Create fake parent SSH keys and patch Path.home() to use them."""
        parent_home = tmp_path / "parent"
        parent_ssh = parent_home / ".ssh"
        parent_ssh.mkdir(parents=True)
        (parent_ssh / "id_ed25519_test").write_text("PRIVATE KEY")
        (parent_ssh / "id_ed25519_test.pub").write_text("ssh-ed25519 AAAA user@host\n")
        mocker.patch("devbox.ssh.Path.home", return_value=parent_home)
        # Patch subprocess.run for ssh-keyscan (known_hosts population)
        mocker.patch(
            "devbox.ssh.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="github.com ssh-ed25519 AAAA\n"),
        )
        return parent_home

    def test_copies_keypair_and_returns_public_key(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        self._setup_parent_keys(mocker, tmp_path)
        home = tmp_path / "dx-dev1"
        home.mkdir()

        result = copy_keypair(home, "id_ed25519_test")

        assert result == "ssh-ed25519 AAAA user@host"
        assert (home / ".ssh" / "id_ed25519_test").exists()
        assert (home / ".ssh" / "id_ed25519_test.pub").exists()

    def test_raises_if_private_key_missing(self, tmp_path: Path, mocker: MockerFixture) -> None:
        parent_home = tmp_path / "parent"
        (parent_home / ".ssh").mkdir(parents=True)
        mocker.patch("devbox.ssh.Path.home", return_value=parent_home)

        home = tmp_path / "dx-dev1"
        home.mkdir()

        with pytest.raises(SSHError, match="not found"):
            copy_keypair(home, "id_ed25519_test")

    def test_sets_correct_permissions(self, tmp_path: Path, mocker: MockerFixture) -> None:
        self._setup_parent_keys(mocker, tmp_path)
        home = tmp_path / "dx-dev1"
        home.mkdir()

        copy_keypair(home, "id_ed25519_test")

        ssh_dir = home / ".ssh"
        assert (ssh_dir.stat().st_mode & 0o777) == 0o700
        assert ((ssh_dir / "id_ed25519_test").stat().st_mode & 0o777) == 0o600
        assert ((ssh_dir / "id_ed25519_test.pub").stat().st_mode & 0o777) == 0o644

    def test_writes_ssh_config(self, tmp_path: Path, mocker: MockerFixture) -> None:
        self._setup_parent_keys(mocker, tmp_path)
        home = tmp_path / "dx-dev1"
        home.mkdir()

        copy_keypair(home, "id_ed25519_test")

        config = (home / ".ssh" / "config").read_text(encoding="utf-8")
        assert "IdentityFile ~/.ssh/id_ed25519_test" in config
        assert "github.com" in config

    def test_rejects_path_traversal(self, tmp_path: Path, mocker: MockerFixture) -> None:
        self._setup_parent_keys(mocker, tmp_path)
        home = tmp_path / "dx-dev1"
        home.mkdir()

        with pytest.raises(SSHError, match="Invalid"):
            copy_keypair(home, "../etc/passwd")


class TestValidateSSHKeys:
    def test_valid_ed25519(self) -> None:
        content = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 user@host\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 1

    def test_valid_rsa(self) -> None:
        content = "ssh-rsa AAAAB3NzaC1yc2E user@host\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 1

    def test_multiple_keys(self) -> None:
        content = "ssh-ed25519 AAAA user1\nssh-rsa BBBB user2\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 2

    def test_skips_invalid_lines(self) -> None:
        content = "ssh-ed25519 AAAA user1\nnot-a-key\nssh-rsa BBBB user2\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 2

    def test_empty_content(self) -> None:
        assert _validate_ssh_keys("") == []
        assert _validate_ssh_keys("\n\n") == []

    def test_ecdsa_accepted(self) -> None:
        content = "ecdsa-sha2-nistp256 AAAA user@host\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 1

    def test_sk_ed25519_accepted(self) -> None:
        content = "sk-ssh-ed25519 AAAA user@host\n"
        keys = _validate_ssh_keys(content)
        assert len(keys) == 1


class TestGetParentGithubUser:
    def test_reads_from_config(self, tmp_path: Path, mocker: MockerFixture) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"parent_github_user": "testuser"}))
        mocker.patch("devbox.ssh._CONFIG_PATH", config_path)

        result = _get_parent_github_user()
        assert result == "testuser"

    def test_missing_config_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.ssh._CONFIG_PATH", tmp_path / "missing.json")

        with pytest.raises(SSHError, match="Config file not found"):
            _get_parent_github_user()

    def test_missing_key_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"other": "value"}))
        mocker.patch("devbox.ssh._CONFIG_PATH", config_path)

        with pytest.raises(SSHError, match="parent_github_user not set"):
            _get_parent_github_user()

    def test_invalid_json_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("{bad json")
        mocker.patch("devbox.ssh._CONFIG_PATH", config_path)

        with pytest.raises(SSHError, match="Failed to read config"):
            _get_parent_github_user()


class TestPopulateAuthorizedKeys:
    def test_fetches_and_writes_keys(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(
            status_code=200,
            text="ssh-ed25519 AAAA user@host\nssh-rsa BBBB user@host\n",
        )
        mock_get.return_value.raise_for_status = MagicMock()

        count = populate_authorized_keys(home, github_user="testuser")

        assert count == 2
        auth_keys = home / ".ssh" / "authorized_keys"
        assert auth_keys.exists()
        assert (auth_keys.stat().st_mode & 0o777) == 0o600
        content = auth_keys.read_text()
        assert "ssh-ed25519" in content
        assert "ssh-rsa" in content

    def test_no_valid_keys_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(status_code=200, text="not a key\n")
        mock_get.return_value.raise_for_status = MagicMock()

        with pytest.raises(SSHError, match="No valid SSH public keys"):
            populate_authorized_keys(home, github_user="nobody")

    def test_network_error_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        import requests

        mocker.patch(
            "devbox.ssh.requests.get",
            side_effect=requests.ConnectionError("connection refused"),
        )

        with pytest.raises(SSHError, match="Failed to fetch SSH keys"):
            populate_authorized_keys(home, github_user="testuser")

    def test_uses_config_when_no_user_given(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mocker.patch("devbox.ssh._get_parent_github_user", return_value="config-user")
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(
            status_code=200,
            text="ssh-ed25519 AAAA user@host\n",
        )
        mock_get.return_value.raise_for_status = MagicMock()

        populate_authorized_keys(home)

        mock_get.assert_called_once_with("https://github.com/config-user.keys", timeout=10)

    def test_ssh_dir_permissions(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(status_code=200, text="ssh-ed25519 AAAA user@host\n")
        mock_get.return_value.raise_for_status = MagicMock()

        populate_authorized_keys(home, github_user="user")

        ssh_dir = home / ".ssh"
        assert (ssh_dir.stat().st_mode & 0o777) == 0o700

    def test_chown_called_with_target_user(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(status_code=200, text="ssh-ed25519 AAAA user@host\n")
        mock_get.return_value.raise_for_status = MagicMock()
        mock_run = mocker.patch("devbox.ssh.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)

        populate_authorized_keys(home, github_user="user", target_user="dx-dev1")

        chown_calls = [c for c in mock_run.call_args_list if "chown" in str(c)]
        assert len(chown_calls) == 1
        assert "dx-dev1:staff" in str(chown_calls[0])

    def test_invalid_target_user_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(status_code=200, text="ssh-ed25519 AAAA user@host\n")
        mock_get.return_value.raise_for_status = MagicMock()

        with pytest.raises(SSHError, match="Invalid target user"):
            populate_authorized_keys(home, github_user="user", target_user="root")

    def test_invalid_github_user_raises(self, tmp_path: Path) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        with pytest.raises(SSHError, match="Invalid GitHub username"):
            populate_authorized_keys(home, github_user="user; echo pwned")

    def test_path_traversal_github_user_raises(self, tmp_path: Path) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        with pytest.raises(SSHError, match="Invalid GitHub username"):
            populate_authorized_keys(home, github_user="../../etc/passwd")
