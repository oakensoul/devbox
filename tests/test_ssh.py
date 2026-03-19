"""Tests for SSH key generation and authorized_keys."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import SSHError
from devbox.ssh import (
    _get_parent_github_user,
    _validate_ssh_keys,
    generate_keypair,
    populate_authorized_keys,
)


class TestGenerateKeypair:
    def test_calls_ssh_keygen(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()

        def fake_keygen(*args: object, **kwargs: object) -> MagicMock:
            ssh_dir = home / ".ssh"
            ssh_dir.mkdir(parents=True, exist_ok=True)
            (ssh_dir / "id_ed25519").write_text("PRIVATE KEY")
            (ssh_dir / "id_ed25519.pub").write_text("ssh-ed25519 AAAA devbox-dx-dev1\n")
            return MagicMock(returncode=0)

        mock_run = mocker.patch("devbox.ssh.subprocess.run", side_effect=fake_keygen)

        result = generate_keypair(home)

        assert result == "ssh-ed25519 AAAA devbox-dx-dev1"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "ssh-keygen"
        assert "-t" in call_args
        assert "ed25519" in call_args

    def test_raises_if_key_exists(self, tmp_path: Path) -> None:
        home = tmp_path / "dx-dev1"
        ssh_dir = home / ".ssh"
        ssh_dir.mkdir(parents=True)
        (ssh_dir / "id_ed25519").write_text("existing")

        with pytest.raises(SSHError, match="already exists"):
            generate_keypair(home)

    def test_raises_if_ssh_keygen_missing(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mocker.patch("devbox.ssh.subprocess.run", side_effect=FileNotFoundError)

        with pytest.raises(SSHError, match="ssh-keygen is not available"):
            generate_keypair(home)

    def test_raises_on_nonzero_exit(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_run = mocker.patch("devbox.ssh.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(SSHError, match="ssh-keygen failed"):
            generate_keypair(home)

    def test_raises_on_timeout(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mocker.patch(
            "devbox.ssh.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=30),
        )

        with pytest.raises(SSHError, match="timed out"):
            generate_keypair(home)

    def test_sets_correct_permissions(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()

        def fake_keygen(*args: object, **kwargs: object) -> MagicMock:
            ssh_dir = home / ".ssh"
            ssh_dir.mkdir(parents=True, exist_ok=True)
            (ssh_dir / "id_ed25519").write_text("PRIVATE")
            (ssh_dir / "id_ed25519.pub").write_text("ssh-ed25519 AAAA test\n")
            return MagicMock(returncode=0)

        mocker.patch("devbox.ssh.subprocess.run", side_effect=fake_keygen)

        generate_keypair(home)

        ssh_dir = home / ".ssh"
        assert (ssh_dir.stat().st_mode & 0o777) == 0o700
        assert ((ssh_dir / "id_ed25519").stat().st_mode & 0o777) == 0o600
        assert ((ssh_dir / "id_ed25519.pub").stat().st_mode & 0o777) == 0o644


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
        content = (
            "ssh-ed25519 AAAA user1\n"
            "ssh-rsa BBBB user2\n"
        )
        keys = _validate_ssh_keys(content)
        assert len(keys) == 2

    def test_skips_invalid_lines(self) -> None:
        content = (
            "ssh-ed25519 AAAA user1\n"
            "not-a-key\n"
            "ssh-rsa BBBB user2\n"
        )
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
        config_path.write_text(json.dumps({"parent_github_user": "oakensoul"}))
        mocker.patch("devbox.ssh._CONFIG_PATH", config_path)

        result = _get_parent_github_user()
        assert result == "oakensoul"

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

        count = populate_authorized_keys(home, github_user="oakensoul")

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
        mock_get.return_value = MagicMock(
            status_code=200, text="not a key\n"
        )
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
            populate_authorized_keys(home, github_user="oakensoul")

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

        mock_get.assert_called_once_with(
            "https://github.com/config-user.keys", timeout=10
        )

    def test_ssh_dir_permissions(self, tmp_path: Path, mocker: MockerFixture) -> None:
        home = tmp_path / "dx-dev1"
        home.mkdir()
        mock_get = mocker.patch("devbox.ssh.requests.get")
        mock_get.return_value = MagicMock(
            status_code=200, text="ssh-ed25519 AAAA user@host\n"
        )
        mock_get.return_value.raise_for_status = MagicMock()

        populate_authorized_keys(home, github_user="user")

        ssh_dir = home / ".ssh"
        assert (ssh_dir.stat().st_mode & 0o777) == 0o700

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
