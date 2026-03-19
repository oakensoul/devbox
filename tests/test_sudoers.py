# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for sudoers configuration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import SudoersError
from devbox.sudoers import (
    SUDOERS_CONTENT,
    SUDOERS_PATH,
    install,
    is_configured,
    validate,
)


class TestSudoersConstants:
    def test_sudoers_path(self) -> None:
        assert Path("/etc/sudoers.d/devbox") == SUDOERS_PATH

    def test_content_starts_with_comment(self) -> None:
        assert SUDOERS_CONTENT.startswith("# Managed by devbox")

    def test_content_contains_dscl_create(self) -> None:
        assert "dscl . -create /Users/dx-*" in SUDOERS_CONTENT

    def test_content_contains_dscl_delete(self) -> None:
        assert "dscl . -delete /Users/dx-*" in SUDOERS_CONTENT

    def test_content_contains_createhomedir(self) -> None:
        assert "createhomedir -u dx-*" in SUDOERS_CONTENT

    def test_content_contains_rm(self) -> None:
        assert "rm -rf /Users/dx-*" in SUDOERS_CONTENT

    def test_content_contains_dseditgroup_add(self) -> None:
        assert "dseditgroup -o edit -a dx-* -t user com.apple.access_ssh" in SUDOERS_CONTENT

    def test_content_contains_dseditgroup_delete(self) -> None:
        assert "dseditgroup -o edit -d dx-* -t user com.apple.access_ssh" in SUDOERS_CONTENT

    def test_content_contains_dseditgroup_checkmember(self) -> None:
        assert "dseditgroup -o checkmember -m dx-* com.apple.access_ssh" in SUDOERS_CONTENT

    def test_content_contains_systemsetup(self) -> None:
        assert "systemsetup -getremotelogin" in SUDOERS_CONTENT

    def test_content_contains_chown(self) -> None:
        assert "chown -R dx-*" in SUDOERS_CONTENT

    def test_content_contains_pwpolicy(self) -> None:
        assert "pwpolicy -u dx-* -disableuser" in SUDOERS_CONTENT


class TestIsConfigured:
    def test_valid_file(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        sudoers_file.write_text(SUDOERS_CONTENT)
        assert is_configured(sudoers_file) is True

    def test_missing_file(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        assert is_configured(sudoers_file) is False

    def test_wrong_content(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        sudoers_file.write_text("wrong content\n")
        assert is_configured(sudoers_file) is False

    def test_empty_file(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        sudoers_file.write_text("")
        assert is_configured(sudoers_file) is False

    def test_partial_content(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        # Only the first line
        sudoers_file.write_text("# Managed by devbox — do not edit manually\n")
        assert is_configured(sudoers_file) is False

    def test_extra_content(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        sudoers_file.write_text(SUDOERS_CONTENT + "extra line\n")
        assert is_configured(sudoers_file) is False

    def test_permission_error(self, tmp_path: Path) -> None:
        sudoers_file = tmp_path / "devbox"
        sudoers_file.write_text(SUDOERS_CONTENT)
        sudoers_file.chmod(0o000)
        try:
            assert is_configured(sudoers_file) is False
        finally:
            sudoers_file.chmod(0o644)

    def test_defaults_to_sudoers_path(self, mocker: MockerFixture) -> None:
        mock_read = mocker.patch("devbox.sudoers.Path.read_text", return_value=SUDOERS_CONTENT)
        result = is_configured()
        assert result is True
        mock_read.assert_called_once()


class TestValidate:
    def test_raises_when_not_configured(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sudoers.is_configured", return_value=False)
        with pytest.raises(SudoersError, match="not configured"):
            validate()

    def test_passes_when_configured(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sudoers.is_configured", return_value=True)
        validate()  # should not raise

    def test_error_message_contains_path(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sudoers.is_configured", return_value=False)
        with pytest.raises(SudoersError, match=r"/etc/sudoers\.d/devbox"):
            validate()

    def test_error_message_contains_install_hint(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.sudoers.is_configured", return_value=False)
        with pytest.raises(SudoersError, match="sudo tee"):
            validate()


class TestInstall:
    def test_validates_before_writing(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        install()

        # First subprocess call should be visudo (validate before write)
        visudo_call = mock_run.call_args_list[0]
        assert "visudo" in visudo_call[0][0]
        assert "-c" in visudo_call[0][0]
        assert "/tmp/devbox-sudoers-xyz" in visudo_call[0][0]

    def test_writes_correct_content(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        install()

        # Second call should be sudo tee
        tee_call = mock_run.call_args_list[1]
        assert tee_call[0][0] == ["sudo", "tee", str(SUDOERS_PATH)]
        assert tee_call[1]["input"] == SUDOERS_CONTENT

    def test_sets_permissions(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        install()

        # Third call should be sudo chmod 0440
        chmod_call = mock_run.call_args_list[2]
        assert chmod_call[0][0] == ["sudo", "chmod", "0440", str(SUDOERS_PATH)]

    def test_custom_path(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        custom = Path("/tmp/test-sudoers")

        install(path=custom)

        tee_call = mock_run.call_args_list[1]
        assert str(custom) in tee_call[0][0]

    def test_cleans_up_temp_file(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mock_unlink = mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        install()

        mock_unlink.assert_called_once_with("/tmp/devbox-sudoers-xyz")

    def test_cleans_up_temp_file_on_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mock_unlink = mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="syntax error")

        with pytest.raises(SudoersError):
            install()

        mock_unlink.assert_called_once_with("/tmp/devbox-sudoers-xyz")

    def test_raises_on_tee_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            cmd = args[0]
            assert isinstance(cmd, list)
            if "tee" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="permission denied")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        with pytest.raises(SudoersError, match="Failed to write"):
            install()

    def test_raises_on_chmod_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            cmd = args[0]
            assert isinstance(cmd, list)
            if "chmod" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="error")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        with pytest.raises(SudoersError, match="Failed to set permissions"):
            install()

    def test_raises_on_visudo_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")
        mock_run = mocker.patch("devbox.sudoers.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="syntax error")

        with pytest.raises(SudoersError, match="visudo validation failed"):
            install()

    def test_raises_on_tee_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # visudo succeeds
                return MagicMock(returncode=0, stdout="", stderr="")
            raise FileNotFoundError

        mocker.patch("devbox.sudoers.subprocess.run", side_effect=side_effect)
        with pytest.raises(SudoersError, match="sudo or tee not found"):
            install()

    def test_raises_on_tee_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # visudo succeeds
                return MagicMock(returncode=0, stdout="", stderr="")
            raise subprocess.TimeoutExpired(cmd="tee", timeout=30)

        mocker.patch("devbox.sudoers.subprocess.run", side_effect=side_effect)
        with pytest.raises(SudoersError, match="timed out"):
            install()

    def test_raises_on_visudo_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        mocker.patch("devbox.sudoers.subprocess.run", side_effect=FileNotFoundError)
        with pytest.raises(SudoersError, match="visudo not found"):
            install()

    def test_raises_on_visudo_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        mocker.patch(
            "devbox.sudoers.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="visudo", timeout=30),
        )
        with pytest.raises(SudoersError, match="visudo timed out"):
            install()

    def test_raises_on_chmod_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return MagicMock(returncode=0, stdout="", stderr="")
            raise FileNotFoundError

        mocker.patch("devbox.sudoers.subprocess.run", side_effect=side_effect)
        with pytest.raises(SudoersError, match="sudo or chmod not found"):
            install()

    def test_raises_on_chmod_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.sudoers.tempfile.mkstemp",
            return_value=(99, "/tmp/devbox-sudoers-xyz"),
        )
        mocker.patch("devbox.sudoers.os.write")
        mocker.patch("devbox.sudoers.os.close")
        mocker.patch("devbox.sudoers.os.unlink")

        call_count = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return MagicMock(returncode=0, stdout="", stderr="")
            raise subprocess.TimeoutExpired(cmd="chmod", timeout=30)

        mocker.patch("devbox.sudoers.subprocess.run", side_effect=side_effect)
        with pytest.raises(SudoersError, match="timed out setting permissions"):
            install()
