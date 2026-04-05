# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for auth injection module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from devbox.auth import (
    _validate_aws_values,
    inject_auth,
    inject_aws_auth,
)
from devbox.exceptions import AuthError
from devbox.presets import Preset

# Valid AWS test values that pass regex validation
_VALID_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
_VALID_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
_VALID_REGION = "us-west-2"
_VALID_REGION_ALT = "us-east-1"
_VALID_REGION_EU = "eu-west-1"


def _make_preset(
    provider: str = "local",
    aws_profile: str = "",
) -> Preset:
    """Create a minimal Preset for testing."""
    return Preset(
        name="test",
        description="test preset",
        provider=provider,
        aws_profile=aws_profile,
        github_account="octocat",
    )


class TestInjectAwsAuth:
    def test_writes_aws_config_and_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION],
        )
        mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        inject_aws_auth(tmp_path, preset, "dx-test")

        config = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
        assert "[profile default]" in config
        assert f"region = {_VALID_REGION}" in config

        creds = (tmp_path / ".aws" / "credentials").read_text(encoding="utf-8")
        assert "[default]" in creds
        assert f"aws_access_key_id = {_VALID_ACCESS_KEY}" in creds
        assert f"aws_secret_access_key = {_VALID_SECRET_KEY}" in creds

    def test_aws_dir_permissions_0700(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION_ALT],
        )
        mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        inject_aws_auth(tmp_path, preset, "dx-test")

        mode = os.stat(tmp_path / ".aws").st_mode & 0o777
        assert mode == 0o700

    def test_aws_files_permissions_0600(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION_ALT],
        )
        mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        inject_aws_auth(tmp_path, preset, "dx-test")

        for name in ("config", "credentials"):
            mode = os.stat(tmp_path / ".aws" / name).st_mode & 0o777
            assert mode == 0o600, f"{name} should be 0600"

    def test_chowns_aws_dir(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION_ALT],
        )
        mock_chown = mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        inject_aws_auth(tmp_path, preset, "dx-test")

        mock_chown.assert_called_once_with(tmp_path / ".aws", "dx-test")

    def test_raises_auth_error_on_wrong_provider(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        preset = _make_preset(provider="local")
        with pytest.raises(AuthError, match="requires provider 'aws'"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_raises_auth_error_when_aws_profile_empty(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        preset = _make_preset(provider="aws", aws_profile="")
        with pytest.raises(AuthError, match="aws_profile is required"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_raises_auth_error_on_secret_failure(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=Exception("vault locked"),
        )
        preset = _make_preset(provider="aws", aws_profile="my-profile")
        with pytest.raises(AuthError, match="Failed to resolve AWS credentials"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_resolves_correct_op_references(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_get = mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION_EU],
        )
        mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="acme-prod")
        inject_aws_auth(tmp_path, preset, "dx-test")

        assert mock_get.call_count == 3
        mock_get.assert_any_call("op://Development/acme-prod/access-key-id")
        mock_get.assert_any_call("op://Development/acme-prod/secret-access-key")
        mock_get.assert_any_call("op://Development/acme-prod/region")

    def test_raises_auth_error_on_write_failure(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION_ALT],
        )
        mocker.patch("devbox.auth.chown_path")
        mocker.patch("pathlib.Path.mkdir", side_effect=PermissionError("denied"))

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        with pytest.raises(AuthError, match="Failed to write AWS credentials"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_config_contains_output_json(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, _VALID_REGION],
        )
        mocker.patch("devbox.auth.chown_path")

        preset = _make_preset(provider="aws", aws_profile="my-profile")
        inject_aws_auth(tmp_path, preset, "dx-test")

        config = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
        assert "output = json" in config


class TestValidateAwsValues:
    def test_valid_values_pass(self) -> None:
        # Should not raise
        _validate_aws_values(_VALID_REGION, _VALID_ACCESS_KEY, _VALID_SECRET_KEY)

    def test_invalid_region_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS region format"):
            _validate_aws_values("not-a-region!", _VALID_ACCESS_KEY, _VALID_SECRET_KEY)

    def test_region_with_uppercase_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS region format"):
            _validate_aws_values("US-WEST-2", _VALID_ACCESS_KEY, _VALID_SECRET_KEY)

    def test_empty_region_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS region format"):
            _validate_aws_values("", _VALID_ACCESS_KEY, _VALID_SECRET_KEY)

    def test_invalid_access_key_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS access key format"):
            _validate_aws_values(_VALID_REGION, "short", _VALID_SECRET_KEY)

    def test_access_key_with_lowercase_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS access key format"):
            _validate_aws_values(_VALID_REGION, "akiaiosfodnn7example", _VALID_SECRET_KEY)

    def test_invalid_secret_key_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS secret key format"):
            _validate_aws_values(_VALID_REGION, _VALID_ACCESS_KEY, "short")

    def test_secret_key_with_special_chars_raises(self) -> None:
        with pytest.raises(AuthError, match="Invalid AWS secret key format"):
            _validate_aws_values(_VALID_REGION, _VALID_ACCESS_KEY, "x" * 16 + "!@#$%^&*()")

    def test_inject_aws_rejects_invalid_region(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY, "INVALID"],
        )
        preset = _make_preset(provider="aws", aws_profile="my-profile")
        with pytest.raises(AuthError, match="Invalid AWS region format"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_inject_aws_rejects_invalid_access_key(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=["bad", _VALID_SECRET_KEY, _VALID_REGION],
        )
        preset = _make_preset(provider="aws", aws_profile="my-profile")
        with pytest.raises(AuthError, match="Invalid AWS access key format"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_inject_aws_rejects_invalid_secret_key(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, "bad", _VALID_REGION],
        )
        preset = _make_preset(provider="aws", aws_profile="my-profile")
        with pytest.raises(AuthError, match="Invalid AWS secret key format"):
            inject_aws_auth(tmp_path, preset, "dx-test")


class TestInjectAuth:
    def test_local_provider_is_noop(self, tmp_path: Path, mocker: MockerFixture) -> None:
        preset = _make_preset(provider="local")
        inject_auth(tmp_path, preset, "dx-test")  # should not raise

    def test_dispatches_to_aws_for_aws(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_aws = mocker.patch("devbox.auth.inject_aws_auth")

        preset = _make_preset(provider="aws", aws_profile="prof")
        inject_auth(tmp_path, preset, "dx-test")

        mock_aws.assert_called_once_with(tmp_path, preset, "dx-test")

    def test_raises_auth_error_for_unknown_provider(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        # Force an invalid provider by bypassing validation
        preset = _make_preset(provider="local")
        object.__setattr__(preset, "provider", "gcp")

        with pytest.raises(AuthError, match="Unknown provider"):
            inject_auth(tmp_path, preset, "dx-test")

    def test_propagates_aws_error(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.inject_aws_auth",
            side_effect=AuthError("aws boom"),
        )

        preset = _make_preset(provider="aws", aws_profile="prof")
        with pytest.raises(AuthError, match="aws boom"):
            inject_auth(tmp_path, preset, "dx-test")
