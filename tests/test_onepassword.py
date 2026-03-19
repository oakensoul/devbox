"""Tests for the 1Password CLI wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import OnePasswordError
from devbox.onepassword import get_secret, resolve_env_vars


class TestGetSecret:
    def test_calls_subprocess_correctly(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="secret-value")

        get_secret("op://vault/item/field", timeout=15)

        mock_run.assert_called_once_with(
            ["op", "read", "op://vault/item/field"],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_returns_stripped_output(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="secret-value\n  ")

        result = get_secret("op://vault/item/field")

        assert result == "secret-value"

    def test_raises_when_op_not_found(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.side_effect = FileNotFoundError

        with pytest.raises(OnePasswordError, match=r"1Password CLI .* is not installed"):
            get_secret("op://vault/item/field")

    def test_raises_on_nonzero_exit(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(
            returncode=1, stderr="item not found\n"
        )

        with pytest.raises(OnePasswordError, match="Failed to resolve 1Password reference"):
            get_secret("op://vault/item/field")

    def test_raises_on_timeout(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="op", timeout=10)

        with pytest.raises(OnePasswordError, match="timed out"):
            get_secret("op://vault/item/field")

    def test_uses_default_timeout(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="val")

        get_secret("op://vault/item/field")

        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 10

    def test_rejects_non_op_reference(self) -> None:
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret("/etc/passwd")

    def test_rejects_empty_reference(self) -> None:
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret("")

    def test_rejects_reference_with_spaces(self) -> None:
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret("op://vault/item with spaces/field")

    def test_rejects_reference_missing_segments(self) -> None:
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret("op://vault-only")

    def test_rejects_reference_two_segments(self) -> None:
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret("op://vault/item")

    def test_accepts_section_colon_field(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout="val")
        result = get_secret("op://vault/item/section:field")
        assert result == "val"

    def test_rejects_overlong_reference(self) -> None:
        ref = "op://vault/item/" + "a" * 500
        with pytest.raises(OnePasswordError, match="Invalid 1Password reference"):
            get_secret(ref)

    def test_error_does_not_leak_stderr(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.onepassword.subprocess.run")
        mock_run.return_value = MagicMock(
            returncode=1, stderr="[ERROR] vault 'SecretVault' item 'ApiKey': not found\n"
        )

        with pytest.raises(OnePasswordError, match="Failed to resolve") as exc_info:
            get_secret("op://vault/item/field")
        # Ensure stderr content is NOT in the error message
        assert "SecretVault" not in str(exc_info.value)
        assert "ApiKey" not in str(exc_info.value)


class TestResolveEnvVars:
    def test_resolves_op_values(self, mocker: MockerFixture) -> None:
        mock_get = mocker.patch("devbox.onepassword.get_secret", return_value="resolved")

        result = resolve_env_vars({"TOKEN": "op://vault/item/field"})

        assert result == {"TOKEN": "resolved"}
        mock_get.assert_called_once_with("op://vault/item/field")

    def test_passes_through_non_op_values(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.onepassword.get_secret")

        result = resolve_env_vars({"PATH": "/usr/bin", "HOME": "/home/user"})

        assert result == {"PATH": "/usr/bin", "HOME": "/home/user"}

    def test_handles_mixed_dict(self, mocker: MockerFixture) -> None:
        mock_get = mocker.patch("devbox.onepassword.get_secret", return_value="secret")

        result = resolve_env_vars({
            "PLAIN": "hello",
            "SECRET": "op://vault/item/field",
            "ALSO_PLAIN": "world",
        })

        assert result == {
            "PLAIN": "hello",
            "SECRET": "secret",
            "ALSO_PLAIN": "world",
        }
        mock_get.assert_called_once_with("op://vault/item/field")

    def test_raises_on_failed_resolution(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.onepassword.get_secret",
            side_effect=OnePasswordError("bad ref"),
        )

        with pytest.raises(OnePasswordError, match="bad ref"):
            resolve_env_vars({"TOKEN": "op://vault/bad/ref"})

    def test_empty_dict_returns_empty(self) -> None:
        result = resolve_env_vars({})

        assert result == {}
