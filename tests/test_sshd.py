"""Tests for sshd configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import SshdError
from devbox.sshd import (
    add_user_to_ssh_group,
    ensure_ssh_access,
    is_remote_login_enabled,
    is_user_in_ssh_group,
    remove_user_from_ssh_group,
)


class TestIsRemoteLoginEnabled:
    def test_enabled(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Remote Login: On"
        )
        assert is_remote_login_enabled() is True

    def test_disabled(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Remote Login: Off"
        )
        assert is_remote_login_enabled() is False

    def test_command_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(SshdError, match="command not found"):
            is_remote_login_enabled()


class TestIsUserInSSHGroup:
    def test_member(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        assert is_user_in_ssh_group("dx-dev1") is True

    def test_not_member(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1)
        assert is_user_in_ssh_group("dx-dev1") is False


class TestAddUserToSSHGroup:
    def test_adds_user(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=False)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)

        add_user_to_ssh_group("dx-dev1")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "dseditgroup" in cmd
        assert "dx-dev1" in cmd

    def test_skips_if_already_member(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=True)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")

        add_user_to_ssh_group("dx-dev1")

        mock_run.assert_not_called()

    def test_raises_on_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=False)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(SshdError, match="Failed to add"):
            add_user_to_ssh_group("dx-dev1")


class TestRemoveUserFromSSHGroup:
    def test_removes_user(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=True)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)

        remove_user_from_ssh_group("dx-dev1")

        mock_run.assert_called_once()

    def test_idempotent_when_not_member(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=False)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")

        remove_user_from_ssh_group("dx-dev1")

        mock_run.assert_not_called()

    def test_raises_on_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_user_in_ssh_group", return_value=True)
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(SshdError, match="Failed to remove"):
            remove_user_from_ssh_group("dx-dev1")


class TestUsernameValidation:
    def test_rejects_non_dx_prefix(self) -> None:
        with pytest.raises(SshdError, match="Invalid devbox username"):
            is_user_in_ssh_group("baduser")

    def test_rejects_empty(self) -> None:
        with pytest.raises(SshdError, match="Invalid devbox username"):
            is_user_in_ssh_group("")

    def test_rejects_injection_attempt(self) -> None:
        with pytest.raises(SshdError, match="Invalid devbox username"):
            add_user_to_ssh_group("dx-; rm -rf /")

    def test_accepts_valid_dx_name(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.sshd.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        assert is_user_in_ssh_group("dx-my-devbox") is True


class TestEnsureSSHAccess:
    def test_enables_when_remote_login_on(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_remote_login_enabled", return_value=True)
        mock_add = mocker.patch("devbox.sshd.add_user_to_ssh_group")

        ensure_ssh_access("dx-dev1")

        mock_add.assert_called_once_with("dx-dev1")

    def test_raises_when_remote_login_off(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sshd.is_remote_login_enabled", return_value=False)

        with pytest.raises(SshdError, match=r"Remote Login.*not enabled"):
            ensure_ssh_access("dx-dev1")
