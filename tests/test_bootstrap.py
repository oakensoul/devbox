"""Tests for bootstrap module — nvm, pyenv, brew extras, npm/pip globals."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.bootstrap import (
    _run_checked,
    bootstrap_user,
    install_brew_extras,
    install_npm_globals,
    install_nvm,
    install_pip_globals,
    install_pyenv,
)
from devbox.exceptions import BootstrapError
from devbox.presets import Preset


def _ok(stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a successful CompletedProcess mock."""
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


def _fail(code: int = 1, stderr: str = "boom") -> MagicMock:
    """Return a failed CompletedProcess mock."""
    return MagicMock(returncode=code, stdout="", stderr=stderr)


def _preset(**overrides: object) -> Preset:
    """Build a minimal valid Preset with optional overrides."""
    defaults: dict[str, object] = {
        "name": "test",
        "description": "test preset",
        "provider": "local",
        "github_account": "octocat",
        "node_version": "lts",
        "python_version": "3.12",
        "brew_extras": [],
        "npm_globals": [],
        "pip_globals": [],
    }
    defaults.update(overrides)
    return Preset.model_validate(defaults)


HOME = Path("/Users/dx-test")
USERNAME = "dx-test"


# ---------------------------------------------------------------------------
# _run_checked
# ---------------------------------------------------------------------------


class TestRunChecked:
    def test_success(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        result = _run_checked(["echo", "hi"], error_prefix="test", timeout=10)
        assert result.returncode == 0
        mock_run.assert_called_once()

    def test_nonzero_exit(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="exit code 1"):
            _run_checked(["false"], error_prefix="test", timeout=10)

    def test_nonzero_exit_includes_stderr(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail(stderr="details"))
        with pytest.raises(BootstrapError, match="details"):
            _run_checked(["false"], error_prefix="test", timeout=10)

    def test_file_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=FileNotFoundError("no such file"),
        )
        with pytest.raises(BootstrapError, match="command not found"):
            _run_checked(["nope"], error_prefix="test", timeout=10)

    def test_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10),
        )
        with pytest.raises(BootstrapError, match="timed out"):
            _run_checked(["slow"], error_prefix="test", timeout=10)

    def test_stderr_truncated(self, mocker: MockerFixture) -> None:
        long_err = "x" * 1000
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail(stderr=long_err))
        with pytest.raises(BootstrapError) as exc_info:
            _run_checked(["fail"], error_prefix="test", timeout=10)
        # stderr tail is capped at 500 chars
        assert len(str(exc_info.value)) <= 600


# ---------------------------------------------------------------------------
# install_nvm
# ---------------------------------------------------------------------------


class TestInstallNvm:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_nvm(HOME, "lts", USERNAME)
        assert mock_run.call_count == 2

    def test_nvm_script_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="nvm install"):
            install_nvm(HOME, "lts", USERNAME)

    def test_node_install_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(stderr="node build failed")],
        )
        with pytest.raises(BootstrapError, match="node lts install"):
            install_nvm(HOME, "lts", USERNAME)


# ---------------------------------------------------------------------------
# install_pyenv
# ---------------------------------------------------------------------------


class TestInstallPyenv:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_pyenv(HOME, "3.12", USERNAME)
        assert mock_run.call_count == 2

    def test_pyenv_script_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="pyenv install"):
            install_pyenv(HOME, "3.12", USERNAME)

    def test_python_build_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(stderr="python build failed")],
        )
        with pytest.raises(BootstrapError, match=r"python 3\.12 install"):
            install_pyenv(HOME, "3.12", USERNAME)


# ---------------------------------------------------------------------------
# install_brew_extras
# ---------------------------------------------------------------------------


class TestInstallBrewExtras:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_brew_extras(["jq", "ripgrep"])
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["brew", "install"]
        assert "jq" in cmd
        assert "ripgrep" in cmd

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_brew_extras([])
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="brew install"):
            install_brew_extras(["bad-pkg"])


# ---------------------------------------------------------------------------
# install_npm_globals
# ---------------------------------------------------------------------------


class TestInstallNpmGlobals:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_npm_globals(HOME, ["typescript", "ts-node"], USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_npm_globals(HOME, [], USERNAME)
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="npm globals"):
            install_npm_globals(HOME, ["bad"], USERNAME)


# ---------------------------------------------------------------------------
# install_pip_globals
# ---------------------------------------------------------------------------


class TestInstallPipGlobals:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_pip_globals(HOME, ["black", "ruff"], USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_pip_globals(HOME, [], USERNAME)
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="pip globals"):
            install_pip_globals(HOME, ["bad"], USERNAME)


# ---------------------------------------------------------------------------
# bootstrap_user
# ---------------------------------------------------------------------------


class TestBootstrapUser:
    def test_all_steps_succeed(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert warnings == []

    def test_nvm_failure_continues(self, mocker: MockerFixture) -> None:
        """nvm failure should warn but not block pyenv/brew/npm/pip."""
        effects = [_fail(), _ok(), _ok(), _ok()]  # nvm fails on first call
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "nvm" in warnings[0].lower()

    def test_pyenv_failure_continues(self, mocker: MockerFixture) -> None:
        # nvm succeeds (2 calls), pyenv fails on first call
        effects = [_ok(), _ok(), _fail(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "pyenv" in warnings[0].lower()

    def test_brew_failure_continues(self, mocker: MockerFixture) -> None:
        # nvm(2) + pyenv(2) succeed, brew fails
        effects = [_ok(), _ok(), _ok(), _ok(), _fail()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(brew_extras=["jq"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "brew" in warnings[0].lower()

    def test_all_steps_fail(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        preset = _preset(brew_extras=["jq"], npm_globals=["ts"], pip_globals=["black"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 5

    def test_empty_optional_lists_skip(self, mocker: MockerFixture) -> None:
        """With empty brew/npm/pip lists, only nvm + pyenv are called."""
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert warnings == []
        # nvm = 2 calls, pyenv = 2 calls, brew/npm/pip = 0
        assert mock_run.call_count == 4

    def test_npm_failure_still_runs_pip(self, mocker: MockerFixture) -> None:
        # nvm(2) + pyenv(2) + brew(0) + npm(1 fail) + pip(1 ok)
        effects = [_ok(), _ok(), _ok(), _ok(), _fail(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(npm_globals=["ts"], pip_globals=["black"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "npm" in warnings[0].lower()

    def test_pip_failure_is_last_warning(self, mocker: MockerFixture) -> None:
        # nvm(2) + pyenv(2) + brew(0) + npm(0) + pip(1 fail)
        effects = [_ok(), _ok(), _ok(), _ok(), _fail()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(pip_globals=["bad"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "pip" in warnings[0].lower()
