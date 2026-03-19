# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for macOS user management."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import MacOSUserError
from devbox.macos import (
    _macos_username,
    _next_uid,
    create_user,
    delete_user,
    disable_password,
)


class TestMacosUsername:
    def test_prefix(self) -> None:
        assert _macos_username("my-devbox") == "dx-my-devbox"

    def test_simple_name(self) -> None:
        assert _macos_username("dev1") == "dx-dev1"


class TestNextUid:
    def test_first_available(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.macos._get_used_uids",
            return_value={600, 601, 602},
        )
        assert _next_uid() == 603

    def test_skips_used(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.macos._get_used_uids",
            return_value={600, 602},
        )
        assert _next_uid() == 601

    def test_range_exhausted(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.macos._get_used_uids",
            return_value=set(range(600, 700)),
        )
        with pytest.raises(MacOSUserError, match="No available UIDs"):
            _next_uid()

    def test_empty_range(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos._get_used_uids", return_value=set())
        assert _next_uid() == 600


class TestGetUsedUids:
    def test_parses_dscl_output(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="nobody -2\nroot 0\nuser1 501\ndx-dev1 600\n",
        )
        from devbox.macos import _get_used_uids

        uids = _get_used_uids()
        assert 0 in uids
        assert 501 in uids
        assert 600 in uids

    def test_dscl_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos.subprocess.run", side_effect=FileNotFoundError)
        from devbox.macos import _get_used_uids

        with pytest.raises(MacOSUserError, match="dscl is not available"):
            _get_used_uids()

    def test_dscl_timeout(self, mocker: MockerFixture) -> None:
        import subprocess

        mocker.patch(
            "devbox.macos.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="dscl", timeout=10),
        )
        from devbox.macos import _get_used_uids

        with pytest.raises(MacOSUserError, match="timed out"):
            _get_used_uids()


class TestCreateUser:
    def test_creates_user_with_correct_dscl_commands(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        # _user_exists returns False (user doesn't exist)
        # _get_used_uids returns empty set
        # All dscl and createhomedir calls succeed
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mocker.patch("devbox.macos._get_used_uids", return_value=set())

        result = create_user("dev1")

        assert result == "dx-dev1"

    def test_raises_if_user_exists(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos._user_exists", return_value=True)

        with pytest.raises(MacOSUserError, match="already exists"):
            create_user("dev1")

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            create_user("Bad_Name")

    def test_uid_allocation(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mocker.patch("devbox.macos._get_used_uids", return_value={600, 601})

        create_user("dev1")

        # Check that UID 602 was used in dscl command
        calls = mock_run.call_args_list
        uid_call = [c for c in calls if "UniqueID" in str(c)]
        assert len(uid_call) == 1
        assert "602" in str(uid_call[0])


class TestDeleteUser:
    def test_deletes_existing_user(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        mocker.patch("devbox.macos._user_exists", return_value=True)

        delete_user("dev1")

        # Should have called dscl -delete and rm -rf
        calls = mock_run.call_args_list
        assert any("-delete" in str(c) for c in calls)
        assert any("rm" in str(c) and "-rf" in str(c) for c in calls)

    def test_idempotent_when_user_gone(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mock_run = mocker.patch("devbox.macos.subprocess.run")

        delete_user("dev1")

        # Should not call any subprocess commands
        mock_run.assert_not_called()

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            delete_user("Bad_Name")


class TestCreateUserRollback:
    def test_rolls_back_on_dscl_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mocker.patch("devbox.macos._get_used_uids", return_value=set())

        call_count = 0

        def fail_on_third(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 3:  # fail on PrimaryGroupID
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="")

        mock_run = mocker.patch("devbox.macos.subprocess.run", side_effect=fail_on_third)

        with pytest.raises(MacOSUserError, match="dscl failed"):
            create_user("dev1")

        # Verify cleanup was attempted (-delete call)
        calls = mock_run.call_args_list
        assert any("-delete" in str(c) for c in calls)


class TestUserExistsErrorHandling:
    def test_dscl_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos.subprocess.run", side_effect=FileNotFoundError)
        from devbox.macos import _user_exists

        with pytest.raises(MacOSUserError, match="dscl is not available"):
            _user_exists("dx-dev1")

    def test_dscl_timeout(self, mocker: MockerFixture) -> None:
        import subprocess as sp

        mocker.patch(
            "devbox.macos.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="dscl", timeout=10),
        )
        from devbox.macos import _user_exists

        with pytest.raises(MacOSUserError, match="timed out"):
            _user_exists("dx-dev1")


class TestDisablePassword:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        disable_password("dev1")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["sudo", "pwpolicy", "-u", "dx-dev1", "-disableuser"]

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            disable_password("Bad_Name")

    def test_command_failure(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

        with pytest.raises(MacOSUserError, match="Failed to disable password"):
            disable_password("dev1")

    def test_command_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos.subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(MacOSUserError, match="command not found"):
            disable_password("dev1")

    def test_command_timeout(self, mocker: MockerFixture) -> None:
        import subprocess as sp

        mocker.patch(
            "devbox.macos.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="pwpolicy", timeout=30),
        )
        with pytest.raises(MacOSUserError, match="timed out"):
            disable_password("dev1")

    def test_called_during_create_user(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.macos.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mocker.patch("devbox.macos._get_used_uids", return_value=set())

        create_user("dev1")

        # pwpolicy should be called (part of the subprocess calls)
        calls = mock_run.call_args_list
        pwpolicy_calls = [c for c in calls if "pwpolicy" in str(c)]
        assert len(pwpolicy_calls) == 1
        assert "-disableuser" in str(pwpolicy_calls[0])

    def test_create_user_rolls_back_on_disable_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.macos._user_exists", return_value=False)
        mocker.patch("devbox.macos._get_used_uids", return_value=set())

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            cmd = args[0]
            assert isinstance(cmd, list)
            # Fail on pwpolicy call (the 9th subprocess call:
            # 7 dscl + 1 createhomedir + 1 pwpolicy)
            if "pwpolicy" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="")

        mock_run = mocker.patch("devbox.macos.subprocess.run", side_effect=side_effect)

        with pytest.raises(MacOSUserError, match="Failed to disable password"):
            create_user("dev1")

        # Verify cleanup was attempted (-delete call)
        calls = mock_run.call_args_list
        assert any("-delete" in str(c) for c in calls)


class TestPathValidation:
    def test_rejects_non_dx_path(self) -> None:
        from devbox.macos import _validate_home_dir

        with pytest.raises(MacOSUserError, match="Refusing to operate"):
            _validate_home_dir("/Users/admin")

    def test_rejects_traversal(self) -> None:
        from devbox.macos import _validate_home_dir

        with pytest.raises(MacOSUserError, match="Path traversal"):
            _validate_home_dir("/Users/dx-../etc")

    def test_accepts_valid_path(self) -> None:
        from devbox.macos import _validate_home_dir

        _validate_home_dir("/Users/dx-my-devbox")  # should not raise
