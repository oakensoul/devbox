"""Tests for LocalProvider (local macOS provider)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.providers.base import Provider
from devbox.providers.local import LocalProvider


def _minimal_preset(**overrides: Any) -> dict[str, Any]:
    """Return a valid preset dict with sensible defaults, accepting overrides."""
    base: dict[str, Any] = {
        "name": "test-box",
        "description": "A test devbox",
        "provider": "local",
        "github_account": "octocat",
    }
    base.update(overrides)
    return base


class TestLocalProviderInterface:
    """Verify LocalProvider satisfies the Provider contract."""

    def test_is_subclass_of_provider(self) -> None:
        assert issubclass(LocalProvider, Provider)

    def test_instance_is_provider(self) -> None:
        provider = LocalProvider()
        assert isinstance(provider, Provider)

    def test_has_provision_method(self) -> None:
        provider = LocalProvider()
        assert callable(getattr(provider, "provision", None))

    def test_has_destroy_method(self) -> None:
        provider = LocalProvider()
        assert callable(getattr(provider, "destroy", None))


class TestLocalProviderProvision:
    """Test LocalProvider.provision orchestration."""

    def _mock_modules(self, mocker: MockerFixture) -> dict[str, MagicMock]:
        """Patch all external module calls and return the mocks.

        Modules imported at module level in local.py (macos, github, sshd,
        iterm2) are patched via ``devbox.providers.local.<mod>``.  Modules
        that are deferred-imported inside ``provision()`` (ssh, onepassword,
        core._write_env_file) are patched at their origin so the deferred
        ``import`` picks up the mock.
        """
        mocks: dict[str, MagicMock] = {}
        mocks["create_user"] = mocker.patch(
            "devbox.providers.local.macos.create_user", return_value="dx-test-box"
        )
        mocks["generate_keypair"] = mocker.patch(
            "devbox.ssh.generate_keypair",
            return_value="ssh-ed25519 AAAA fake-public-key",
        )
        mocks["populate_authorized_keys"] = mocker.patch(
            "devbox.ssh.populate_authorized_keys",
        )
        mocks["add_ssh_key"] = mocker.patch(
            "devbox.providers.local.github.add_ssh_key", return_value=42
        )
        mocks["resolve_env_vars"] = mocker.patch(
            "devbox.onepassword.resolve_env_vars",
            return_value={"MY_TOKEN": "resolved-secret"},
        )
        mocks["ensure_ssh_access"] = mocker.patch(
            "devbox.providers.local.sshd.ensure_ssh_access",
        )
        mocks["create_profile"] = mocker.patch(
            "devbox.providers.local.iterm2.create_profile",
        )
        return mocks

    def test_happy_path_no_env_vars(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()
        preset = _minimal_preset()

        result = provider.provision("test-box", preset)

        assert result == {
            "username": "dx-test-box",
            "home_dir": "/Users/dx-test-box",
            "github_key_id": 42,
        }
        mocks["create_user"].assert_called_once_with("test-box")
        mocks["resolve_env_vars"].assert_not_called()

    def test_happy_path_with_env_vars(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        mock_write_env = mocker.patch("devbox.core._write_env_file")
        provider = LocalProvider()
        preset = _minimal_preset(env_vars={"MY_TOKEN": "op://vault/item/field"})

        result = provider.provision("test-box", preset)

        assert result["username"] == "dx-test-box"
        mocks["resolve_env_vars"].assert_called_once_with(
            {"MY_TOKEN": "op://vault/item/field"}
        )
        from pathlib import Path

        mock_write_env.assert_called_once_with(
            Path("/Users/dx-test-box"),
            {"MY_TOKEN": "resolved-secret"},
            target_user="dx-test-box",
        )

    def test_calls_modules_in_correct_order(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        call_order: list[str] = []

        def _make_side_effect(
            label: str, ret: object = None
        ) -> Any:
            def _side_effect(*a: object, **kw: object) -> Any:
                call_order.append(label)
                return ret
            return _side_effect

        mocks["create_user"].side_effect = _make_side_effect("create_user", "dx-test-box")
        mocks["generate_keypair"].side_effect = _make_side_effect(
            "generate_keypair", "ssh-ed25519 AAAA"
        )
        mocks["populate_authorized_keys"].side_effect = _make_side_effect(
            "populate_authorized_keys"
        )
        mocks["add_ssh_key"].side_effect = _make_side_effect("add_ssh_key", 42)
        mocks["ensure_ssh_access"].side_effect = _make_side_effect("ensure_ssh_access")
        mocks["create_profile"].side_effect = _make_side_effect("create_profile")

        provider = LocalProvider()
        provider.provision("test-box", _minimal_preset())

        assert call_order == [
            "create_user",
            "generate_keypair",
            "populate_authorized_keys",
            "add_ssh_key",
            "ensure_ssh_access",
            "create_profile",
        ]

    def test_generate_keypair_receives_home_dir(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()

        provider.provision("test-box", _minimal_preset())

        from pathlib import Path

        mocks["generate_keypair"].assert_called_once_with(Path("/Users/dx-test-box"))

    def test_populate_authorized_keys_receives_user(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()

        provider.provision("test-box", _minimal_preset())

        from pathlib import Path

        mocks["populate_authorized_keys"].assert_called_once_with(
            Path("/Users/dx-test-box"), target_user="dx-test-box"
        )

    def test_add_ssh_key_uses_github_account(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()

        provider.provision("test-box", _minimal_preset(github_account="myorg"))

        mocks["add_ssh_key"].assert_called_once_with(
            "devbox:test-box", "ssh-ed25519 AAAA fake-public-key", "myorg"
        )

    def test_ensure_ssh_access_receives_username(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()

        provider.provision("test-box", _minimal_preset())

        mocks["ensure_ssh_access"].assert_called_once_with("dx-test-box")

    def test_iterm2_profile_receives_name_and_preset(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()
        preset = _minimal_preset()

        provider.provision("test-box", preset)

        mocks["create_profile"].assert_called_once()
        args = mocks["create_profile"].call_args
        assert args[0][0] == "test-box"
        # Second arg should be a Preset object
        from devbox.presets import Preset

        assert isinstance(args[0][1], Preset)

    def test_write_env_file_delegated_to_core(self, mocker: MockerFixture) -> None:
        self._mock_modules(mocker)
        mock_write_env = mocker.patch("devbox.core._write_env_file")
        provider = LocalProvider()
        preset = _minimal_preset(env_vars={"SECRET": "op://v/i/f"})

        provider.provision("test-box", preset)

        mock_write_env.assert_called_once()
        call_kwargs = mock_write_env.call_args
        assert call_kwargs[1]["target_user"] == "dx-test-box"

    def test_invalid_preset_raises_validation_error(self, mocker: MockerFixture) -> None:
        self._mock_modules(mocker)
        provider = LocalProvider()
        bad_preset: dict[str, Any] = {"name": "x"}  # missing required fields

        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            provider.provision("test-box", bad_preset)


class TestLocalProviderDestroy:
    """Test LocalProvider.destroy orchestration."""

    def _mock_modules(self, mocker: MockerFixture) -> dict[str, MagicMock]:
        mocks: dict[str, MagicMock] = {}
        mocks["remove_ssh_key"] = mocker.patch(
            "devbox.providers.local.github.remove_ssh_key",
        )
        mocks["remove_user_from_ssh_group"] = mocker.patch(
            "devbox.providers.local.sshd.remove_user_from_ssh_group",
        )
        mocks["delete_user"] = mocker.patch(
            "devbox.providers.local.macos.delete_user",
        )
        mocks["remove_profile"] = mocker.patch(
            "devbox.providers.local.iterm2.remove_profile",
        )
        return mocks

    def test_happy_path(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        provider.destroy("test-box", entry)

        mocks["remove_ssh_key"].assert_called_once_with("99", "octocat")
        mocks["remove_user_from_ssh_group"].assert_called_once_with("dx-test-box")
        mocks["delete_user"].assert_called_once_with("test-box")
        mocks["remove_profile"].assert_called_once_with("test-box")

    def test_missing_github_info_skips_key_removal(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()
        entry: dict[str, Any] = {}

        provider.destroy("test-box", entry)

        mocks["remove_ssh_key"].assert_not_called()
        mocks["remove_user_from_ssh_group"].assert_called_once()
        mocks["delete_user"].assert_called_once()
        mocks["remove_profile"].assert_called_once()

    def test_missing_github_key_id_skips_key_removal(self, mocker: MockerFixture) -> None:
        mocks = self._mock_modules(mocker)
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_account": "octocat"}

        provider.destroy("test-box", entry)

        mocks["remove_ssh_key"].assert_not_called()

    def test_github_failure_logs_warning_and_continues(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocks = self._mock_modules(mocker)
        mocks["remove_ssh_key"].side_effect = Exception("GitHub API error")
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        with caplog.at_level(logging.WARNING):
            provider.destroy("test-box", entry)

        assert "Failed to remove GitHub key" in caplog.text
        mocks["remove_user_from_ssh_group"].assert_called_once()
        mocks["delete_user"].assert_called_once()
        mocks["remove_profile"].assert_called_once()

    def test_sshd_failure_logs_warning_and_continues(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocks = self._mock_modules(mocker)
        mocks["remove_user_from_ssh_group"].side_effect = Exception("sshd error")
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        with caplog.at_level(logging.WARNING):
            provider.destroy("test-box", entry)

        assert "Failed to remove from SSH group" in caplog.text
        mocks["delete_user"].assert_called_once()
        mocks["remove_profile"].assert_called_once()

    def test_macos_failure_logs_warning_and_continues(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocks = self._mock_modules(mocker)
        mocks["delete_user"].side_effect = Exception("dscl error")
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        with caplog.at_level(logging.WARNING):
            provider.destroy("test-box", entry)

        assert "Failed to delete macOS user" in caplog.text
        mocks["remove_profile"].assert_called_once()

    def test_iterm2_failure_logs_warning(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocks = self._mock_modules(mocker)
        mocks["remove_profile"].side_effect = Exception("plist error")
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        with caplog.at_level(logging.WARNING):
            provider.destroy("test-box", entry)

        assert "Failed to remove iTerm2 profile" in caplog.text

    def test_all_steps_fail_logs_all_warnings(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        mocks = self._mock_modules(mocker)
        mocks["remove_ssh_key"].side_effect = Exception("gh fail")
        mocks["remove_user_from_ssh_group"].side_effect = Exception("sshd fail")
        mocks["delete_user"].side_effect = Exception("macos fail")
        mocks["remove_profile"].side_effect = Exception("iterm fail")
        provider = LocalProvider()
        entry: dict[str, Any] = {"github_key_id": 99, "github_account": "octocat"}

        with caplog.at_level(logging.WARNING):
            provider.destroy("test-box", entry)

        assert "Failed to remove GitHub key" in caplog.text
        assert "Failed to remove from SSH group" in caplog.text
        assert "Failed to delete macOS user" in caplog.text
        assert "Failed to remove iTerm2 profile" in caplog.text
