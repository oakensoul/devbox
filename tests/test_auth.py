# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for auth injection module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from devbox.auth import (
    _validate_aws_keys,
    inject_auth,
    inject_aws_auth,
    render_aws_files,
)
from devbox.exceptions import AuthError
from devbox.presets import Preset

_VALID_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
_VALID_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
_OP_ACCESS = "op://Dev/acme/access_key_id"
_OP_SECRET = "op://Dev/acme/secret_access_key"


def _static_profile(name: str = "acme", region: str = "us-east-1") -> dict[str, Any]:
    return {
        "name": name,
        "type": "static",
        "region": region,
        "access_key_id": _OP_ACCESS,
        "secret_access_key": _OP_SECRET,
    }


def _sso_profile(name: str = "splash-dev") -> dict[str, Any]:
    return {
        "name": name,
        "type": "sso",
        "region": "us-east-1",
        "sso_start_url": "https://splash.awsapps.com/start",
        "sso_region": "us-east-1",
        "sso_account_id": "123456789012",
        "sso_role_name": "DeveloperAccess",
    }


def _make_preset(aws: dict[str, Any] | None = None, provider: str = "local") -> Preset:
    data: dict[str, Any] = {
        "name": "test",
        "description": "test preset",
        "provider": provider,
        "github_account": "octocat",
    }
    if aws is not None:
        data["aws"] = aws
    return Preset(**data)


class TestInjectAwsAuthNoBlock:
    def test_noop_when_no_aws_block(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_chown = mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(aws=None)
        result = inject_aws_auth(tmp_path, preset, "dx-test")
        assert result == []
        assert not (tmp_path / ".aws").exists()
        mock_chown.assert_not_called()


class TestInjectAwsAuthStatic:
    def _prep(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        mocker.patch("devbox.auth.chown_path")

    def test_writes_config_and_credentials(self, tmp_path: Path, mocker: MockerFixture) -> None:
        self._prep(mocker)
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        sso = inject_aws_auth(tmp_path, preset, "dx-test")
        assert sso == []

        config = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
        assert "[profile acme]" in config
        assert "region = us-east-1" in config
        assert "output = json" in config

        creds = (tmp_path / ".aws" / "credentials").read_text(encoding="utf-8")
        assert "[acme]" in creds
        assert f"aws_access_key_id = {_VALID_ACCESS_KEY}" in creds
        assert f"aws_secret_access_key = {_VALID_SECRET_KEY}" in creds
        assert "[default]" not in creds

    def test_dir_0700_files_0600(self, tmp_path: Path, mocker: MockerFixture) -> None:
        self._prep(mocker)
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        inject_aws_auth(tmp_path, preset, "dx-test")

        assert os.stat(tmp_path / ".aws").st_mode & 0o777 == 0o700
        for name in ("config", "credentials"):
            assert os.stat(tmp_path / ".aws" / name).st_mode & 0o777 == 0o600

    def test_chowns_aws_dir(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        mock_chown = mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        inject_aws_auth(tmp_path, preset, "dx-test")
        mock_chown.assert_called_once_with(tmp_path / ".aws", "dx-test")

    def test_resolves_op_refs(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_get = mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        inject_aws_auth(tmp_path, preset, "dx-test")
        mock_get.assert_any_call(_OP_ACCESS)
        mock_get.assert_any_call(_OP_SECRET)
        assert mock_get.call_count == 2

    def test_raises_on_secret_failure(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.auth.get_secret", side_effect=Exception("vault locked"))
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        with pytest.raises(AuthError, match="Failed to resolve AWS credentials"):
            inject_aws_auth(tmp_path, preset, "dx-test")

    def test_rejects_invalid_access_key(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret", side_effect=["bad-key", _VALID_SECRET_KEY]
        )
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        with pytest.raises(AuthError, match="Invalid AWS access key"):
            inject_aws_auth(tmp_path, preset, "dx-test")


class TestInjectAwsAuthSso:
    def test_writes_sso_block_to_config(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={"default_profile": "splash-dev", "profiles": [_sso_profile()]},
        )
        sso = inject_aws_auth(tmp_path, preset, "dx-test")
        assert sso == ["splash-dev"]

        config = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
        assert "[profile splash-dev]" in config
        assert "sso_start_url = https://splash.awsapps.com/start" in config
        assert "sso_account_id = 123456789012" in config
        assert "sso_role_name = DeveloperAccess" in config

        # Credentials file is not written when no static profiles are present.
        assert not (tmp_path / ".aws" / "credentials").exists()

    def test_no_op_calls_for_sso_only(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_get = mocker.patch("devbox.auth.get_secret")
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={"default_profile": "splash-dev", "profiles": [_sso_profile()]},
        )
        inject_aws_auth(tmp_path, preset, "dx-test")
        mock_get.assert_not_called()


class TestInjectAwsAuthMixed:
    def test_static_plus_sso(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            aws={
                "default_profile": "acme",
                "profiles": [_static_profile(), _sso_profile()],
            },
        )
        sso = inject_aws_auth(tmp_path, preset, "dx-test")
        assert sso == ["splash-dev"]

        config = (tmp_path / ".aws" / "config").read_text(encoding="utf-8")
        assert "[profile acme]" in config
        assert "[profile splash-dev]" in config

        creds = (tmp_path / ".aws" / "credentials").read_text(encoding="utf-8")
        assert "[acme]" in creds
        assert "splash-dev" not in creds


class TestValidateAwsKeys:
    def test_valid_passes(self) -> None:
        _validate_aws_keys(_VALID_ACCESS_KEY, _VALID_SECRET_KEY)

    def test_bad_access_key_raises(self) -> None:
        with pytest.raises(AuthError, match="access key"):
            _validate_aws_keys("short", _VALID_SECRET_KEY)

    def test_bad_secret_key_raises(self) -> None:
        with pytest.raises(AuthError, match="secret key"):
            _validate_aws_keys(_VALID_ACCESS_KEY, "short")


class TestInjectAuth:
    def test_local_provider_no_aws(self, tmp_path: Path, mocker: MockerFixture) -> None:
        preset = _make_preset(provider="local")
        assert inject_auth(tmp_path, preset, "dx-test") == []

    def test_local_provider_with_aws_still_injects(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        mocker.patch("devbox.auth.chown_path")
        preset = _make_preset(
            provider="local",
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        inject_auth(tmp_path, preset, "dx-test")
        assert (tmp_path / ".aws" / "credentials").exists()

    def test_unknown_provider_raises(self, tmp_path: Path) -> None:
        preset = _make_preset(provider="local")
        object.__setattr__(preset, "provider", "gcp")
        with pytest.raises(AuthError, match="Unknown provider"):
            inject_auth(tmp_path, preset, "dx-test")


class TestRenderAwsFiles:
    def test_render_static_only(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.auth.get_secret",
            side_effect=[_VALID_ACCESS_KEY, _VALID_SECRET_KEY],
        )
        preset = _make_preset(
            aws={"default_profile": "acme", "profiles": [_static_profile()]},
        )
        config, creds, sso = render_aws_files(preset)
        assert sso == []
        assert "[profile acme]" in config
        assert f"aws_access_key_id = {_VALID_ACCESS_KEY}" in creds


class TestLogSsoHints:
    def test_emits_login_hint_per_profile(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from devbox.auth import log_sso_hints

        with caplog.at_level(logging.INFO, logger="devbox.auth"):
            log_sso_hints(["p1", "p2"])

        messages = [r.getMessage() for r in caplog.records]
        joined = "\n".join(messages)
        assert "aws sso login --profile p1" in joined
        assert "aws sso login --profile p2" in joined

    def test_empty_list_is_noop(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from devbox.auth import log_sso_hints

        with caplog.at_level(logging.INFO, logger="devbox.auth"):
            log_sso_hints([])

        assert caplog.records == []


class TestRenderAwsFilesNoBlock:
    def test_returns_empty_when_no_aws_block(self) -> None:
        from devbox.auth import AwsRender

        preset = _make_preset(aws=None)
        assert render_aws_files(preset) == AwsRender("", "", [])
